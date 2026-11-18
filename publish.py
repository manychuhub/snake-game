"""Publish the SHIFT BRIDGE source files to their GitHub branch."""

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent
REPOSITORY = 'https://github.com/manychuhub/snake-game.git'
BRANCH = 'shift-bridge'
AUTHOR = ('user.name=manychuhub', 'user.email=265815235+manychuhub@users.noreply.github.com')
PATHS = (
    '.dockerignore', '.gitignore', '.github/workflows/aws-release.yml', 'Dockerfile',
    'README.md', 'Start.bat', 'Publish.bat', 'launch.py', 'publish.py',
    'Agent/README.md', 'Agent/app.py', 'Agent/alb_identity.py', 'Agent/database.py',
    'Agent/gemini_client.py', 'Agent/static/index.html', 'Agent/static/style.css',
    'Agent/static/app.js', 'Agent/tests/test_web.py',
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
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(directory), *args],
                          encoding='utf-8', errors='replace', **options)


def publish(files):
    with tempfile.TemporaryDirectory(prefix='shift-bridge-publish-') as temporary:
        worktree = Path(temporary).resolve()
        git(worktree, 'clone', '--quiet', '--depth', '1', '--single-branch', '--branch', BRANCH,
            REPOSITORY, '.', check=True)
        tracked = set(git(worktree, 'ls-files', '-z', check=True, capture_output=True).stdout.split('\0'))
        staged = []
        for name in PATHS:
            target = worktree / name
            if not target.resolve().is_relative_to(worktree):
                raise ValueError(f'Remote path is outside the checkout: {name}')
            if name in files:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(files[name], encoding='utf-8', newline='\n')
                staged.append(name)
            elif name in tracked:
                target.unlink(missing_ok=True)
                staged.append(name)
        if not staged:
            return
        git(worktree, 'add', '-A', '--', *staged, check=True)
        changed = git(worktree, 'diff', '--cached', '--quiet', '--').returncode
        if changed == 0:
            print('GitHub already has this version.', flush=True)
            return
        if changed != 1:
            raise RuntimeError('Could not inspect staged changes.')
        git(worktree, '-c', AUTHOR[0], '-c', AUTHOR[1], 'commit', '-qm', 'Update SHIFT BRIDGE', check=True)
        git(worktree, 'push', 'origin', f'HEAD:refs/heads/{BRANCH}', check=True)
        print(f'Published to {REPOSITORY.removesuffix(".git")}/tree/{BRANCH}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Upload once and exit.')
    options = parser.parse_args()
    if options.once:
        publish(source_files())
        return
    print('Watching SHIFT BRIDGE source files. Ctrl+C stops automatic uploads.', flush=True)
    last_seen = last_published = None
    while True:
        try:
            files = source_files()
            version = {name: hashlib.sha256(content.encode('utf-8')).digest() for name, content in files.items()}
            if version == last_seen and version != last_published:
                publish(files)
                last_published = version
            last_seen = version
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f'Publish paused: {error}', flush=True)
            time.sleep(20)
        time.sleep(5)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Publish failed: {error}') from None
