"""Validate supplied execution evidence without running attached code or solvers.

This verifies internal consistency and binding to the original delivery. It does
not attest the remote host, reproduce its execution, or prove target-mode rank.
All checks are explicit exceptions and remain effective under Python -O.
"""
import argparse,csv,hashlib,json,math,zipfile
from datetime import datetime
from fractions import Fraction as F
from pathlib import Path,PurePosixPath
import xml.etree.ElementTree as ET

def require(condition,code):
    if not condition:raise ValueError(code)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_manifest(root):
    root=Path(root).resolve();m=read(root/'MANIFEST.json')['files']
    require(not any(p.is_symlink() for p in root.rglob('*')),'SYMLINK_NOT_ALLOWED')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p!=root/'MANIFEST.json'}
    require(actual==set(m),'MANIFEST_FILE_SET')
    for name,item in m.items():
        rel=PurePosixPath(name)
        require(not rel.is_absolute() and '..' not in rel.parts and '\\' not in name and ':' not in name,'MANIFEST_PATH')
        p=(root/name).resolve();require(root in p.parents,'MANIFEST_ESCAPE')
        digest=item if isinstance(item,str) else item['sha256']
        require(sha(p)==digest,'MANIFEST_HASH:'+name)
        if isinstance(item,dict):require(p.stat().st_size==item['bytes'],'MANIFEST_SIZE:'+name)
    return len(m)

