"""Explicit opt-in CLI boundary. No credential access during import or tests."""
from pathlib import Path
import os
from .core import load,write_json,digest
from .exchange import export_request,action_to_patch,save_exchange

def diagnose_api(args):
    from .backend import ApprovedRates,BackendAuthorization,DeepSeekConfig,DeepSeekBackend,PersistentBudgetLedger,BackendError
    if not args.approve_data_and_cost:raise ValueError("Explicit approval to send diagnostic data and incur bounded API cost is required")
    data=load(args.config)
    if not isinstance(data,dict) or 'api_key' in data:raise ValueError("Configuration must be an object without secrets; use the secure credential environment")
    authorization=data.get('authorization',{})
    if authorization.get('approved') is not True:raise ValueError("No approved provider/model/data/spending authorization in configuration")
    model=data.get('model')
    rates=ApprovedRates(**authorization['rates'])
    auth=BackendAuthorization(approved=True,reference=authorization['reference'],model=authorization['model'],total_budget_usd=authorization['total_budget_usd'],max_calls=authorization['max_calls'],rates=rates)
    request=export_request(args.evidence)
    # Only an explicit invocation with approval reaches this exact environment key.
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key:raise ValueError("Secure DEEPSEEK_API_KEY is not configured. No model call was made.")
    config=DeepSeekConfig(model=model,authorization=auth,api_key=key,**data.get('limits',{}))
    backend=DeepSeekBackend(config,ledger=PersistentBudgetLedger(auth,args.ledger))
    audit_dir=Path(args.audit_dir)
    if audit_dir.exists():raise ValueError("Audit directory already exists; do not overwrite prior model evidence")
    if Path(args.out).exists():raise ValueError("Proposal output already exists; choose a new file")
    try:
        result=backend.diagnose(request)
    except BackendError as e:
        audit_dir.mkdir(parents=True,exist_ok=False)
        write_json(audit_dir/'request.json',request);write_json(audit_dir/'failure.audit.json',e.audit)
        print("API diagnostic stopped; sanitized failure audit saved. No candidate changed.")
        return 3
    audit=result['audit'];action=result['action']
    if audit.get('transport_kind')!='live_https' or audit.get('actual_llm_calls')!=1:raise ValueError("CLI refuses to present injected/mock responses as live API evidence")
    provenance={'mode':'deepseek_api','model_identity':audit.get('provider_model'),'requested_model':model,'api_calls':1,'runtime_api_calls':1,'request_payload_sha256':digest(request),'provider_audit':audit}
    try:
        patch=action_to_patch(args.evidence,request,action,provenance)
    except ValueError as e:
        audit_dir.mkdir(parents=True,exist_ok=False)
        write_json(audit_dir/'request.json',request);write_json(audit_dir/'response.action.json',action);write_json(audit_dir/'provider.audit.json',audit);write_json(audit_dir/'validation.json',{'status':'REJECTED','reason':str(e)})
        print("Model action rejected by independent bounds; audit saved. No candidate changed.")
        return 3
    save_exchange(audit_dir,request,action,provenance,patch)
    if patch is None:print("API diagnosis recorded; no patch proposed. Verifier status remains unchanged.");return 0
    write_json(args.out,patch)
    print("API proposal saved. Review it, explicitly approve it, then rerun all Meep checks.")
    return 0
