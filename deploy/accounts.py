"""Private administrator CLI. Passwords are prompted, never command arguments."""
import argparse
from getpass import getpass
from .auth import AuthStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='data/auth.sqlite')
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('create')
    create.add_argument('email')
    imported = sub.add_parser('import-htpasswd')
    imported.add_argument('path')
    args = parser.parse_args()
    store = AuthStore(args.database)
    if args.action == 'create':
        password = getpass('Password (10+ characters): ')
        if password != getpass('Repeat password: '):
            raise SystemExit('Passwords do not match; nothing changed')
        store.create_account(args.email, password)
        print('Account created; existing accounts were not replaced.')
    else:
        count = store.import_htpasswd(args.path)
        print(f'Imported {count} legacy identities without replacing existing accounts.')


if __name__ == '__main__':
    main()
