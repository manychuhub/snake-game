"""Publish the SHIFT BRIDGE source files to their GitHub branch."""

import argparse
import hashlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
REPOSITORY = 'https://github.com/manychuhub/snake-game.git'
BRANCH = 'shift-bridge'
AUTHOR = ('user.name=manychuhub', 'user.email=265815235+manychuhub@users.noreply.github.com')
TASK_NAME = 'SHIFT BRIDGE GitHub Publish'
LOG = logging.getLogger('shift-bridge-publish')
PATHS = (
    '.dockerignore', '.gitignore', '.github/workflows/aws-release.yml', 'Dockerfile',
    'AGENTS.md', 'README.md', 'Start.bat', 'Publish.bat', 'launch.py', 'publish.py',
    'Agent/README.md', 'Agent/app.py', 'Agent/alb_identity.py', 'Agent/database.py',
    'Agent/gemini_client.py', 'Agent/demo.py', 'Agent/static/index.html', 'Agent/static/style.css',
    'Agent/static/app.js', 'Agent/static/about.html', 'Agent/static/about.css', 'Agent/static/about.js',
    'Agent/accounts.py', 'Agent/static/account.html', 'Agent/static/account.css',
    'Agent/static/account.js', 'Agent/static/admin.html', 'Agent/static/admin.js',
    'Agent/static/preferences.html', 'Agent/static/preferences.js',
    'Agent/tests/test_web.py',
    'BridgeCLI/.env.example', 'BridgeCLI/README.md', 'BridgeCLI/api_server.py',
    'BridgeCLI/bridge_cli.py', 'BridgeCLI/config.py', 'BridgeCLI/gemini_api.py',
    'BridgeCLI/memory.py', 'BridgeCLI/shift_bridge_client.py', 'BridgeCLI/requirements.txt',
    'BridgeCLI/bridge.bat', 'BridgeCLI/start.bat', 'BridgeCLI/stop.bat',
    'BridgeCLI/test.bat', 'BridgeCLI/tests/test_bridge.py',
    'deploy/README.md', 'deploy/RENDER.md', 'deploy/aws.yml', 'deploy/run.py',
    'test/README.md', 'test/app.py', 'test/alb_identity.py', 'test/database.py',
    'test/gemini_client.py', 'test/static/index.html', 'test/static/style.css', 'test/static/app.js',
)
SECRET_NAMES = {'GEMINI_API_KEY', 'HYBRID_API_AUTH_TOKEN'}
CREDENTIAL = re.compile(r'AIza[A-Za-z0-9_-]{35}|gh[pousr]_[A-Za-z0-9]{30,}'
                        r'|github_pat_[A-Za-z0-9_]{30,}|(?:AKIA|ASIA)[A-Z0-9]{16}'
                        r'|-----BEGIN [A-Z ]*PRIVATE KEY-----')


def source_files():
    settings = ROOT / 'BridgeCLI/.env'
    protected = []
    if settings.is_file():
        for line in settings.read_text(encoding='utf-8-sig').splitlines():
            name, _, value = line.partition('=')
            if name.strip().removeprefix('export ') in SECRET_NAMES:
                secret = value.strip().strip('"\'')
                if len(secret) >= 12:
                    protected.append(secret)
    files = {}
    for name in PATHS:
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError(f'Source path is outside the project: {name}')
        if not path.is_file():
            continue
        content = path.read_text(encoding='utf-8')
        if CREDENTIAL.search(content) or any(secret in content for secret in protected):
            raise ValueError(f'Possible credential in {name}. Remove it before publishing.')
        files[name] = content
    return files


def git(directory, *args, **options):
    command = ['git', '-c', 'core.autocrlf=false', '-C', str(directory), *args]
    if LOG.handlers:
        checked = options.pop('check', False)
        result = subprocess.run(command, encoding='utf-8', errors='replace', capture_output=True,
                                timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'},
                                **options)
        if checked and result.returncode:
            detail = CREDENTIAL.sub('[redacted]', result.stderr.strip())
            raise RuntimeError(f'git {args[0]} failed ({result.returncode}): {detail}')
        return result
    return subprocess.run(command, encoding='utf-8', errors='replace', **options)


