"""Trial-package launcher only. Source is pinned to the maintenance commit."""
from pathlib import Path
import hashlib,json,os,signal,sys

def verify(root):
    import numpy,scipy,tmm,ssl
    assert numpy.__version__=='2.5.3' and scipy.__version__=='1.18.1'
    ssl.create_default_context()
    manifest=json.loads((root/'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    for name,wanted in manifest['files'].items():
        file=root/'source'/name
        assert file.resolve().is_relative_to((root/'source').resolve())
        if hashlib.sha256(file.read_bytes()).hexdigest()!=wanted:raise RuntimeError('源码文件已改变，请重新解压原始试用包：'+name)
    from photonguard.workflow import make_server
    return {'status':'READY','python':sys.version.split()[0],'numpy':numpy.__version__,'scipy':scipy.__version__,'source_files':len(manifest['files']),'source_commit':manifest['source_commit'],'model_requests':0}

def main():
    operation=sys.argv[1];root=Path(sys.argv[2]).resolve();statefile=root/'data/service.json'
    if operation=='verify':
        result=verify(root)
        if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(result),encoding='utf-8')
        print(json.dumps(result),flush=True);return
    if operation=='stop':
        if not statefile.exists():print('没有需要停止的试用服务。');return
        state=json.loads(statefile.read_text());pid=int(state['pid'])
        try:args=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:print('试用服务已经关闭。');return
        expected=[str(Path(__file__).resolve()).encode(),b'serve',str(root).encode()]
        if not all(x in args for x in expected):raise RuntimeError('进程与此试用包不匹配，未停止任何程序。')
        os.kill(pid,signal.SIGINT);print('已请求关闭此试用工作台；已开始的有限计算会保留结果。');return
    if operation!='serve':raise ValueError('Unknown operation')
    info=verify(root);port=int(sys.argv[3])
    from photonguard.workflow import make_server
    with make_server(root/'data/workspace',port=port,allow_workers=True) as server:
        server.store.service_identity={'release_id':'photonguard-rc9-success-quota-20261020','source_root':str(root/'source'),'data_root':str(root/'data/workspace'),'source_commit':info['source_commit'],'package_root':str(root)}
        state={'pid':os.getpid(),'port':port,'package_root':str(root),'url':f'http://127.0.0.1:{port}/experiments'}
        statefile.write_text(json.dumps(state),encoding='utf-8')
        print('READY '+state['url'],flush=True)
        try:server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:pass
        finally:
            if statefile.exists() and json.loads(statefile.read_text()).get('pid')==os.getpid():statefile.unlink()

if __name__=='__main__':main()
