"""Explicitly assign confirmed historical ownership after an offline backup."""
import argparse
from pathlib import Path
import re
import sqlite3

from .ownership import Ownership


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('assignments', nargs='+', help='project_id=account; never overwrites another owner')
    args = parser.parse_args()
    with sqlite3.connect((args.root.resolve() / 'learning.sqlite').as_uri() + '?mode=ro', uri=True) as conn:
        projects = {r[0] for r in conn.execute('SELECT id FROM learning_projects')}
    pairs = [value.split('=', 1) for value in args.assignments]
    if any(len(pair) != 2 or pair[0] not in projects or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', pair[1]) for pair in pairs):
        raise SystemExit('Unknown project or invalid account; no assignment made')
    registry = Ownership(args.registry)
    for project, account in pairs:
        if not registry.claim(project, account):
            raise SystemExit('Existing ownership conflicts; refusing replacement')
        print(f'Assigned {project} to {account}')