def report(message):
    if LOG.handlers:
        LOG.info(message)
    else:
        print(message, flush=True)


def publish(files):
    with tempfile.TemporaryDirectory(prefix='shift-bridge-publish-') as temporary:
        worktree = Path(temporary).resolve()
        git(worktree, 'clone', '--quiet', '--depth', '1', '--single-branch', '--branch', BRANCH,
            REPOSITORY, '.', check=True)
        for name, content in files.items():
            target = worktree / name
            if not target.resolve().is_relative_to(worktree):
                raise ValueError(f'Remote path is outside the checkout: {name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8', newline='\n')
        if not files:
            return
        git(worktree, 'add', '--', *files, check=True)
        changed = git(worktree, 'diff', '--cached', '--quiet', '--').returncode
        if changed == 0:
            report('GitHub already has this version.')
            return
        if changed != 1:
            raise RuntimeError('Could not inspect staged changes.')
        git(worktree, '-c', AUTHOR[0], '-c', AUTHOR[1], 'commit', '-qm', 'Update SHIFT BRIDGE', check=True)
        git(worktree, 'push', 'origin', f'HEAD:refs/heads/{BRANCH}', check=True)
        report(f'Published to {REPOSITORY.removesuffix(".git")}/tree/{BRANCH}')


def install():
    if os.name != 'nt':
        raise RuntimeError('Install the login task from Windows using Publish.bat --install.')
    publish(source_files())
    interpreter = Path(sys.executable)
    gui_interpreter = interpreter.with_name('pythonw.exe')
    environment = {
        **os.environ, 'SHIFT_PUBLISH_PYTHON': str(gui_interpreter if gui_interpreter.is_file() else interpreter),
        'SHIFT_PUBLISH_SCRIPT': str(Path(__file__).resolve()), 'SHIFT_PUBLISH_ROOT': str(ROOT),
        'SHIFT_PUBLISH_TASK': TASK_NAME,
    }
    script = r"""
        $ErrorActionPreference = 'Stop'
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $action = New-ScheduledTaskAction -Execute $env:SHIFT_PUBLISH_PYTHON `
            -Argument ('"{0}" --background' -f $env:SHIFT_PUBLISH_SCRIPT) -WorkingDirectory $env:SHIFT_PUBLISH_ROOT
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        $existing = Get-ScheduledTask -TaskName $env:SHIFT_PUBLISH_TASK -ErrorAction SilentlyContinue
        if ($existing -and $existing.State -eq 'Running') {
            Stop-ScheduledTask -InputObject $existing
        }
        Register-ScheduledTask -TaskName $env:SHIFT_PUBLISH_TASK -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $env:SHIFT_PUBLISH_TASK
    """
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                   env=environment, check=True)
    report(f'Started Windows scheduled task "{TASK_NAME}". Log: {ROOT / "publish.log"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true', help='Upload once and exit.')
    mode.add_argument('--install', action='store_true', help='Upload and start the Windows login task.')
    mode.add_argument('--background', action='store_true', help='Watch and write status to publish.log.')
    options = parser.parse_args()
    if options.once:
        publish(source_files())
        return
    if options.install:
        install()
        return
    if options.background:
        handler = RotatingFileHandler(ROOT / 'publish.log', maxBytes=262144, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)
    report('Watching SHIFT BRIDGE source files.')
    last_seen = last_published = None
    while True:
        try:
            files = source_files()
            version = {name: hashlib.sha256(content.encode('utf-8')).digest() for name, content in files.items()}
            if version == last_seen and version != last_published:
                changes = files if last_published is None else {
                    name: content for name, content in files.items() if version[name] != last_published.get(name)
                }
                if changes:
                    publish(changes)
                last_published = version
            last_seen = version
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            report(f'Publish paused: {error}')
            time.sleep(20)
        time.sleep(5)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Publish failed: {error}') from None
