"""Create new evaluation passwords without printing them or replacing accounts."""
import os
from pathlib import Path
import secrets
import subprocess


if __name__ == '__main__':
    destination = Path('/home/admin/skilltree-evaluation-access.txt')
    hashes = Path('/home/admin/skilltree-evaluators.htpasswd')
    if destination.exists() or hashes.exists():
        raise SystemExit('Existing credentials detected; refusing to replace them')
    os.umask(0o077)
    credentials = ['SkillTree V3 competition evaluation', 'URL pending public-access approval.',
                   'Shared evaluation workspace: all evaluators can see the same demo projects.',
                   'Do not upload personal or confidential material. Deletion is disabled.', '']
    entries = []
    for number in range(1, 4):
        name = f'judge{number:02d}'
        password = secrets.token_urlsafe(18)
        result = subprocess.run(['htpasswd', '-niB', name], input=password + '\n', text=True, capture_output=True, check=True)
        entries.append(result.stdout.strip())
        credentials.append(f'{name}: {password}')
    hashes.write_text('\n'.join(entries) + '\n')
    destination.write_text('\n'.join(credentials) + '\n')
    print('Created three evaluation accounts; passwords saved privately on the server.')
