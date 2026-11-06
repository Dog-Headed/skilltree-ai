"""The garden shell links unit admins to the training hub and hides that link from everyone else."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_garden_topbar_training_admin_link_follows_session_role():
    node = os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('node is required to execute the garden shell')
    result = subprocess.run(
        [node, str(Path(__file__).parent / 'support' / 'garden_admin_nav.cjs'), str(ROOT / 'app' / 'static' / 'v3.js')],
        capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    admin = report['admin']
    assert [(link['href'], link['text']) for link in admin['links']] == [('/', '学习首页'), ('/training/admin', '学习管理')]
    assert all(link['hidden'] is False for link in admin['links'])
    assert admin['brand'] == '自由学习 · 学习管理员'
    assert admin['pageTitle'] == '我的花园'
    # The legacy admin display name is not enough. Only role admin gets the hub link.
    assert report['employee']['brand'] == '自由学习 · 学习管理员'
    for role in ('employee', 'personal', 'guest'):
        links = report[role]['links']
        assert [link['href'] for link in links if link['href'] == '/'] == ['/'], role
        assert [link for link in links if link['href'] == '/training/admin' or link['text'] == '学习管理'] == [], role
        assert report[role]['pageTitle'] == '我的花园'
    # A session without a training membership keeps the garden tools unchanged.
    assert report['none']['links'] == []
    assert report['none']['pageTitle'] == '我的花园'
