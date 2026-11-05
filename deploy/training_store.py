"""Training unit foundations. Shared course content, separate learner runs.

Day 3 publication/assignment APIs are still closed. 4A adds member selection.
Account IDs refer to the canonical IDs in the isolated AuthStore.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = '''
CREATE TABLE IF NOT EXISTS training_units(
 id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training_members(
 unit_id TEXT NOT NULL REFERENCES training_units(id), account TEXT NOT NULL,
 display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','employee')),
 PRIMARY KEY(unit_id,account), UNIQUE(account));
CREATE TABLE IF NOT EXISTS training_material_versions(
 id TEXT PRIMARY KEY, unit_id TEXT NOT NULL, owner_account TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('unit','private')),
 version INTEGER NOT NULL CHECK(version>=1), title TEXT NOT NULL,
 original_path TEXT NOT NULL, parsed_path TEXT NOT NULL, locations_json TEXT NOT NULL CHECK(json_valid(locations_json)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(unit_id,id),
 FOREIGN KEY(unit_id,owner_account) REFERENCES training_members(unit_id,account));
CREATE TABLE IF NOT EXISTS training_course_versions(
 id TEXT PRIMARY KEY, unit_id TEXT NOT NULL REFERENCES training_units(id),
 course_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>=1), title TEXT NOT NULL,
 tree_json TEXT NOT NULL CHECK(json_valid(tree_json)),
 required_nodes_json TEXT NOT NULL CHECK(json_valid(required_nodes_json)),
 pass_rule_json TEXT NOT NULL CHECK(json_valid(pass_rule_json)),
 published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(unit_id,id), UNIQUE(unit_id,course_id,version));
CREATE TABLE IF NOT EXISTS training_course_materials(
 unit_id TEXT NOT NULL, course_version_id TEXT NOT NULL, material_version_id TEXT NOT NULL,
 PRIMARY KEY(course_version_id,material_version_id),
 FOREIGN KEY(unit_id,course_version_id) REFERENCES training_course_versions(unit_id,id),
 FOREIGN KEY(unit_id,material_version_id) REFERENCES training_material_versions(unit_id,id));
CREATE TABLE IF NOT EXISTS training_tasks(
 id TEXT PRIMARY KEY, unit_id TEXT NOT NULL, course_version_id TEXT NOT NULL,
 title TEXT NOT NULL, due_at TEXT, created_by TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(unit_id,id),
 FOREIGN KEY(unit_id,course_version_id) REFERENCES training_course_versions(unit_id,id),
 FOREIGN KEY(unit_id,created_by) REFERENCES training_members(unit_id,account));
CREATE TABLE IF NOT EXISTS training_employee_tasks(
 id TEXT PRIMARY KEY, unit_id TEXT NOT NULL, task_id TEXT NOT NULL, account TEXT NOT NULL,
 project_id TEXT UNIQUE, started_at TEXT,
 UNIQUE(task_id,account), UNIQUE(id,project_id),
 FOREIGN KEY(unit_id,task_id) REFERENCES training_tasks(unit_id,id),
 FOREIGN KEY(unit_id,account) REFERENCES training_members(unit_id,account));
CREATE TABLE IF NOT EXISTS training_node_bindings(
 employee_task_id TEXT NOT NULL, project_id TEXT NOT NULL,
 course_node_id TEXT NOT NULL, project_node_id TEXT NOT NULL,
 PRIMARY KEY(employee_task_id,course_node_id), UNIQUE(project_id,project_node_id),
 FOREIGN KEY(employee_task_id,project_id) REFERENCES training_employee_tasks(id,project_id));
CREATE TRIGGER IF NOT EXISTS training_frozen_course_update BEFORE UPDATE ON training_course_versions
 BEGIN SELECT RAISE(ABORT,'Published course versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS training_frozen_course_delete BEFORE DELETE ON training_course_versions
 BEGIN SELECT RAISE(ABORT,'Published course versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS training_frozen_material_update BEFORE UPDATE ON training_material_versions
 BEGIN SELECT RAISE(ABORT,'Material versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS training_frozen_material_delete BEFORE DELETE ON training_material_versions
 BEGIN SELECT RAISE(ABORT,'Material versions are immutable'); END;
'''


class TrainingStore:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def member(self, account):
        with self.connect() as conn:
            row = conn.execute('''SELECT m.*,u.name AS unit_name FROM training_members m
                JOIN training_units u ON u.id=m.unit_id WHERE account=?''', (account,)).fetchone()
            return dict(row) if row else None

    def overview(self, unit_id):
        with self.connect() as conn:
            members = [dict(row) for row in conn.execute(
                'SELECT account,display_name,role FROM training_members WHERE unit_id=? ORDER BY role,account', (unit_id,))]
            courses = [dict(row) for row in conn.execute(
                'SELECT id,title,version,published_at FROM training_course_versions WHERE unit_id=?', (unit_id,))]
            tasks = [dict(row) for row in conn.execute(
                'SELECT id,title,course_version_id,due_at FROM training_tasks WHERE unit_id=?', (unit_id,))]
        return {'members': members, 'courses': courses, 'tasks': tasks, 'publishing_available': False}

    def my_tasks(self, unit_id, account):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('''SELECT e.id,e.task_id,e.project_id,t.title,t.due_at,
                t.course_version_id FROM training_employee_tasks e JOIN training_tasks t ON t.id=e.task_id
                WHERE e.unit_id=? AND e.account=?''', (unit_id, account))]


    def add_employee(self, unit_id, account, display_name):
        """Add a registered personal account as an employee of this unit.

        Idempotent when already in this unit. Rejects accounts already in another
        unit. Never grants admin through this path.
        """
        if not isinstance(display_name, str) or not display_name.strip() or len(display_name.strip()) > 64:
            raise ValueError('invalid_display_name')
        name = display_name.strip()
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM training_units WHERE id=?', (unit_id,)).fetchone():
                raise KeyError('unknown_unit')
            existing = conn.execute(
                'SELECT unit_id, role, display_name FROM training_members WHERE account=?',
                (account,)).fetchone()
            if existing:
                if existing['unit_id'] != unit_id:
                    raise ValueError('other_unit')
                return {
                    'unit_id': existing['unit_id'], 'account': account,
                    'display_name': existing['display_name'], 'role': existing['role'],
                    'created': False,
                }
            conn.execute(
                'INSERT INTO training_members(unit_id,account,display_name,role) VALUES (?,?,?,?)',
                (unit_id, account, name, 'employee'))
            return {
                'unit_id': unit_id, 'account': account, 'display_name': name,
                'role': 'employee', 'created': True,
            }

    def remove_employee(self, unit_id, account):
        """Revoke unit membership only; never deletes personal learning data."""
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                'SELECT role FROM training_members WHERE unit_id=? AND account=?',
                (unit_id, account)).fetchone()
            if not row:
                return {'removed': False, 'account': account}
            if row['role'] == 'admin':
                raise ValueError('cannot_remove_admin')
            conn.execute(
                'DELETE FROM training_members WHERE unit_id=? AND account=?',
                (unit_id, account))
            return {'removed': True, 'account': account}

