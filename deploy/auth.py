"""Email identities and revocable, opaque browser sessions.

Email is a username, never proof of mailbox ownership. Legacy logins keep their
canonical project owner, so importing passwords does not reassign any course.
"""
from contextlib import contextmanager
from hashlib import pbkdf2_hmac, sha256
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time


def normalize_login(value):
    if not isinstance(value, str):
        raise ValueError('Invalid login')
    value = value.strip().lower()
    legacy = re.fullmatch(r'[a-z0-9_-]{1,64}', value)
    email = re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9.-]{0,187}[a-z0-9])?\.[a-z]{2,63}", value)
    if len(value) > 254 or not (legacy or email):
        raise ValueError('Invalid login')
    return value


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return 'pbkdf2_sha256$600000$' + salt.hex() + '$' + digest.hex()


def verify_password(password, encoded):
    try:
        if encoded.startswith(('$2a$', '$2b$', '$2y$')):
            import bcrypt
            # Preserve htpasswd's historic 72-byte bcrypt semantics on import.
            return bcrypt.checkpw(password.encode()[:72], encoded.encode())
        algorithm, count, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 600000 <= int(count) <= 1000000:
            return False
        actual = pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(count))
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


def csrf_token(token):
    return sha256(('skilltree-csrf\0' + token).encode()).hexdigest()


