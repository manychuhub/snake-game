"""Run a single web process and its loopback-only BridgeCLI engine."""

import json
import os
from pathlib import Path
import secrets
import re
import signal
import subprocess
import sys
import time
import urllib.request


def render_settings(environment):
    legacy_user = environment.pop('SHIFT_BRIDGE_WEB_USER', 'admin')
    legacy_password = environment.pop('SHIFT_BRIDGE_WEB_PASSWORD', '')
    username = environment.pop('SHIFT_BRIDGE_ADMIN_USER', legacy_user)
    configured_password = environment.pop('SHIFT_BRIDGE_ADMIN_PASSWORD', '')
    password = configured_password or legacy_password
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,64}', username):
        raise RuntimeError('SHIFT_BRIDGE_ADMIN_USER must be 3–64 letters, numbers, dots, underscores or dashes.')
    if password and not 24 <= len(password) <= 256:
        raise RuntimeError('Set SHIFT_BRIDGE_ADMIN_PASSWORD to a long random password (24–256 characters).')
    origin = environment.get('RENDER_EXTERNAL_URL', '').rstrip('/')
    if not re.fullmatch(r'https://[a-z0-9-]+\.onrender\.com', origin):
        raise RuntimeError('Render must provide a valid RENDER_EXTERNAL_URL for the web service.')
    port = int(environment.get('PORT', '10000'))
    if port == 8011 or not 1 <= port <= 65535:
        raise RuntimeError('Choose a valid Render PORT different from BridgeCLI port 8011.')
    data = Path('/var/data')
    for directory, uid in ((data / 'web', 10001), (data / 'engine', 10002)):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(directory, uid, uid)
        directory.chmod(0o700)
    environment.pop('SHIFT_BRIDGE_ALB_ARN', None)
    return data, {
        'PORT': str(port), 'SHIFT_BRIDGE_PUBLIC_ORIGIN': origin,
        'SHIFT_BRIDGE_ADMIN_USER': username,
        'SHIFT_BRIDGE_ADMIN_PASSWORD': password,
        'SHIFT_BRIDGE_ADMIN_SYNC_PASSWORD': '1' if configured_password else '0',
    }


def main():
    def shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    environment = dict(os.environ)
    key = environment.pop('GEMINI_API_KEY', '').strip()
    environment.pop('SHIFT_BRIDGE_WEB_CREDENTIAL', None)
    on_render = environment.get('RENDER') == 'true'
    if on_render:
        data, web_settings = render_settings(environment)
    else:
        key = Path('/run/shift-bridge/gemini.key').read_text(encoding='utf-8').strip()
        if not key:
            raise RuntimeError('The mounted Gemini credential is empty.')
        data, web_settings = Path('/data'), {'PORT': '8000'}
    for name in ('SHIFT_BRIDGE_ADMIN_USER', 'SHIFT_BRIDGE_ADMIN_PASSWORD'):
        if name in environment:
            web_settings[name] = environment.pop(name)
    token = secrets.token_urlsafe(32)
    engine_port = '8011'
    engine_url = f'http://127.0.0.1:{engine_port}'
    shared = {**environment, 'HYBRID_API_AUTH_TOKEN': token}
    engine_env = {**shared, 'GEMINI_API_KEY': key, 'BRIDGE_PORT': engine_port, 'BRIDGE_DATA_DIR': str(data / 'engine')}
    web_env = {**shared, **web_settings, 'SHIFT_BRIDGE_WEB_HOST': '0.0.0.0',
               'SHIFT_BRIDGE_DB_PATH': str(data / 'web/shift_bridge.db'), 'SHIFT_BRIDGE_SEED_DEMO': '0',
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
            if health.get('auth_configured') and (on_render or health.get('api_key_configured')):
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
