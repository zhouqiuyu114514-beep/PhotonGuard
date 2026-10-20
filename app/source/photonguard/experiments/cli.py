"""Explicit bounded rerun entrypoint for exported, fixed optical plans."""
import argparse
import json
from pathlib import Path
from .executor import execute_plan

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['run']);p.add_argument('plan');p.add_argument('--out',required=True);p.add_argument('--approve',action='store_true');a=p.parse_args()
    if not a.approve:p.error('Explicit --approve is required for new computation')
    result=execute_plan(json.loads(Path(a.plan).read_text(encoding='utf-8')),a.out)
    print(json.dumps({'status':result['status'],'resources':result['resources'],'winner_id':result['winner_id']},ensure_ascii=False))

if __name__=='__main__':main()
