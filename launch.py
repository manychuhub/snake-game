"""Start one portable web app and its local AI engine."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "BridgeCLI"


def ensure_environment():
    settings = ENGINE / ".env"
    if not settings.exists():
        settings.write_text(
            f"GEMINI_API_KEY=\nHYBRID_API_AUTH_TOKEN={secrets.token_urlsafe(32)}\nBRIDGE_PORT=8011\n",
            encoding="utf-8",
        )

    interpreter = ENGINE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(ENGINE / ".venv")], check=True)
    check = subprocess.run(
        [str(interpreter), "-c", "import fastapi, uvicorn, dotenv, httpx, psycopg"],
        capture_output=True,
    )
    if check.returncode:
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", "requirements.txt"], cwd=ENGINE, check=True)

    setup = "import config,json; print(json.dumps([config.PORT, config.TOKEN, bool(config.KEY)]))"
    port, token, has_key = json.loads(subprocess.check_output([str(interpreter), "-c", setup], cwd=ENGINE))
    if not token:
        token = secrets.token_urlsafe(32)
        save_token = (
            "import sys; from dotenv import set_key; "
            "set_key('.env', 'HYBRID_API_AUTH_TOKEN', sys.stdin.read(), quote_mode='never')"
        )
        subprocess.run([str(interpreter), "-c", save_token], cwd=ENGINE, input=token, text=True, check=True)
    return interpreter, port, token, has_key


def wait_ready(process, url):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited while starting: {url}")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError(f"Server did not respond: {url}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", choices=("Agent", "test"), nargs="?", default="Agent")
    args = parser.parse_args()
    interpreter, engine_port, token, has_key = ensure_environment()
    web_port = 8000 if args.app == "Agent" else 8001
    if engine_port == web_port:
        raise RuntimeError("Choose a different BRIDGE_PORT in BridgeCLI/.env.")
    for port in (engine_port, web_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(f"Port {port} is already in use.") from error

    engine_url = f"http://127.0.0.1:{engine_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    web_dsn = os.getenv('SHIFT_BRIDGE_DATABASE_URL') if args.app == 'Agent' else None
    common = {key: value for key, value in os.environ.items()
              if key not in {'SHIFT_BRIDGE_DATABASE_URL', 'SHIFT_BRIDGE_ENGINE_DATABASE_URL'}}
    common['PYTHONPATH'] = os.pathsep.join(filter(None, (str(ROOT), common.get('PYTHONPATH'))))
    engine_environment = {key: value for key, value in common.items() if not key.startswith('SHIFT_BRIDGE_DCO_')}
    engine_environment['HYBRID_API_AUTH_TOKEN'] = token
    if engine_dsn := os.getenv('SHIFT_BRIDGE_ENGINE_DATABASE_URL'):
        engine_environment['SHIFT_BRIDGE_ENGINE_DATABASE_URL'] = engine_dsn
    processes = []
    try:
        processes.append(subprocess.Popen(
            [str(interpreter), "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1", "--port", str(engine_port)],
            cwd=ENGINE,
            env=engine_environment,
        ))
        wait_ready(processes[-1], engine_url + "/health")
        web_environment = {key: value for key, value in common.items() if key != "GEMINI_API_KEY"}
        if web_dsn:
            web_environment['SHIFT_BRIDGE_DATABASE_URL'] = web_dsn
        processes.append(subprocess.Popen(
            [str(interpreter) if web_dsn else sys.executable, "app.py"],
            cwd=ROOT / args.app,
            env={**web_environment, "PORT": str(web_port), "SHIFT_BRIDGE_ENGINE_URL": engine_url,
                 "HYBRID_API_AUTH_TOKEN": token},
        ))
        wait_ready(processes[-1], web_url)
        print(f"Web: {web_url} | BridgeCLI: {engine_url} | Stop: Ctrl+C", flush=True)
        if not has_key:
            print("Gemini is not configured. The web interface is available. Set GEMINI_API_KEY in BridgeCLI/.env and restart to use AI features.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("A server stopped unexpectedly.")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
