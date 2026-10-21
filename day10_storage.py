"""Initialize V3, or upgrade idle Day9/Day10 V3 stores with paired backup.

Stop V3 writers first. This never opens or upgrades the original V2 databases.
Nonempty Day9 Graph checkpoints are deliberately refused by the migration.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from app.v3.storage import V3Paths, initialize_storage, migrate_day9_storage


def prepare(root,*,migrate=False,backup=None):
    paths=V3Paths(root);paths.validate()
    result={'root':str(paths.root),'action':'migrate_day9' if migrate else 'initialize'}
    if migrate:
        if backup is None:raise ValueError('Migration requires a new paired-backup directory')
        backup=Path(backup).resolve()
        backup.mkdir(parents=True,exist_ok=False)
        inventory=[]
        for path in (paths.learning,paths.checkpoints):
            target=backup/path.name
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(target) as destination:
                source.backup(destination)
            inventory.append({'original':str(path),'backup':str(target),
                'sha256':sha256(target.read_bytes()).hexdigest()})
        (backup/'manifest.json').write_text(json.dumps({'requires_idle_writers':True,'files':inventory},indent=2),encoding='utf8')
        migrate_day9_storage(paths)
        result['backup']=str(backup)
    else:initialize_storage(paths)
    for kind,path in (('business',paths.learning),('checkpoint',paths.checkpoints)):
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as conn:
            result[kind]=dict(conn.execute('SELECT key,value FROM runtime_metadata'))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=V3Paths().root)
    parser.add_argument('--migrate-day9',action='store_true')
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root,migrate=args.migrate_day9,backup=args.backup),ensure_ascii=False,indent=2))
