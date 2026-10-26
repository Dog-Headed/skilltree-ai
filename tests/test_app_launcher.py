"""The user's normal app.py entry must serve V3 without opening a V2 runtime."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from tests.day11_support import build_frozen_project


def launcher():
    path=Path(__file__).resolve().parents[1]/'app.py'
    spec=importlib.util.spec_from_file_location('skilltree_desktop_launcher',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_default_launcher_serves_v3_routes_and_assets_without_database_writes(tmp_path,monkeypatch):
    from app.v3 import learning_api
    frozen=build_frozen_project(tmp_path/'v3',node_count=1)
    factory=learning_api.create_learning_app
    make=Mock(side_effect=lambda:factory(frozen['paths'],llm=frozen['model'],
        legacy_business_path=tmp_path/'no-legacy.sqlite',legacy_checkpoint_path=tmp_path/'no-old-checkpoints.sqlite'))
    monkeypatch.setattr(learning_api,'create_learning_app',make)
    module=launcher()
    paths=[frozen['paths'].learning,frozen['paths'].checkpoints,frozen['paths'].root/'learning-checkpoints.sqlite']
    before={p:p.read_bytes() for p in paths};calls=len(frozen['model'].calls)
    client=TestClient(module.load_application())
    page=client.get('/')
    assert page.status_code==200 and '/assets/v3.js' in page.text and 'V2 历史' not in page.text
    assert 'legacy-tab' not in page.text and '学习记录' in page.text
    assert client.get('/capabilities').status_code==200
    assert client.get('/projects/'+frozen['project_id']).json()['version']=='v3'
    assert client.get('/legacy/projects').json()==[]
    make.assert_called_once_with()
    assert module.PORT==8765 and len(frozen['model'].calls)==calls
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert not (tmp_path/'no-legacy.sqlite').exists()


def test_main_passes_v3_application_to_server_and_keeps_ready_browser_behavior(monkeypatch,capsys):
    import uvicorn
    module=launcher();product=object();config=object();server=SimpleNamespace(run=Mock())
    load=Mock(return_value=product);make_config=Mock(return_value=config);make_server=Mock(return_value=server)
    thread=Mock();make_thread=Mock(return_value=thread)
    monkeypatch.setattr(module,'load_application',load)
    monkeypatch.setattr(uvicorn,'Config',make_config);monkeypatch.setattr(uvicorn,'Server',make_server)
    monkeypatch.setattr(module.threading,'Thread',make_thread)
    module.main()
    load.assert_called_once_with()
    make_config.assert_called_once_with(product,host='127.0.0.1',port=8765,workers=1)
    make_server.assert_called_once_with(config)
    assert make_thread.call_args.kwargs['target'] is module.open_browser_when_ready
    assert make_thread.call_args.kwargs['args']==(server,)
    thread.start.assert_called_once_with();server.run.assert_called_once_with()
    assert 'SkillTree V3' in capsys.readouterr().out


def test_incompatible_v3_store_stops_without_falling_back_to_old_server(monkeypatch,capsys):
    import uvicorn
    module=launcher();make_server=Mock()
    monkeypatch.setattr(module,'load_application',Mock(side_effect=ValueError('PRIVATE_INTERNAL_PATH')))
    monkeypatch.setattr(uvicorn,'Server',make_server)
    with pytest.raises(SystemExit,match='1'):module.main()
    error=capsys.readouterr().err
    assert 'V3' in error and 'PRIVATE_INTERNAL_PATH' not in error
    make_server.assert_not_called()
