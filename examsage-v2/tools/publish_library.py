"""Export a self-contained course library without overwriting an existing version."""
import argparse
import json
from pathlib import Path
import uuid

from examsage.cli import load
from examsage.course_pack import _publish_directory
from examsage.ingest import atomic_json
from examsage.release import inside, publish_release


def publish_library(data: Path, output: Path) -> dict:
    if output.exists():raise FileExistsError('Use a new library release directory')
    registry=json.loads((data/'library.json').read_text(encoding='utf-8'))
    stage=output.with_name(output.name+'.staging-'+uuid.uuid4().hex[:8])
    stage.mkdir(parents=True)
    reports={}
    for entry in registry['courses']:
        source=inside(data,entry['data'])
        store,scope=load(source)
        result=publish_release(store,scope,source/'assets',inside(stage,entry['data']),evaluation_dir=source/'evaluation')
        reports[entry['slug']]={k:v for k,v in result.items() if k!='files'}
        reports[entry['slug']]['hashed_files']=len(result['files'])
    atomic_json(stage/'library.json',registry)
    atomic_json(stage/'library-release.json',{'status':'candidate','human_acceptance':'pending','courses':reports})
    _publish_directory(stage,output)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path('data'))
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(publish_library(args.data,args.out),ensure_ascii=False,indent=2))
