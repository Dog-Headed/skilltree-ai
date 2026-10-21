"""Day 12 hard-exit probe. Only a caller-supplied isolated test store is opened."""

import json
import os
from pathlib import Path
import sys

from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from app.v3.storage import V3Paths
from tests.day11_support import FakeLearningModel


def logged_model(log_path):
    model = FakeLearningModel()
    invoke = model._invoke

    def tracked(schema, messages):
        # Fsync the external observation before returning to the model adapter;
        # os._exit intentionally bypasses Python cleanup and exception handlers.
        with Path(log_path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"schema": schema, "process": os.getpid()}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return invoke(schema, messages)

    model._invoke = tracked
    return model


def main():
    root, project_id, hook, command_path, call_log = sys.argv[1:]
    paths = V3Paths(Path(root))
    # A positive opt-in marker prevents accidentally pointing the worker at a
    # live database, even if its command line is copied out of the test harness.
    if not (paths.root / "day12-isolated-test-store").is_file():
        raise ValueError("Hard-exit worker requires an explicitly isolated store")
    command = json.loads(Path(command_path).read_text(encoding="utf-8"))
    model = logged_model(call_log)
    if hook == "budget_child_saved":
        original = LearningRepository.create_operation

        def saved(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if kwargs.get("parent_operation_id"):
                os._exit(72)
            return result

        LearningRepository.create_operation = saved
    else:
        name = {"quiz_saved": "save_quiz", "evaluation_saved": "save_evaluation",
                "diagnosis_saved": "save_diagnosis", "completion_saved": "apply_transition"}[hook]
        original = getattr(LearningRepository, name)

        def saved(self, *args, **kwargs):
            original(self, *args, **kwargs)
            os._exit(72)

        setattr(LearningRepository, name, saved)
    service = LearningService(paths, llm=model)
    if command.get("kind") == "retry":
        service.retry(project_id, retry_token=command["retry_token"], request_id=command["request_id"],
                      continue_budget=command.get("continue_budget", False))
    else:
        service.resume(project_id, command)
    raise AssertionError("Expected an uncatchable process exit")


if __name__ == "__main__":
    main()
