"""Read-only verification of saved RC6 canonical plans; performs zero fits."""
import json
import sys
from pathlib import Path
from photonguard.experiments import inverse_models as models


def main(source,destination):
    rows=[]
    for path in sorted(Path(source).rglob('request.json')):
        payload=json.loads(path.read_text());plan=payload.get('plan')
        if not isinstance(plan,dict) or not plan.get('schema','').startswith('photonguard.inverse-plan.'):
            continue
        models.verify_plan(plan)
        rows.append({'source':str(path),'model':plan['model'],'operation':plan['operation'],'sha256':plan['sha256'],'verified_without_rewrite':True})
    report={'saved_plans':len(rows),'plans':rows,'fit_runs':0,'profile_runs':0,'model_calls':0,'old_files_modified':False}
    Path(destination).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'verified_saved_plans':len(rows),'new_fits':0}))


if __name__=='__main__':main(*sys.argv[1:])
