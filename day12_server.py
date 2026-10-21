"""Run the V3 browser product on initialized Day11 stores; V2 stays read only."""
import argparse
from pathlib import Path


if __name__=='__main__':
    import uvicorn
    from app.v3.learning_api import create_learning_app
    from app.v3.storage import V3Paths,PROJECT_ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=V3Paths().root)
    parser.add_argument('--port',type=int,default=8012)
    parser.add_argument('--legacy-business',type=Path,default=PROJECT_ROOT/'data'/'learning.sqlite')
    parser.add_argument('--legacy-checkpoints',type=Path,default=PROJECT_ROOT/'data'/'checkpoints.sqlite')
    args=parser.parse_args()
    uvicorn.run(create_learning_app(V3Paths(args.root),legacy_business_path=args.legacy_business,
                                   legacy_checkpoint_path=args.legacy_checkpoints),host='127.0.0.1',port=args.port)
