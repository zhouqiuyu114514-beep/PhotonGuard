"""One non-overwritable 24-cell + two-pass integration window."""
from pathlib import Path
from fractions import Fraction as F
import hashlib,json,os,resource,signal,subprocess,sys,time
import numpy as np
from .geometry import validate
from .assembly import endpoints,record
from .propagation import compare,propagate

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,value):
    with Path(p).open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
def verify_bindings(inputs):
    for key,entry in inputs.items():
        p=Path(entry['path'])
        if not p.is_file() or p.stat().st_size!=entry['bytes'] or sha(p)!=entry['sha256']:raise ValueError('INPUT_BINDING:'+key)

def freeze(out,original,model_path,record_path):
    out=Path(out);out.mkdir(exist_ok=False);original=Path(original)
    inputs={'model':Path(model_path),'topology':original/'E3/anchor-and-topology.npz','proposal':original/'C/CENTER/proposal.npz',
        'selected_record':Path(record_path),'endpoint0':original/'C/CENTER/endpoint-0.json','endpoint1':original/'C/CENTER/endpoint-1.json','old_record_integrals':original/'C/RECORD/integrals.json',
        'original_certificate':original/'C/selected-record-continuous-certificate.json'}
    with np.load(inputs['topology'],allow_pickle=False) as z:vertices=z['vertices'][z['triangles']]
    centers=vertices.mean(axis=1);chosen=[];categories=[]
    targets=[('interior',(-1,-1)),('interior',(1,-1)),('interior',(0,.15)),('interior',(0,1)),
        ('bottom-interface',(-.4,-.3)),('bottom-interface',(.4,-.3)),('slab-interface',(-1,0)),('slab-interface',(1,0)),
        ('film-interface',(-.3,.3)),('film-interface',(.3,.3)),('shoulder',(-.7,0)),('shoulder',(.7,0)),
        ('shoulder',(-.7,.3)),('shoulder',(.7,.3)),('periodic-seam',(-2,-1)),('periodic-seam',(2,-1)),
        ('periodic-seam',(-1,-2)),('periodic-seam',(-1,2)),('outer-clipping',(-1.8,1)),('outer-clipping',(1.8,1)),
        ('outer-clipping',(1,1.8)),('outer-clipping',(1,-1.8)),('pixel-cut',(.13,.13)),('pixel-cut',(-.17,-.17))]
    for category,point in targets:
        candidates=np.argsort(np.sum((centers-point)**2,axis=1))
        if category=='outer-clipping':
            axis=0 if abs(point[0])==1.8 else 1;line=point[axis]
            candidates=[i for i in candidates if min(vertices[i,:,axis])<line<max(vertices[i,:,axis])]
        ident=next(int(i) for i in candidates if int(i) not in chosen);chosen.append(ident);categories.append({'cell':ident,'category':category,'target':point})
    source=Path(__file__).parent
    plan={'inputs':{k:{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for k,p in inputs.items()},
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
        'source_sha256':{p.name:sha(p) for p in source.glob('*.py')},'pilot':categories,
        'limits':{'pilot_cells':24,'full_passes':2,'wall_seconds':1200,'memory_bytes':1024**3,'output_bytes':64*1024**2},
        'method':'Independent moment dual + P3 interpolation; 96-bit integer outward dyadic intervals; Bernstein/barycentric fan integration; independent Machin pi',
        'API_MPB_Meep':0,'upstream_counts_and_pump_theorem_assumed':True}
    save(out/'execution-plan.json',plan)
    return plan

def run(out):
    out=Path(out);plan=read(out/'execution-plan.json')
    if (out/'STARTED.json').exists():raise ValueError('WINDOW_ALREADY_STARTED')
    verify_bindings(plan['inputs'])
    if any(sha(Path(__file__).parent/name)!=value for name,value in plan['source_sha256'].items()):raise ValueError('SOURCE_CHANGED')
    save(out/'STARTED.json',{'time':time.time(),'plan_sha256':sha(out/'execution-plan.json'),'pid':os.getpid()})
    started=time.monotonic();coverage={'pilot_cells_complete':0,'endpoint_cells_complete':0,'record_cells_complete':0,'full_passes_started':0};last={}
    def timeout(*_):raise TimeoutError('INDEPENDENT_WALL_CAP')
    signal.signal(signal.SIGALRM,timeout);signal.alarm(1200)
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3));resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
    stage='preflight'
    def progress(kind,completed,total):
        if stage!='pilot':coverage[kind+'_cells_complete']=completed
        step=completed//1280
        if completed==total or step>last.get(kind,-1):
            last[kind]=step
            value={'stage':stage,'kind':kind,'completed':completed,'total':total,'seconds':time.monotonic()-started}
            print(json.dumps(value),flush=True)
            save(out/(stage+'-'+kind+'-'+str(completed)+'.progress.json'),value)
    try:
        inp={k:Path(e['path']) for k,e in plan['inputs'].items()};model=read(inp['model'])
        with np.load(inp['topology'],allow_pickle=False) as z:data={k:z[k] for k in z.files if k!='anchor'}
        with np.load(inp['proposal'],allow_pickle=False) as z:coeff=z['coefficients']
        ids,sign,core,topology=validate(data,coeff,model);save(out/'topology.json',topology)
        old=[read(inp['endpoint0']),read(inp['endpoint1'])];parameters=[F(e['s_exact']) for e in old];shifts=[F(e['arbitrary_residual_shift_exact']) for e in old]
        if parameters[1]-parameters[0]!=F(1,500):raise ValueError('ROOT_ENDPOINT_ORDER')
        stage='pilot';cells=[row['cell'] for row in plan['pilot']]
        small=endpoints(data,coeff,ids,sign,core,cells,parameters,shifts,progress)
        partial=record(data,coeff,ids,sign,cells,inp['selected_record'],progress)
        coverage['pilot_cells_complete']=24
        save(out/'pilot.json',{'status':'24_CELL_ASSEMBLY_COMPLETE','endpoints':small,'record':partial,'full_spatial_reproduction':False})
        stage='full';coverage['full_passes_started']=1;last={}
        final=endpoints(data,coeff,ids,sign,core,list(range(12800)),parameters,shifts,progress)
        for i,result in enumerate(final):
            save(out/('endpoint-'+str(i)+'.json'),result)
            for key,value in result['integrals'].items():compare(value,old[i]['integrals'][key],str(i)+':'+key)
        coverage['full_passes_started']=2
        actual=record(data,coeff,ids,sign,list(range(12800)),inp['selected_record'],progress);save(out/'record-integrals.json',actual)
        prior=read(inp['old_record_integrals'])
        for key in ('record_mass','covered_area'):compare(actual[key],prior[key],key)
        for key in ('real','imag'):compare(actual['cross_record_trial'][key],prior['cross_record_trial'][key],'cross:'+key)
        result=propagate(final,actual);result.update(all_saved_intervals_compatible=True,intervals_intersected_to_force_agreement=False)
    except (Exception,MemoryError) as error:
        result={'status':'INDEPENDENT_ASSEMBLY_INCOMPLETE','stage':stage,'error_type':type(error).__name__,'reason':str(error),'full_independent_certificate_claimed':False}
    finally:signal.alarm(0)
    result.update(coverage=coverage,wall_seconds=time.monotonic()-started,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,API_MPB_Meep_calls=0)
    save(out/'result.json',result);print(json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    if sys.argv[1]=='freeze':freeze(*sys.argv[2:])
    elif sys.argv[1]=='run':run(sys.argv[2])
    else:raise ValueError('COMMAND')