def interval_margin(d):
    r=d['R'];lo,hi=r['real'];il,ih=r['imag'];bounds=[]
    require(all(len(a)==3 and all(len(row)==3 for row in a) for a in (lo,hi,il,ih)),'MATRIX_DIMENSION')
    for i in range(3):
        off=F(0)
        for j in range(3):
            vals=[lo[i][j],hi[i][j],il[i][j],ih[i][j]]
            require(all(math.isfinite(v) for v in vals),'MATRIX_NONFINITE')
            require(lo[i][j]<=hi[i][j] and il[i][j]<=ih[i][j],'INTERVAL_ORDER')
            require(max(lo[i][j],lo[j][i])<=min(hi[i][j],hi[j][i]),'REAL_HERMITIAN')
            require(max(il[i][j],-ih[j][i])<=min(ih[i][j],-il[j][i]),'IMAG_HERMITIAN')
            if i!=j:
                q=max(abs(F(lo[i][j])),abs(F(hi[i][j])))**2+max(abs(F(il[i][j])),abs(F(ih[i][j])))**2
                scale=10**40;off+=F(math.isqrt(q.numerator*scale*scale//q.denominator)+1,scale)
        bounds.append(F(lo[i][i])-off)
    require(min(bounds)>0,'MATRIX_NOT_STRICTLY_POSITIVE')
    return float(min(bounds))

def nested_evidence(folder):
    # The solver's manifest is lower-case and has string digests.
    m=read(folder/'manifest.json')['files']
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name!='manifest.json'}
    require(actual==set(m),'SOLVER_MANIFEST_FILE_SET')
    for name,digest in m.items():
        require((folder/name).resolve().is_relative_to(folder.resolve()),'SOLVER_MANIFEST_PATH')
        require(sha(folder/name)==digest,'SOLVER_MANIFEST_HASH')
    return len(m)

def audit(cloud,baseline,baseline_zip):
    cloud=Path(cloud);baseline=Path(baseline);baseline_zip=Path(baseline_zip);e=cloud/'evidence'
    cloud_count=verify_manifest(cloud);base_count=verify_manifest(baseline)
    provenance=read(e/'INPUT_PROVENANCE.json')['inputs']
    for item in provenance:
        path=baseline_zip if item['filename'].endswith('.zip') else baseline/'REPORT_ZH.md'
        require(sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'UPLOADED_INPUT_BINDING')
    require(len(provenance)==2,'EXPECTED_TWO_INPUTS')
    source=read(baseline/'SOURCE_MANIFEST.json');observed=read(e/'source-hash-verification.json')
    require(observed['git_commit_claim']==source['git_commit'],'SOURCE_COMMIT_BINDING')
    require(set(observed['files'])==set(source['files']),'SOURCE_FILE_SET')
    plan=read(e/'FROZEN_REPRODUCTION_PLAN.json')
    require((e/'FROZEN_REPRODUCTION_PLAN.sha256').read_text().strip()==sha(e/'FROZEN_REPRODUCTION_PLAN.json'),'PLAN_HASH')
    with zipfile.ZipFile(baseline/'SOURCE.zip') as z:
        for name,digest in source['files'].items():
            require(hashlib.sha256(z.read('PhotonGuard/'+name)).hexdigest()==digest,'SOURCE_ZIP_HASH:'+name)
            row=observed['files'][name];require(row['expected']==row['actual']==digest and row['passed'] is True,'REMOTE_SOURCE_HASH:'+name)
        for name,digest in plan['file_sha256'].items():
            if name.startswith('work/PhotonGuard/'):
                actual=hashlib.sha256(z.read('PhotonGuard/'+name.removeprefix('work/PhotonGuard/'))).hexdigest()
            else:
                prefix='package/PhotonGuard-small-certificates-20261008/'
                require(name.startswith(prefix),'PLAN_INPUT_PATH');actual=sha(baseline/name.removeprefix(prefix))
            require(actual==digest,'PLAN_INPUT_HASH')
        require(z.read('PhotonGuard/runtime/conda-linux-64.lock')==(e/'install/conda-linux-64.lock').read_bytes(),'DEPENDENCY_LOCK_BINDING')
    frozen=datetime.fromisoformat(plan['frozen_at_utc'])
    for name in ('pump','SH','acceptance','regression','install/bootstrap'):
        receipt=read(e/(name+'.receipt.json'));require(receipt['exit_code']==0,'EXECUTION_EXIT:'+name)
        start=datetime.fromisoformat(receipt['started_utc']);end=datetime.fromisoformat(receipt['finished_utc'])
        require(end>=start and receipt['elapsed_seconds']>=0,'EXECUTION_TIME')
        if name in ('pump','SH'):
            require(start>=frozen,'PLAN_NOT_FROZEN_BEFORE_CHECKER')
            require(receipt['elapsed_seconds']<=plan['independent_certificate_window'][name]['max_seconds'],'CHECKER_TIME_CAP')
        require('-O' not in receipt['command'] and '-OO' not in receipt['command'],'OPTIMIZED_EXECUTION_ARGV')
    flags=read(e/'python-flags.json');require(flags['optimization_level']==0 and flags['__debug__'] is True,'OBSERVED_OPTIMIZATION_ENABLED')
    smoke=json.JSONDecoder().raw_decode((e/'install/smoke-runtime.log').read_text().lstrip())[0]
    require(smoke['status']=='PASS' and smoke['real_fdtd']['steps']>0 and smoke['real_fdtd']['positive_vacuum_flux']>0,'BOOTSTRAP_PHYSICAL_SMOKE')
    # The supplied flags observation is post-run; preserve that scope in output.
    expected=set()
    for row in (e/'install/conda-linux-64.lock').read_text().splitlines():
        if row.startswith('https://'):
            name=row.split('#')[0].rsplit('/',1)[-1]
            name=name.removesuffix('.conda').removesuffix('.tar.bz2')
            expected.add(tuple(name.rsplit('-',2)))
    actual={(p['name'],p['version'],p['build']) for p in read(e/'install/conda-actual-packages.json')}
    require(expected==actual and len(actual)==124,'DEPENDENCY_PACKAGE_SET')
    old_pump=read(baseline/'evidence/pump-certificate.json');pump=read(e/'pump-external.json')
    old_pump={k:v for k,v in old_pump.items() if k not in ('seconds','peak_rss_kib')}
    require(old_pump==pump,'PUMP_MATHEMATICAL_FIELDS')
    require(pump['status']=='MODEL_PUMP_UPPER_VERIFIED','PUMP_STATUS')
    sh=read(e/'SH-external.json');require(sh['status']=='CONTINUOUS_LOW_SPECTRAL_COUNT_VERIFIED','SH_STATUS')
    require(sh['new_spatial_assemblies']==2 and sh['target_mode_rank_bound'] is False,'SH_SCOPE')
    require(len(sh['endpoints'])==2,'ENDPOINT_COUNT');margins=[]
    for name,point in zip(('low','high'),sh['endpoints']):
        old=read(baseline/f'evidence/basis-binding-v3/SH-r40-{name}.json')
        for field in ('R','parameter_s_exact','wavelength_exact','tau_exact','c_exact','positive_definiteness'):
            require(point[field]==old[field],'SH_ENDPOINT_BINDING:'+field)
        margins.append(interval_margin(point))
    acceptance=read(e/'external-run-001/acceptance.json');require(acceptance['status']=='PASS','ACCEPTANCE_STATUS')
    reports={}
    for label in ('pass','refusal'):
        paths=list((e/'external-run-001'/label).glob('*/report.json'));require(len(paths)==1,'UNIQUE_SOLVER_RUN')
        folder=paths[0].parent;nested_evidence(folder);reports[label]=(read(paths[0]),folder)
    good,folder=reports['pass'];old=read(baseline/'external-fixtures/thinfilm-pass/report.json')
    require(good['status']=='PASS','THINFILM_STATUS')
    for field in ('task_hash','candidate_hash','policy_hash'):require(good[field]==old[field],'THINFILM_BINDING')
    require(good['resource_usage']['fdtd_runs']==good['resource_usage']['fdtd_attempts_reserved']==8,'FDTD_COUNT')
    for variant in ('base','grid','time','pml'):
        raw=read(folder/f'raw/{variant}.json');require(raw['fdtd_runs']==2,'VARIANT_FDTD_COUNT')
    def rows(p):
        with p.open() as f:return [{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]
    a,b=rows(baseline/'external-fixtures/thinfilm-pass/spectrum.csv'),rows(folder/'spectrum.csv')
    require(len(a)==len(b)==41,'SPECTRUM_GRID_SIZE');delta=0.
    for x,y in zip(a,b):
        require(all(math.isfinite(v) for v in (*x.values(),*y.values())),'SPECTRUM_NONFINITE')
        require(x['frequency']==y['frequency'] and x['wavelength_um']==y['wavelength_um'],'SPECTRUM_GRID')
        delta=max(delta,abs(x['R']-y['R']),abs(x['T']-y['T']))
    require(delta<=1e-6,'SPECTRUM_TOLERANCE')
    bad,_=reports['refusal'];require(bad['status']=='FAIL','REFUSAL_STATUS')
    require([c['id'] for c in bad['checks'] if c['status']=='FAIL']==['task_parameters'],'REFUSAL_CAUSE')
    require(bad['resource_usage']['fdtd_runs']==bad['resource_usage']['fdtd_attempts_reserved']==0,'REFUSAL_COUNT')
    require(acceptance['LN_read_only']==read(baseline/'external-fixtures/LN-status.json'),'LN_READ_ONLY_BINDING')
    log=(e/'regression.stdout.log').read_text();require('1055 passed, 1 deselected, 40 subtests passed' in log,'REGRESSION_COUNTS')
    suites=ET.parse(e/'regression.junit.xml').getroot().findall('testsuite')
    require(len(suites)==1 and suites[0].attrib['tests']=='1095' and suites[0].attrib['failures']==suites[0].attrib['errors']=='0','JUNIT_RESULT')
    return {'status':'RECEIVED_EXTERNAL_EVIDENCE_VERIFIED','baseline_commit':source['git_commit'],'baseline_zip_sha256':sha(baseline_zip),'cloud_manifest_sha256':sha(cloud/'MANIFEST.json'),'cloud_manifest_files':cloud_count,'baseline_manifest_files':base_count,'source_files':len(source['files']),'locked_packages':len(actual),'pump_mathematical_fields_match':True,'SH_interval_matrices_match':True,'exact_rational_margin_replay':margins,'spectrum_points':len(a),'max_absolute_RT_difference':delta,'reported_remote_counts':{'FDTD_total':9,'bootstrap_smoke':1,'product_FDTD':8,'local_assemblies':2,'MPB':0,'API':0},'local_new_physical_solves':0,'local_new_assemblies':0,'local_new_API_calls':0,'target_rank_bound':False,'independent_algorithm_reimplementation':False,'actual_human_trial':False,'provenance_scope':'Supplied external execution records and hashes checked locally; remote host/execution not cryptographically attested; flag observation was post-run; Git baseline verified separately in local repository.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--cloud',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--baseline-zip',type=Path,required=True);p.add_argument('--output',type=Path)
    a=p.parse_args();result=audit(a.cloud,a.baseline,a.baseline_zip);encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.output:
        with a.output.open('x',encoding='utf-8') as f:f.write(encoded)
    else:print(encoded)
    return 0
if __name__=='__main__':raise SystemExit(main())
