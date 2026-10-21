"""Run the V3 backend after explicit day11_storage.py initialization."""
import argparse
from pathlib import Path


if __name__=='__main__':
    import uvicorn
    from app.v3.storage import V3Paths
    from app.v3.learning_api import create_learning_app
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=V3Paths().root)
    parser.add_argument('--port',type=int,default=8011)
    args=parser.parse_args()
    uvicorn.run(create_learning_app(V3Paths(args.root)),host='127.0.0.1',port=args.port)
