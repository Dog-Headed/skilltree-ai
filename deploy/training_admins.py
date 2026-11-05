"""Backend-only helpers for demo unit administrators.

Creates or grants admin role for registered accounts. Passwords are never CLI
arguments: generate randomly and write to a private file outside Git, or prompt.
Not exposed as a public HTTP privilege-escalation API.
"""
from __future__ import annotations

import argparse
import json
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

from .auth import AuthStore, normalize_login
from .training_demo import UNIT_ID
from .training_store import TrainingStore


QA_LOGINS = (
    'admin.qa1@example.test',
    'admin.qa2@example.test',
    'admin.qa3@example.test',
)


def strong_password(length=24):
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*-_=+'
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in value) and any(c.isupper() for c in value)
                and any(c.isdigit() for c in value) and any(c in '!@#$%^&*-_=+' for c in value)):
            return value


def ensure_unit(store, unit_id, unit_name):
    with store.connect() as conn:
        conn.execute('INSERT OR IGNORE INTO training_units VALUES (?,?)', (unit_id, unit_name))
        conn.execute('UPDATE training_units SET name=? WHERE id=?', (unit_name, unit_id))


def grant_admin(auth: AuthStore, store: TrainingStore, login: str, *, unit_id: str, unit_name: str,
                display_name: str, password: str | None, private_records: list):
    login = normalize_login(login)
    ensure_unit(store, unit_id, unit_name)
    with auth.connect() as conn:
        row = conn.execute('SELECT account, password_hash FROM auth_accounts WHERE login=?', (login,)).fetchone()
    created_account = False
    if row:
        account = row['account']
        # Never reset an existing password.
        password_action = 'reused_existing_password'
    else:
        if password is None:
            password = strong_password()
        account = auth.create_account(login, password)
        created_account = True
        password_action = 'generated_new_password'
        private_records.append({
            'login': login, 'account': account, 'password': password,
            'unit_id': unit_id, 'role': 'admin', 'created': True,
        })
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT unit_id, role, display_name FROM training_members WHERE account=?',
                                (account,)).fetchone()
        if existing and existing['unit_id'] != unit_id:
            raise SystemExit(f'{login} already belongs to another unit; refused to move.')
        if existing:
            if existing['role'] != 'admin':
                conn.execute('UPDATE training_members SET role=?, display_name=? WHERE account=?',
                             ('admin', display_name, account))
                membership = 'promoted_to_admin'
            else:
                membership = 'already_admin'
        else:
            conn.execute('INSERT INTO training_members(unit_id,account,display_name,role) VALUES (?,?,?,?)',
                         (unit_id, account, display_name, 'admin'))
            membership = 'joined_as_admin'
    return {
        'login': login, 'account': account, 'unit_id': unit_id,
        'created_account': created_account, 'password_action': password_action,
        'membership': membership,
    }


def write_private(path: Path, records: list, meta: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'generated_at': datetime.now(timezone.utc).astimezone().isoformat(),
        'warning': 'Private credentials. Do not commit, paste into chat, or put in README.',
        'meta': meta,
        'accounts': records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description='Grant/create training demo administrators (backend only)')
    parser.add_argument('--auth-db', type=Path, required=True)
    parser.add_argument('--training-db', type=Path, required=True)
    parser.add_argument('--unit-id', default=UNIT_ID)
    parser.add_argument('--unit-name', default='中国电信延安分公司')
    parser.add_argument('--private-out', type=Path, required=True,
                        help='JSON file outside Git for newly generated passwords')
    parser.add_argument('--qa-admins', action='store_true',
                        help=f'Ensure {", ".join(QA_LOGINS)} as admins of the unit')
    parser.add_argument('--login', action='append', default=[],
                        help='Additional login email to grant admin (repeatable)')
    parser.add_argument('--display-name', default='学习管理员')
    args = parser.parse_args()

    if not args.qa_admins and not args.login:
        parser.error('Specify --qa-admins and/or --login')

    auth, store = AuthStore(args.auth_db), TrainingStore(args.training_db)
    private_records = []
    results = []
    targets = []
    if args.qa_admins:
        for i, login in enumerate(QA_LOGINS, start=1):
            targets.append((login, f'QA管理员{i}'))
    for login in args.login:
        targets.append((login, args.display_name))

    for login, name in targets:
        results.append(grant_admin(
            auth, store, login, unit_id=args.unit_id, unit_name=args.unit_name,
            display_name=name, password=None, private_records=private_records))

    if private_records:
        write_private(args.private_out, private_records, {
            'auth_db': str(args.auth_db.resolve()),
            'training_db': str(args.training_db.resolve()),
            'unit_id': args.unit_id,
            'note': 'Only newly created accounts include passwords. Existing accounts were not reset.',
        })
        print(f'Wrote {len(private_records)} new password(s) to {args.private_out}')
    else:
        print('No new passwords generated (accounts already existed).')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
