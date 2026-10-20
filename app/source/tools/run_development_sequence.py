"""Run explicitly listed development stages serially; never retry a stage.

Use one sequence for solver regressions and user journeys. The shared solver
lock is only probed here; the actual worker must still acquire it atomically.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photonguard.experiments.executor import solver_mutex, SolverBusyError


def run(stages):
    if not isinstance(stages,list) or not stages:raise ValueError('Declare at least one development stage')
    for stage in stages:
        if not isinstance(stage,dict) or set(stage)!={'name','kind','argv'} or stage['kind'] not in ('read_only','solver_regression','user_journey'):
            raise ValueError('Each stage needs name, kind and argv')
        if not isinstance(stage['name'],str) or not isinstance(stage['argv'],list) or not stage['argv'] or any(not isinstance(v,str) or not v for v in stage['argv']):
            raise ValueError('Use a named stage and a nonempty argument list, never a shell string')
    for stage in stages:
        if stage['kind']!='read_only':
            try:
                with solver_mutex():pass
            except SolverBusyError:
                print(json.dumps({'stage':stage['name'],'status':'NOT_STARTED_SOLVER_BUSY','note':'已有数据保留；等待求解结束后重新启动本开发序列，不自动重试。'},ensure_ascii=False),flush=True)
                return 2
        print(json.dumps({'stage':stage['name'],'status':'STARTED'},ensure_ascii=False),flush=True)
        result=subprocess.run(stage['argv'],check=False)  # Blocking: next stage waits for this exit.
        print(json.dumps({'stage':stage['name'],'status':'FINISHED','returncode':result.returncode},ensure_ascii=False),flush=True)
        if result.returncode:return result.returncode
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('sequence',type=Path)
    sys.exit(run(json.loads(parser.parse_args().sequence.read_text(encoding='utf-8'))))
