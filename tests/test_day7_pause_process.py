import json
import os
import subprocess
import sys
from pathlib import Path


def test_pause_survives_process_exit_and_extend_is_persisted_once(tmp_path):
    worker = Path(__file__).parent / "support" / "day7_pause_worker.py"
    def run(phase):
        result = subprocess.run([sys.executable, str(worker), phase, str(tmp_path)],
                                capture_output=True, text=True, encoding="utf-8", timeout=40,
                                env={**os.environ, "PYTHONUTF8": "1"})
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])
    first = run("begin")
    calls = (tmp_path / "calls.jsonl").read_text()
    assert first["next"] == ["pause"]
    assert first["state"]["rounds_by_node"] == {"node_0": 3}
    assert run("inspect")["state"] == first["state"]
    rested = run("rest")
    assert rested["next"] == ["pause"]
    assert rested["state"]["round_limit_by_node"]["node_0"] == 3
    assert (tmp_path / "calls.jsonl").read_text() == calls
    extended = run("extend")
    assert extended["next"] == ["wait_learning"]
    assert extended["state"]["rounds_by_node"] == {"node_0": 3}
    assert extended["state"]["round_limit_by_node"]["node_0"] == 6
    assert extended["state"]["round_limit_by_node"]["node_1"] == 3
    assert len(extended["state"]["credited_pause_input_ids"]) == 1
    assert run("inspect")["state"] == extended["state"]