class AuthStore:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS auth_accounts(
                login TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS auth_sessions(
                token_hash TEXT PRIMARY KEY, account TEXT NOT NULL,
                expires REAL NOT NULL, created REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS auth_session_account ON auth_sessions(account);
              CREATE TABLE IF NOT EXISTS auth_attempts(actor TEXT NOT NULL, at REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS auth_attempt_time ON auth_attempts(actor,at);
              CREATE TABLE IF NOT EXISTS auth_registrations(account TEXT PRIMARY KEY,ip_hash TEXT NOT NULL,created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS auth_register_attempts(ip_hash TEXT NOT NULL,at REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS auth_register_ip_time ON auth_register_attempts(ip_hash,at);
            ''')
        # Same KDF cost for nonexistent accounts; do not cache a plaintext secret.
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_account(self, login, password):
        login = normalize_login(login)
        if '@' not in login:
            raise ValueError('New accounts require an email username')
        if not isinstance(password, str) or not 10 <= len(password) <= 256:
            raise ValueError('Password must contain 10 to 256 characters')
        encoded = password_hash(password)
        with self.connect() as conn:
            conn.execute('INSERT INTO auth_accounts(login,account,password_hash) VALUES (?,?,?)', (login, login, encoded))
        return login

    def import_htpasswd(self, filename):
        entries = []
        for line in Path(filename).read_text().splitlines():
            if not line.strip():
                continue
            account, encoded = line.split(':', 1)
            login = normalize_login(account)
            if not encoded.startswith(('$2a$', '$2b$', '$2y$')):
                raise ValueError('Only bcrypt htpasswd entries are supported')
            entries.append((login, account, encoded))
        with self.connect() as conn:
            for entry in entries:
                existing = conn.execute('SELECT account FROM auth_accounts WHERE login=?', (entry[0],)).fetchone()
                if existing and existing['account'] != entry[1]:
                    raise ValueError('Identity collision; import stopped')
                conn.execute('INSERT OR IGNORE INTO auth_accounts(login,account,password_hash) VALUES (?,?,?)', entry)
        return len(entries)

    def bind_email(self, account, email):
        """Administrator-only alias change; preserve canonical owner and hash."""
        email = normalize_login(email)
        if '@' not in email:
            raise ValueError('Email username required')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM auth_accounts WHERE account=?', (account,)).fetchone():
                raise KeyError('Unknown canonical account')
            row = conn.execute('SELECT account FROM auth_accounts WHERE login=?', (email,)).fetchone()
            if row and row['account'] != account:
                raise ValueError('Email is already in use; no identity was merged')
            conn.execute('UPDATE auth_accounts SET login=? WHERE account=?', (email, account))
        return email

    def login_name(self, account):
        with self.connect() as conn:
            row = conn.execute('SELECT login FROM auth_accounts WHERE account=?', (account,)).fetchone()
        return row['login'] if row else account

    def register(self, login, password, ip, remember=False):
        try:
            login = normalize_login(login)
        except ValueError:
            return {'status': 422, 'code': 'invalid_input'}
        if '@' not in login or not isinstance(password, str) or not 10 <= len(password) <= 256:
            return {'status': 422, 'code': 'invalid_input'}
        at = time.time()
        ip_hash = sha256(ip.encode()).hexdigest()
        limit = max(0, int(os.getenv('SKILLTREE_REGISTRATION_LIMIT', '10')))
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM auth_register_attempts WHERE at<?', (at-3600,))
            attempts = conn.execute('SELECT at FROM auth_register_attempts WHERE ip_hash=? ORDER BY at', (ip_hash,)).fetchall()
            if len(attempts) >= 10:
                return {'status': 429, 'code': 'rate_limited', 'retry_after': max(1, int(attempts[0]['at']+3601-at))}
            conn.execute('INSERT INTO auth_register_attempts VALUES (?,?)', (ip_hash, at))
            if conn.execute('SELECT 1 FROM auth_accounts WHERE login=? OR account=?', (login, login)).fetchone():
                return {'status': 409, 'code': 'email_taken'}
            if conn.execute('SELECT COUNT(*) FROM auth_registrations r JOIN auth_accounts a ON a.account=r.account WHERE a.disabled=0').fetchone()[0] >= limit:
                return {'status': 403, 'code': 'registration_closed'}
        # Expensive hashing occurs outside the SQLite write transaction.
        encoded, token = password_hash(password), secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # Recheck after the KDF so parallel registrations cannot exceed capacity.
            if conn.execute('SELECT 1 FROM auth_accounts WHERE login=? OR account=?', (login, login)).fetchone():
                return {'status': 409, 'code': 'email_taken'}
            if conn.execute('SELECT COUNT(*) FROM auth_registrations r JOIN auth_accounts a ON a.account=r.account WHERE a.disabled=0').fetchone()[0] >= limit:
                return {'status': 403, 'code': 'registration_closed'}
            conn.execute('INSERT INTO auth_accounts(login,account,password_hash) VALUES (?,?,?)', (login, login, encoded))
            conn.execute('INSERT INTO auth_registrations VALUES (?,?,?)', (login, ip_hash, at))
            conn.execute('INSERT INTO auth_sessions VALUES (?,?,?,?)',
                         (sha256(token.encode()).hexdigest(), login, at+(2592000 if remember else 43200), at))
        return {'status': 201, 'account': login, 'token': token}

    def login(self, login, password, ip, remember=False):
        at = time.time()
        try:
            normalized = normalize_login(login)
        except ValueError:
            normalized = 'invalid'
        actors = ('account:' + sha256(normalized.encode()).hexdigest(), 'ip:' + sha256(ip.encode()).hexdigest())
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM auth_attempts WHERE at<?', (at-900,))
            for actor, limit in zip(actors, (8, 30)):
                rows = conn.execute('SELECT at FROM auth_attempts WHERE actor=? ORDER BY at', (actor,)).fetchall()
                if len(rows) >= limit:
                    return {'status': 429, 'retry_after': max(1, int(rows[0]['at'] + 901 - at))}
            conn.executemany('INSERT INTO auth_attempts VALUES (?,?)', [(actor, at) for actor in actors])
            row = conn.execute('SELECT * FROM auth_accounts WHERE login=?', (normalized,)).fetchone()
        valid_input = isinstance(password, str) and 0 < len(password) <= 256
        valid = verify_password(password if valid_input else '', row['password_hash'] if row else self.dummy_hash)
        if not row or row['disabled'] or not valid_input or not valid:
            return {'status': 401}
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute('DELETE FROM auth_attempts WHERE actor=?', (actors[0],))
            # Successful logins need not consume the shared-IP failure budget.
            conn.execute('DELETE FROM auth_attempts WHERE actor=? AND at=?', (actors[1], at))
            conn.execute('DELETE FROM auth_sessions WHERE expires<?', (at,))
            conn.execute('INSERT INTO auth_sessions VALUES (?,?,?,?)',
                         (sha256(token.encode()).hexdigest(), row['account'], at+(2592000 if remember else 43200), at))
        return {'status': 200, 'account': row['account'], 'token': token}

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.connect() as conn:
            row = conn.execute('''SELECT s.account FROM auth_sessions s JOIN auth_accounts a ON a.account=s.account
                 WHERE s.token_hash=? AND s.expires>? AND a.disabled=0''', (sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return row['account'] if row else None

    def logout(self, token):
        with self.connect() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE token_hash=?', (sha256(token.encode()).hexdigest(),))
