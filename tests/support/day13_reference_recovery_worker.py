"""Hard process death after normal private-reference confirmation writes."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
from fastapi.testclient import TestClient
from app.v3 import planner
from app.v3.preparation import PreparationService
from app.v3.preparation_api import create_preparation_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths, initialize_storage
from tests.test_v3_preparation import Model, create, upload, resume


def main(directory, mode):
    paths = initialize_storage(V3Paths(directory))
    with patch.object(planner, 'get_llm', lambda: Model()):
        client = TestClient(create_preparation_app(paths))
        p = upload(client, create(client))
        p = upload(client, p, source_id='private', title='SECRET-TITLE',
                   content='# 评价参考\nSECRET-BODY：变量保存值。', visibility='assessment_private')
        p = resume(client, p, 'confirm_profile').json()
        body = {'request_id': str(uuid4()), 'action': 'confirm_plan',
                'pending_input_id': p['pending_input_id'], 'draft_revision': p['draft_revision'],
                'private_references': [{'reference_id': p['private_references'][0]['reference_id'],
                                        'action': 'bind', 'node_ids': ['same-node']}]}
        (directory / 'reference-command.json').write_text(json.dumps({'view': p, 'body': body}), encoding='utf8')
        if mode == 'business_commit':
            original = V3Repository.freeze_plan
            def die_after_write(self, *args, **kwargs):
                original(self, *args, **kwargs)
                os._exit(73)
            with patch.object(V3Repository, 'freeze_plan', die_after_write):
                client.post('/projects/' + p['project_id'] + '/resume', json=body)
        else:
            with patch.object(PreparationService, '_finish_execution', lambda *args: os._exit(73)):
                client.post('/projects/' + p['project_id'] + '/resume', json=body)


if __name__ == '__main__':
    main(Path(sys.argv[1]), sys.argv[2])
