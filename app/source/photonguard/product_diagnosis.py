"""Product-phase diagnosis using the same audited repair contract."""
from pathlib import Path
from .core import digest
from .backend import _strict_json
from .product_phase import json_payload
from .repair_diagnosis import model_request,validate_model_action,explanation_audit,retained_rejection
from .evidence_facts import verify_compact_facts
from .workflow import write_once

def diagnose(client,evidence,ident):
    base,request=model_request(evidence)
    payload=json_payload(request['prompt'],{k:request[k] for k in ('task','candidate','observations','allowed_actions')})
    result=client.complete(ident,payload);audit=result['audit']
    if audit['status']!='ASSISTANT_RETURNED':return {'status':'FAILED','patch':None,'issues':[],'reason':audit['status'],'actual_model_calls':audit.get('actual_completed_calls'),'provider_attempts':int(audit['live_dispatch'])}
    provenance={**audit,'requested_model':'deepseek-flash','actual_llm_calls':audit['actual_completed_calls']}
    try:
        action=_strict_json(result['assistant']['content'])
        patch,issues=validate_model_action(evidence,base,request,action,provenance)
        explanation=explanation_audit(action,verify_compact_facts(evidence,request['observations']['evidence_facts']))
        value={'status':'PROPOSED' if patch else 'NO_PATCH','reason':patch['rationale'] if patch else ' '.join(explanation['rendered']),
            'decision':action['decision'],'patch':patch,'issues':issues,'patch_policy_valid':True if patch else None,
            'reverification_status':'NOT_RUN','explanation_audit_status':explanation['status'],'explanation_audit':explanation}
    except (ValueError,TypeError,KeyError) as error:
        value=retained_rejection(evidence,request,locals().get('action',{}),error)
    value.update(actual_model_calls=1,model=audit['provider_model'],request_sha256=digest(request),evidence_directory=str(Path(evidence)))
    write_once(client.binding.parent/'requests'/ident/'diagnosis.json',value)
    return value

class ProductBroker:
    def __init__(self,client):self.client=client
    def preflight(self,require_key=True):return self.client.preflight(require_key)
    def status(self):return self.client.status()
    def diagnose(self,evidence):
        # One dispatch for a given saved report per immutable service binding.
        report=Path(evidence)/'report.json'
        return diagnose(self.client,evidence,'diagnosis-'+digest(report.read_text()))
