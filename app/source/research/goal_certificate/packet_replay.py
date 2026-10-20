"""Version 2 portable, read-only certificate replay with explicit paths."""
import hashlib, json, zipfile
from pathlib import Path, PurePosixPath
from .evidence_resolver import EvidenceResolver

def read(p):return json.loads(p.read_text())
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def verify_packet(root, output=None):
    root=Path(root).resolve()
    if output is not None:
        output=Path(output).resolve()
        if output.exists():raise ValueError('OUTPUT_ALREADY_EXISTS')
        if output.is_relative_to(root):raise ValueError('OUTPUT_INSIDE_READ_ONLY_PACKET')
    manifest=read(root/'MANIFEST.json')['files']
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p!=root/'MANIFEST.json'}
    if actual!=set(manifest):raise ValueError('MANIFEST_COVERAGE')
    for name,entry in manifest.items():
        pure=PurePosixPath(name)
        path=(root/name).resolve()
        if pure.is_absolute() or '..' in pure.parts or '\\' in name or not path.is_relative_to(root):raise ValueError('MANIFEST_ESCAPE')
        if path.stat().st_size!=entry['bytes'] or sha(path)!=entry['sha256']:raise ValueError('MANIFEST_MISMATCH:'+name)
    provenance=read(root/'PROVENANCE.json')
    if sha(root/'SOURCE.zip')!=provenance['source_archive_sha256']:raise ValueError('SOURCE_ARCHIVE_BINDING')
    for commit in provenance['executed_source_commits']:
        with zipfile.ZipFile(root/'executed-source'/(commit+'.zip')) as archive:
            if archive.testzip() is not None:raise ValueError('EXECUTED_SOURCE_CRC')
    for index in (1,2):
        receipt=read(root/'evidence/C'/('upper-'+str(index)+'.execution.json'))
        upper=read(root/'evidence/C'/('upper-'+str(index))/'result.json')
        with zipfile.ZipFile(root/'executed-source'/(receipt['source_commit']+'.zip')) as archive:
            for name,digest in upper['execution_binding']['implementation_sha256'].items():
                if hashlib.sha256(archive.read('research/goal_certificate/'+name)).hexdigest()!=digest:raise ValueError('UPPER_SOURCE_BINDING:'+name)
    resolver=EvidenceResolver(root,read(root/'PATH_MAP.json'))
    from .selected_record_sidecar import replay
    result=replay(root/'evidence/C',resolver=resolver)
    expected=read(root/'evidence/C/selected-record-continuous-certificate.json')
    for key in ('status','root_existence','root_uniqueness','research_goal_decision','certified_phase_factor_upper','J'):
        if result[key]!=expected[key]:raise ValueError('FINAL_REPLAY_MISMATCH:'+key)
    from .fixed_s_rank_one import verify
    from fractions import Fraction
    fixed=read(root/'evidence/STRICT-repair1/certificate.json')
    rank=verify(root/'inputs',read(root/'inputs/local-validation/c-special-20261010/input-bindings.json'),Fraction(fixed['rho_exact']))
    if rank['rank']!=1 or Fraction(rank['complementary_gap_lower_exact'])!=Fraction(fixed['gap_lower_exact']):raise ValueError('FIXED_RANK_REPLAY')
    audit={'status':'PASS','packet_replay_version':2,'manifest_files_verified':len(manifest),
        'research_goal_decision':result['research_goal_decision'],'phase_factor_upper':result['certified_phase_factor_upper'],
        'original_absolute_paths_used':False,'new_spatial_integrations_or_solver_API_calls':0,
        'independent_implementation_claimed':False,'original_certificate_overwritten':False}
    if output is not None:
        with output.open('x') as f:json.dump(audit,f,indent=2);f.write('\n')
    return audit

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('packet');parser.add_argument('--output')
    args=parser.parse_args();print(json.dumps(verify_packet(args.packet,args.output)))
