"""Explicit additive Day11 migration. Stop writers; existing stores require backup."""
import argparse
from contextlib import ExitStack
from pathlib import Path
import json
import sqlite3
from hashlib import sha256

from app.v3.storage import V3Paths, initialize_storage
from app.v3.repository import V3Repository
from app.v3.execution import project_execution
from app.v3.runtime_storage import initialize_learning_storage, learning_checkpoint_path


def prepare(root, *, backup=None):
    paths=V3Paths(root);paths.validate()
    if not paths.learning.exists(): initialize_storage(paths)
    elif backup is None: raise ValueError('Existing stores require a new paired backup directory')
    with ExitStack() as stack:
        with V3Repository(paths) as repo: projects=repo.list_projects()
        for project in sorted(projects,key=lambda p:p['id']): stack.enter_context(project_execution(project['id'],paths))
        if backup is not None:
            target=Path(backup).resolve();target.mkdir(parents=True,exist_ok=False)
            files=[]
            for source in (paths.learning,paths.checkpoints,learning_checkpoint_path(paths)):
                if not source.exists():continue
                destination=target/source.name
                with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(destination) as dst: src.backup(dst)
                files.append({'source':str(source),'backup':str(destination),'sha256':sha256(destination.read_bytes()).hexdigest()})
            (target/'manifest.json').write_text(json.dumps({'requires_idle_writers':True,'files':files},indent=2),encoding='utf-8')
        initialize_learning_storage(paths)
    return {'root':str(paths.root),'backup':str(Path(backup).resolve()) if backup else None,
            'learning_checkpoint':str(learning_checkpoint_path(paths)),
            'project_ids':[p['id'] for p in projects],'migration':'v3-day11-1','graph_version':'v3-day11-learning'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=V3Paths().root)
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root,backup=args.backup),ensure_ascii=False,indent=2))
