"""Independent real-browser checks for explicit private-reference choices.

These tests launch the shipped page against an isolated Fake-backed API/Graph.
They establish interaction, privacy and persistence evidence, not content quality.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.v3.context import ContextBuilder
from app.v3.learning_repository import LearningRepository
from app.v3.storage import V3Paths
from test_day12_frontend import frontend_server


@pytest.mark.parametrize('scenario', [
    'desktop-bind', 'mobile-refresh-bind', 'explicit-exclude',
    'missing-choice', 'stale-and-duplicate', 'safe-text',
])
def test_private_reference_browser_flow(frontend_server, tmp_path, scenario):
    root, url = frontend_server
    node = os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node and Playwright are required for the real browser checks')
    env = os.environ.copy()
    bundled = Path(node).resolve().parent.parent / 'node_modules'
    env['NODE_PATH'] = os.pathsep.join(filter(None, [str(bundled), env.get('NODE_PATH', '')]))
    probe = subprocess.run([node, '-e', "require.resolve('playwright')"], env=env,
                           capture_output=True, text=True, encoding='utf-8')
    if probe.returncode:
        pytest.skip('Playwright is required for the real browser checks')
    if os.name == 'nt':
        env.setdefault('SKILLTREE_TEST_BROWSER_CHANNEL', 'msedge')
    evidence = Path(env.get('DAY13_PRIVATE_REFERENCE_EVIDENCE_DIR', tmp_path)) / scenario
    evidence.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([node, str(Path(__file__).parent / 'support' / 'day13_private_reference_frontend.cjs'),
                             url, scenario, str(evidence.resolve())], env=env, capture_output=True,
                            text=True, encoding='utf-8', timeout=150)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    report = json.loads((evidence / 'result.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['scenario'] == scenario
    with LearningRepository(V3Paths(root)) as repo:
        project = repo.get_project(report['project_id'])
        assert project['frozen_snapshot']
        private_sources = [s for s in repo.list_sources(report['project_id'], include_private=True)
                           if s['visibility'] == 'assessment_private']
        assert len(private_sources) == 1
        source = private_sources[0]
        refs = {r['source_id'] for r in project['frozen_snapshot']['source_manifest']}
        chunks = repo.list_source_chunks(report['project_id'], source['source_id'], source['source_version'], include_private=True)
        links = [dict(row) for row in repo.conn.execute(
            'SELECT node_id,objective_id,chunk_id,purpose FROM node_material_links WHERE project_id=?',
            (report['project_id'],)) if row['chunk_id'] in {c['chunk_id'] for c in chunks}]
        if report['decision'] == 'exclude':
            assert source['source_id'] not in refs and not links
        else:
            assert source['source_id'] in refs
            assert {row['node_id'] for row in links} == {'node_1'}
            assert {row['purpose'] for row in links} == {'assessment', 'grading'}
            builder = ContextBuilder(repo)
            objective = project['candidate_plan']['nodes'][0]['objectives'][0]['objective_id']
            assert report['private_marker'] in builder.for_assessment(report['project_id'], 'node_1', objective).payload
            assert report['private_marker'] in builder.for_grading(report['project_id'], 'node_1', objective).payload
            assert report['private_marker'] not in builder.for_teaching(report['project_id'], 'node_1', objective).payload
        facts = {'project_id': report['project_id'], 'lifecycle': project['lifecycle'],
                 'private_source_count': len(private_sources), 'private_chunk_count': len(chunks),
                 'private_link_count': len(links), 'private_link_purposes': sorted({r['purpose'] for r in links}),
                 'frozen_included_private_reference': source['source_id'] in refs,
                 'preparation_command_count': repo.conn.execute(
                     'SELECT COUNT(*) FROM preparation_inputs WHERE project_id=?', (report['project_id'],)).fetchone()[0],
                 'model_request_count': repo.conn.execute(
                     'SELECT COALESCE(SUM(reserved_requests),0) FROM model_operations WHERE project_id=?',
                     (report['project_id'],)).fetchone()[0]}
    (evidence / 'database-facts.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding='utf-8')
