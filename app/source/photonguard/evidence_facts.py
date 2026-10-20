"""Hash-bound facts extracted from immutable solver evidence, never model prose."""
from pathlib import Path
import hashlib
from .core import digest, load
from .runner import verify_evidence

CONTRACT = 'evidence-facts-v1'

def pointer_value(document, pointer):
    value = document
    for key in pointer.split('/')[1:]:
        key = key.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value

def collect_facts(evidence):
    root = Path(evidence)
    if not verify_evidence(root):
        raise ValueError('FACT_EVIDENCE_INTEGRITY')
    report = load(root / 'report.json')
    facts = {}
    def add(ident, artifact, pointer, unit, kind='measured_fact'):
        path = root / artifact
        value = pointer_value(load(path), pointer)
        facts[ident] = {'fact_id': ident, 'value': value, 'unit': unit,
            'source_artifact': artifact, 'json_pointer': pointer,
            'artifact_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'kind': kind}
    for index, check in enumerate(report['checks']):
        add('check.' + check['id'] + '.status', 'report.json', f'/checks/{index}/status', 'status')
        for key, value in check.get('metrics', {}).items():
            if type(value) in (int, float):
                unit = 'dimensionless'
                if key.endswith('amplitude'): unit = 'source_amplitude'
                if key == 'frequency_count': unit = 'count'
                add('check.' + check['id'] + '.' + key, 'report.json', f'/checks/{index}/metrics/{key}', unit)
    for variant in ('base', 'grid', 'time', 'pml'):
        artifact = f'raw/{variant}.json'
        if not (root / artifact).exists():
            continue  # No simulated measurements for static/failed worker evidence.
        for key, unit in [('resolution', 'pixels_per_length_unit'), ('after_sources', 'simulation_time'),
                ('courant', 'dimensionless'), ('pml_um', 'um'), ('source_amplitude', 'source_amplitude')]:
            if key in load(root / artifact).get('target_recipe', {}):
                add(f'{variant}.{key}', artifact, '/target_recipe/' + key, unit)
    value = {'contract': CONTRACT, 'task_sha256': report['task_hash'],
        'candidate_sha256': report['candidate_hash'],
        'report_sha256': hashlib.sha256((root / 'report.json').read_bytes()).hexdigest(),
        'facts': facts, 'limitations': ['Facts describe actual recorded settings; local sensitivity does not prove convergence',
            'after_sources is duration after source completion, not a Courant time step']}
    value['facts_sha256'] = digest(value)
    return value

def verify_facts(evidence, table):
    if table != collect_facts(evidence):
        raise ValueError('FACT_TABLE_OR_POINTER_BINDING')
    return True

def compact_facts(table):
    """Deduplicate artifact metadata for the 64 KiB wire cap; lose no fact/pointer."""
    artifacts={};facts={}
    for ident,entry in table['facts'].items():
        artifact=entry['source_artifact'];sha=entry['artifact_sha256']
        if artifact in artifacts and artifacts[artifact]!=sha:raise ValueError('FACT_ARTIFACT_HASH_COLLISION')
        artifacts[artifact]=sha
        facts[ident]={'value':entry['value'],'unit':entry['unit'],'a':artifact,'p':entry['json_pointer']}
        if entry['kind']!='measured_fact':facts[ident]['kind']=entry['kind']
    return {'contract':'evidence-facts-wire-v1','facts_sha256':table['facts_sha256'],
        'default_kind':'measured_fact','encoding':{'a':'source_artifact','p':'json_pointer'},
        'artifacts':artifacts,'facts':facts,'limitations':table['limitations']}

def verify_compact_facts(evidence,wire):
    full=collect_facts(evidence)
    if wire!=compact_facts(full):raise ValueError('FACT_WIRE_OR_POINTER_BINDING')
    return full
