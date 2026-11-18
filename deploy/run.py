"""Run a single web process and its loopback-only BridgeCLI engine."""

import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import urllib.request


def main():
    def shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    environment = dict(os.environ)
    environment.pop('GEMINI_API_KEY', None)
    key = Path('/run/shift-bridge/gemini.key').read_text(encoding='utf-8').strip()
    if not key:
        raise RuntimeError('The mounted Gemini credential is empty.')
    token = secrets.token_urlsafe(32)
    engine_port = '8011'
    engine_url = f'http://127.0.0.1:{engine_port}'
    shared = {**environment, 'HYBRID_API_AUTH_TOKEN': token}
    engine_env = {**shared, 'GEMINI_API_KEY': key, 'BRIDGE_PORT': engine_port, 'BRIDGE_DATA_DIR': '/data/engine'}
    web_env = {**shared, 'PORT': '8000', 'SHIFT_BRIDGE_WEB_HOST': '0.0.0.0',
               'SHIFT_BRIDGE_DB_PATH': '/data/web/shift_bridge.db', 'SHIFT_BRIDGE_SEED_DEMO': '0',
               'SHIFT_BRIDGE_ENGINE_URL': engine_url}
    processes = []
    try:
        processes.append(subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'api_server:app', '--host', '127.0.0.1',
             '--port', engine_port, '--no-access-log'], cwd='/app/BridgeCLI', env=engine_env,
            user=10002, group=10002, extra_groups=[],
        ))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 20
        while processes[0].poll() is None and time.monotonic() < deadline:
            try:
                with opener.open(f'{engine_url}/health', timeout=1) as response:
                    health = json.load(response)
            except OSError:
                time.sleep(0.25)
                continue
            if health.get('api_key_configured') and health.get('auth_configured'):
                break
        else:
            raise RuntimeError('BridgeCLI did not start.')
        processes.append(subprocess.Popen([sys.executable, 'app.py'], cwd='/app/Agent', env=web_env,
                                          user=10001, group=10001, extra_groups=[]))
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    sys.exit(main())
