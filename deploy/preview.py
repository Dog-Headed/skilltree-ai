"""Real local cookie/ownership/queue preview, isolated from existing courses.

The five example.test identities exist only in this explicitly local preview.
Model operations use the configured Intern provider, never an auth mock.
"""
import os
from pathlib import Path
import sqlite3

from .asgi import EvaluationGateway
from .auth import AuthStore
from .provider import create_runtime_model
from app.v3.learning_api import create_learning_app
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage


def create_app():
    root = Path(os.getenv('SKILLTREE_PREVIEW_ROOT', 'work/beta-login-preview')).resolve()
    paths = initialize_learning_storage(initialize_storage(V3Paths(root/'learning')))
    auth = AuthStore(root/'auth.sqlite')
    for i in range(1, 6):
        try:
            auth.create_account(f'preview{i}@example.test', 'preview2026')
        except sqlite3.IntegrityError:
            pass  # Never reset an existing preview password.
    app = create_learning_app(paths, llm=create_runtime_model(),
        quiz_generation_mode=os.getenv('SKILLTREE_QUIZ_GENERATION', 'content-v1'),
        preparation_generation_mode=os.getenv('SKILLTREE_PREPARATION_GENERATION', 'notes-outline-v1'))
    return EvaluationGateway(app, paths, root/'quota.sqlite', auth_store=auth, queued=True,
                 origin='http://127.0.0.1:18230', cookie_secure=False)
