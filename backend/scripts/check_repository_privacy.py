"""Check tracked source for private paths, credentials and generated state.

Findings show only a path/line/category, never the matched value. --history
checks reachable blobs and commit identities in a full local clone as well.
"""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_PATH = re.compile(r'(?:/Users/|/home/|[A-Z]:\\Users\\)([A-Za-z0-9._-]+)')
PUBLIC_PATH_NAMES = {'USER', 'user', 'runner', 'example', 'REDACTED', 'YOUR_USERNAME'}
EMAIL = re.compile(r'[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})')
PUBLIC_MAIL_DOMAINS = {'users.noreply.github.com', 'github.com', 'example.com', 'example.org', 'example.invalid'}
CREDENTIAL = re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
GENERATED = ('.agents/', '.omc/', '.omx/', '.claude/', '.playwright-mcp/', 'docs/_session/', 'backend/scratch/', 'backend/runtime/', 'backend/venv/', 'backend/.venv/', 'frontend/node_modules/', 'frontend/dist/')
PRIVATE_SUFFIXES = ('.db', '.db-wal', '.db-shm', '.log', '.parquet', '.joblib', '.bundle', '.pyc')


def scan_text(text):
    findings = []
    for line, content in enumerate(text.splitlines(), 1):
        if any(m.group(1) not in PUBLIC_PATH_NAMES for m in PRIVATE_PATH.finditer(content)):
            findings.append((line, 'personal-path'))
        if any(m.group(1) not in PUBLIC_MAIL_DOMAINS for m in EMAIL.finditer(content)):
            findings.append((line, 'personal-email'))
        if CREDENTIAL.search(content):
            findings.append((line, 'credential'))
    return findings


def tracked_findings(root):
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    findings = []
    for name in filter(None, paths):
        if name.startswith(GENERATED) or name.endswith(PRIVATE_SUFFIXES) or (Path(name).name.startswith('.env') and name != 'backend/.env.example'):
            findings.append((name, 0, 'private-or-generated-file'))
        try:
            text = (root / name).read_text()
        except (UnicodeError, FileNotFoundError):
            continue
        findings.extend((name, line, category) for line, category in scan_text(text))
    return findings


def history_findings(root):
    objects = {}
    for row in subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=root, text=True).splitlines():
        parts = row.split(' ', 1)
        if len(parts) == 2:
            objects[parts[0]] = parts[1]
    findings = []
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha, name in objects.items():
            process.stdin.write((sha + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3:
                continue
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            if header[1] != 'blob':
                continue
            if name.startswith(GENERATED):
                findings.append((name, 0, 'historical-session-file'))
            try:
                text = data.decode()
            except UnicodeError:
                continue
            findings.extend((name, line, category) for line, category in scan_text(text))
    finally:
        process.stdin.close()
        process.wait()
    identities = subprocess.check_output(['git', 'log', '--all', '--format=%ae%n%ce'], cwd=root, text=True)
    if any(not line.endswith('@users.noreply.github.com') and line not in {'noreply@github.com', 'web-flow@github.com'} for line in identities.splitlines()):
        findings.append(('<git-identities>', 0, 'non-public-identity'))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    findings = tracked_findings(ROOT)
    if args.history:
        findings.extend(history_findings(ROOT))
    for path, line, category in sorted(set(findings)):
        print(f'{path}:{line}: {category}')
    if findings:
        raise SystemExit(1)
    print('Privacy check passed: no detected private paths, credentials or generated state.')


if __name__ == '__main__':
    main()
