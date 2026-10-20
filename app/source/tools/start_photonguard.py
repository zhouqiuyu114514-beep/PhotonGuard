"""Portable local product entry. Optional paid binding, memory credential only."""
import argparse,getpass,json,sys
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from photonguard.workflow import make_server
from photonguard.repair_pipeline import ThreeStepPipeline
from photonguard.service_identity import identity,require_match

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--data',type=Path,default=ROOT/'workspace-data');p.add_argument('--port',type=int,default=8778)
 p.add_argument('--phase',type=Path);p.add_argument('--binding',type=Path)
 p.add_argument('--credential-stdin',action='store_true',help='Read one line from private pipe, never from arguments or environment')
 p.add_argument('--simulation',type=Path,help='Frozen offline simulator permit; separate data directory required')
 a=p.parse_args();simulation=json.loads(a.simulation.read_text()) if a.simulation else None
 if simulation and (a.data.resolve()==(ROOT/'workspace-data').resolve() or a.phase or a.binding):raise ValueError('模拟服务必须独立存储且禁用收费入口')
 if simulation and (simulation.get('actor_type')!='SIMULATED' or simulation.get('model_calls_allowed')!=0 or simulation.get('physical_runs_allowed')!=0):raise ValueError('Unsupported simulation permit')
 if bool(a.phase)!=bool(a.binding):raise ValueError('Paid phase and source binding required together')
 mode='PRODUCT_DEEPSEEK' if a.phase else 'RULES_ONLY'
 expected=identity(ROOT,a.data,mode=mode,mode_qpm=True,simulation=simulation)
 try:
  with urlopen(f'http://127.0.0.1:{a.port}/api/bootstrap',timeout=1) as response:existing=json.load(response)
 except OSError:existing=None
 if existing is not None:
  require_match(expected,existing);print('Matching service already running',flush=True);return
 key=None;client=None;broker=None
 if a.phase:
  from photonguard.product_phase import ProductClient
  from photonguard.product_diagnosis import ProductBroker
  ProductClient(ROOT,a.phase,a.binding).preflight(False)
  key=sys.stdin.readline().strip() if a.credential_stdin else getpass.getpass('DeepSeek credential (hidden): ')
  client=ProductClient(ROOT,a.phase,a.binding,lambda:key);broker=ProductBroker(client)
 with make_server(a.data,port=a.port,allow_workers=not bool(simulation)) as server:
  store=server.store;store.simulation_context=simulation;store.service_identity=expected;store.product_client=client
  store.pipeline_controller=ThreeStepPipeline(store,broker)
  from photonguard.mode_pipeline import ModePipeline
  store.mode_controller=ModePipeline(store)
  print(json.dumps({'url':f'http://127.0.0.1:{a.port}/','mode':mode,'simulated':bool(simulation),'automatic_requests':False}),flush=True)
  try:server.serve_forever(poll_interval=.2)
  except KeyboardInterrupt:pass
 key=None
if __name__=='__main__':main()
