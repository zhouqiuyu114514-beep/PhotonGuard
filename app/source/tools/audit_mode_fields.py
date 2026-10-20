"""Only read original mode fields; append research diagnostics, never product receipts."""
from pathlib import Path
import argparse,hashlib,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photonguard.mode_field_research import audit_field_file,competitor_matrices
from photonguard.mode_precision import audit_raw_worker_series,classify_precision_evidence
from photonguard.mode_verification import overlap_squared

def read(p):return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()
def save(p,value):
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();index=read(args.index);assert not args.out.exists();args.out.mkdir(parents=True)
    save(args.out/'started.json',{'index_sha256':sha(args.index),'new_solver_runs':0,'new_model_requests':0,'automatic_retry':False})
    start=time.monotonic();bundles=[];audits=[];comparisons=[];v1max=0.
    for declared in index['bundles']:
        root=Path(declared['full_local_bundle']);seed=declared['base_resolution'];manifest=read(root/'manifest.json')
        assert sha(root/'manifest.json')==declared['manifest_sha256']
        # Full data really exists locally; a declared hash is not substituted for reading it.
        for name,value in manifest['files'].items():
            p=(root/name).resolve();assert p.is_relative_to(root.resolve()) and p.is_file() and sha(p)==value
        bundles.append((seed,root));report=read(root/'report.json')
        for wave in (1.55,.775):
            base=root/('base-'+str(wave));first=read(base/'result.json')
            for variant in ('base','grid','domain'):
                folder=root/(variant+'-'+str(wave));raw=read(folder/'result.json')
                for mode in raw['all_modes']:
                    p=folder/mode['fields_npz'];item=audit_field_file(p,mode,raw['domain_um'])
                    declared_hash=manifest['files'][str(p.relative_to(root))]
                    assert item['sha256']==declared_hash
                    audits.append({'seed_resolution':seed,'variant':variant,'wavelength_um':wave,
                        'band':mode['band'],'source':str(p),**item})
                if variant=='base':continue
                old=next(c for c in report['checks'] if c['id']==str(wave)+'.mode_identity')
                original=overlap_squared(base,first['selected_mode'],folder,raw['selected_mode'])
                expected=old['overlap_squared'][0 if variant=='grid' else 1]
                v1max=max(v1max,abs(original-expected));assert abs(original-expected)<=1e-12
                result=competitor_matrices(base,first,folder,raw)
                filename=f'identity-r{seed}-{wave}-{variant}.json'
                save(args.out/filename,{'before':str(base),'after':str(folder),
                    'E_L2_overlap_v1_recomputed':original,'E_L2_overlap_v1_recorded':expected,**result})
                selected=next(r for r in result['all_competing_band_pairs'] if r['first_band']==result['first_selected_band'] and r['second_band']==result['second_selected_band'])
                comparisons.append({'seed_resolution':seed,'wavelength_um':wave,'variant':variant,
                    'matrix_file':filename,'E_L2_overlap_v1':original,'selected_research_metrics':selected,
                    'competing_pairs':len(result['all_competing_band_pairs'])})
        print(json.dumps({'audited_seed':seed,'field_files_so_far':len(audits),'new_solver_runs':0}),flush=True)
    assert len(audits)==96 and len(comparisons)==16
    goal={'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':20,
          'qpm_order':1,'target_phase_factor_min':.8}
    scalar=audit_raw_worker_series(bundles,goal);save(args.out/'raw-scalar-audit.json',scalar)
    save(args.out/'96-full-fields-audit.json',{'files':audits,'all_hashes_and_arrays_actually_read':True,
        'unweighted_component_fraction_not_electric_energy':True,'new_solver_runs':0})
    levels=classify_precision_evidence(record_integrity=True,root_closure=True,mode_identity=True,
        setting_sensitivity=True,phase_status='INCONCLUSIVE',design_goal_status='NOT_EVALUATED')
    summary={'field_files_checked':96,'all_finite':True,'actual_raw_worker_records':scalar['actual_worker_records'],
        'unique_setting_wavelength_combinations':scalar['unique_setting_wavelength_combinations'],
        'E_L2_overlap_v1_max_reproduction_difference':v1max,'research_comparisons':comparisons,
        'four_by_four_competitor_matrices':16,'field_pair_metrics':256,
        'negative_dpwr_samples':sum(a['electric_energy_raw']['negative_sample_count'] for a in audits),
        'most_negative_dpwr':min(a['electric_energy_raw']['minimum'] for a in audits),
        'evidence_levels':levels,'wall_seconds':time.monotonic()-start,'new_solver_runs':0,'new_model_requests':0,
        'no_original_files_modified':True,'old_v1_thresholds_and_statuses_preserved':True}
    save(args.out/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('research_comparisons','evidence_levels')},indent=2))
if __name__=='__main__':main()
