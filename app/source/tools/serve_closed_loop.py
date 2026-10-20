"""Stable local entry: reuse archived AI, no credentials and no paid calls."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photonguard.workflow import make_server
from photonguard.workflow_model import DeepSeekSemanticAdapter

class ArchivedOutputsOnly(DeepSeekSemanticAdapter):
    def status(self):
        result=super().status()
        result['live_enabled']=False
        result['reason']='复用已有四份AI输出；本阶段不派发模型请求。'
        path=ROOT/'local-validation/development-phase-20cny/development-budget.ledger.json'
        if path.exists():
            ledger=json.loads(path.read_text())
            result['batch']={'reference':'photonguard-development-20cny-20261006',
                'requests_used':ledger['attempts'],'requests_maximum':None,
                'reserved_cny':ledger['reserved_cny'],'cny_maximum':'20',
                'pending':ledger['pending'] is not None,'halted':ledger['halted']}
        return result
    def run(self,view,*,mode,arm='A1'):
        if mode=='live': raise ValueError('Paid dispatch disabled for this milestone')
        return super().run(view,mode=mode,arm=arm)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',default=str(ROOT/'workspace-data'))
    p.add_argument('--port',type=int,default=8778)
    args=p.parse_args()
    with make_server(args.data,port=args.port,allow_workers=True,model_adapter=ArchivedOutputsOnly()) as server:
        print(f'PhotonGuard closed loop: http://127.0.0.1:{server.server_port}/',flush=True)
        print('Archived AI only; paid calls disabled; solver needs explicit human actions.',flush=True)
        try: server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt: pass

if __name__=='__main__': main()
