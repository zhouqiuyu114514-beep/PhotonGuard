"""RPC-only offline worker. Bubblewrap mounts just public tools and one view.

No coordinator, model key, provider client invocation, arbitrary command/path,
task approval or solver endpoint is exposed to the model.
SPDX-License-Identifier: GPL-2.0-or-later
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, '/tools/research/intent-pilot')
sys.path.insert(0, '/tools')
import semantic_intake as adapter
import public_tool

WORK=Path('/work')
SESSION=WORK/'rule-session'
MATERIALS={'contract':'research/intent-pilot/public-contract/semantic_contract.json',
           'response_schema':'research/intent-pilot/public-contract/response.schema.json',
           'tool_usage':'TOOL_USAGE_ZH.txt',
           'semantic_rule_source':'research/intent-pilot/semantic_intake.py',
           'legacy_rule_source':'research/intent-pilot/intent_pilot.py',
           'legacy_intake_source':'research/intent-pilot/requirements_intake.py',
           'common_wrapper_source':'research/intent-pilot/public_tool.py'}


def reserve(operation, status='RETURNED'):
    SESSION.mkdir(exist_ok=True)
    for i in range(1,9):
        call=SESSION/('call-%02d'%i)
        try:call.mkdir(exist_ok=False)
        except FileExistsError:continue
        (call/'event.json').write_text(json.dumps({'operation':operation,'call_number':i,
            'status':status,'model_calls':0,'solver_calls':0,'elapsed_seconds':None})+'\n')
        return call
    return None


def raw_member(text,name):
    decoder=json.JSONDecoder();pos=0;found=None
    def space(i):
        while i<len(text) and text[i] in ' \t\r\n':i+=1
        return i
    pos=space(0)+1
    while text[space(pos):space(pos)+1]!='}':
        pos=space(pos);key,end=decoder.raw_decode(text,pos);pos=space(end)+1
        start=space(pos);unused,end=decoder.raw_decode(text,start)
        if key==name:found=text[start:end]
        pos=space(end)
        if text[pos:pos+1]==',':pos+=1
    if found is None:raise ValueError('missing member')
    return found


def main():
    raw=sys.stdin.buffer.read(1048577)
    if len(raw)>1048576:raise ValueError('RPC cap exceeded')
    request=json.loads(raw)
    if set(request)!={'name','arguments'} or not isinstance(request['name'],str) or not isinstance(request['arguments'],str):
        raise ValueError('closed RPC required')
    argument_file=WORK/'rpc-arguments.json'
    argument_file.write_text(request['arguments'],encoding='utf-8')
    try:args=adapter.read(argument_file,decimal_numbers=True)
    except (ValueError,TypeError,UnicodeError,RecursionError):
        call=reserve(request['name'],'REJECTED')
        return {'status':'REJECTED' if call else 'BUDGET_STOP'}
    name=request['name']
    if name=='read_public_material':
        call=reserve(name)
        if not call:return {'status':'BUDGET_STOP'}
        tick=time.perf_counter()
        if type(args) is not dict or set(args)!={'name'} or args['name'] not in MATERIALS:
            result={'status':'REJECTED'}
        else:
            result={'status':'RETURNED','text':(Path('/tools')/MATERIALS[args['name']]).read_text()}
        (call/'event.json').write_text(json.dumps({'operation':name,'status':result['status'],
           'elapsed_seconds':time.perf_counter()-tick,'model_calls':0,'solver_calls':0})+'\n')
        return result
    if name=='export_visible_input' and args=={}:
        op='semantic-export';source='/visible/view.json';candidate=None
    elif name=='review_public_candidate' and type(args) is dict and set(args)=={'candidate'}:
        op='semantic-import';source='/visible/view.json';candidate='/work/candidate.json'
        Path(candidate).write_text(raw_member(request['arguments'],'candidate'),encoding='utf-8')
    elif name=='review_legacy_intent' and type(args) is dict and set(args)=={'bundle','proposal'}:
        op='legacy-review';source='/work/bundle.json';candidate='/work/proposal.json'
        Path(source).write_text(raw_member(request['arguments'],'bundle'),encoding='utf-8')
        Path(candidate).write_text(raw_member(request['arguments'],'proposal'),encoding='utf-8')
    elif name=='legacy_intake_export' and type(args) is dict and set(args)=={'input'}:
        op='legacy-export';source='/work/legacy-input.json';candidate=None
        Path(source).write_text(raw_member(request['arguments'],'input'),encoding='utf-8')
    elif name=='legacy_intake_import' and type(args) is dict and set(args)=={'input','candidate'}:
        op='legacy-import';source='/work/legacy-input.json';candidate='/work/legacy-candidate.json'
        Path(source).write_text(raw_member(request['arguments'],'input'),encoding='utf-8')
        Path(candidate).write_text(raw_member(request['arguments'],'candidate'),encoding='utf-8')
    else:
        call=reserve(name,'REJECTED')
        return {'status':'REJECTED' if call else 'BUDGET_STOP'}
    before=set(SESSION.glob('call-*')) if SESSION.exists() else set()
    sys.argv=['public_tool.py',op,'--source',source,'--session',str(SESSION)]
    if candidate:sys.argv+=['--candidate',candidate]
    if op.startswith('semantic-'):
        trusted=json.loads(Path('/visible/trusted.json').read_text())['expected_input_sha256']
        sys.argv+=['--expected-input-sha256',trusted]
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        try:public_tool.main()
        except SystemExit as e:code=e.code
    new=set(SESSION.glob('call-*'))-before
    if not new:return {'status':'BUDGET_STOP'}
    call=new.pop();output=call/'output.json'
    if code or not output.exists():return {'status':'REJECTED','reason':'STRUCTURAL_RULE_REJECTION'}
    result=json.loads(output.read_text())
    if op=='semantic-import':
        # Public feedback includes no coordinator score, labels, mapping sidecar
        # or unreleased material; normalization remains visibly a tool stage.
        return {'status':result['status'],'normalized_response':result['normalized_response'],
                'semantic_entailment_verified':False,'task_approved':False}
    return {'status':'RETURNED','output':result}


if __name__=='__main__':
    try:result=main()
    except (ValueError,TypeError,KeyError,OSError,UnicodeError,RecursionError):
        result={'status':'REJECTED','reason':'INVALID_TOOL_RPC'}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
