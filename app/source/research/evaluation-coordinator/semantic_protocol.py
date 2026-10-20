"""Unchanged public tools and exact submission extraction shared with GUI. No CLI execution."""
import live_transport as transport

TOOLS=[{'type':'function','function':{'name':name,'description':description,'parameters':parameters}} for name,description,parameters in [
    ('export_visible_input','Read/export the currently coordinator-released view; no future material.',{'type':'object','properties':{},'additionalProperties':False}),
    ('read_public_material','Read the same approved public rule/schema/tool documentation available to all conditions.',{'type':'object','properties':{'name':{'type':'string','enum':['contract','response_schema','tool_usage','semantic_rule_source','legacy_rule_source','legacy_intake_source','common_wrapper_source']}},'required':['name'],'additionalProperties':False}),
    ('review_public_candidate','Run the complete current structural semantic rule on a draft. A rejection still counts. This tool cannot judge meaning or approve.',{'type':'object','properties':{'candidate':{'type':'object'}},'required':['candidate'],'additionalProperties':False}),
    ('review_legacy_intent','Use the complete existing explicit-fact/proposal rules. This legacy shape differs from the public semantic contract; do not invent defaults or authority.',{'type':'object','properties':{'bundle':{'type':'object'},'proposal':{'type':'object'}},'required':['bundle','proposal'],'additionalProperties':False}),
    ('legacy_intake_export','Export existing independent-raw-document intake. Legacy documents require explicit source roles, never invent them.',{'type':'object','properties':{'input':{'type':'object'}},'required':['input'],'additionalProperties':False}),
    ('legacy_intake_import','Run existing independent-raw-document intake review, preserving its complete original rules.',{'type':'object','properties':{'input':{'type':'object'},'candidate':{'type':'object'}},'required':['input','candidate'],'additionalProperties':False})]]


def candidate_contents(message):
    """Operational text during tool calls is a retained tool turn, not a final.

    Every no-tool content, including malformed/prose content, is a submission.
    Every review tool draft is a submission, even if rejected or unparseable.
    No validity/acceptance test selects which submitted answers get counted.
    """
    contents=[]
    if not message.get('tool_calls') and isinstance(message.get('content'),str):
        contents.append(('ASSISTANT_FINAL_CONTENT',message['content']))
    for i,call in enumerate(message.get('tool_calls') or [],1):
        fn=call['function']
        if fn['name']=='review_public_candidate':
            try:raw=transport.raw_member(fn['arguments'],'candidate')
            except (ValueError,TypeError,RecursionError):raw=fn['arguments']
            contents.append(('MODEL_DRAFT_FOR_TOOL_REVIEW_%02d'%i,raw))
    return contents
