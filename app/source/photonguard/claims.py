"""Finite, evidence-bound claims with independent audit and deterministic wording."""
import math
import re

CONTRACT = 'evidence-claims-v1'

def same(left, right):
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right

def render_value(value):
    return format(value, '.7g') if type(value) in (int, float) else str(value)

def fact_label(ident):
    settings={'base':'原设置','grid':'加密网格','time':'延长运行','pml':'增厚吸收边界'}
    fields={'resolution':'网格精度','after_sources':'光源结束后的运行时长','courant':'Courant系数','pml_um':'吸收边界厚度','source_amplitude':'光源幅度'}
    if ident.split('.')[0] in settings and ident.split('.')[-1] in fields:
        parts=ident.split('.');return settings[parts[0]]+'的'+fields[parts[-1]]
    tests={'task_parameters':'需求与脚本参数核对','reference_pairing':'参考与目标配对','reflection_subtraction':'入射场扣除',
        'base_independent_tmm':'与独立理论参考比较','grid_sensitivity':'加密网格敏感度','time_sensitivity':'延长运行敏感度','pml_sensitivity':'边界厚度敏感度'}
    metric={'status':'检查结果','max_absolute_change':'最大光谱变化','max_absolute_error':'最大光谱误差','tolerance':'检查阈值'}
    parts=ident.split('.')
    if len(parts)==3 and parts[0]=='check' and parts[1] in tests and parts[2] in metric:return tests[parts[1]]+'的'+metric[parts[2]]
    return ident

def unit_label(unit):
    return {'dimensionless':'（无量纲）','status':'','um':'微米','pixels_per_length_unit':'像素/Meep长度单位',
        'simulation_time':'Meep运行时间单位','source_amplitude':'光源幅度单位','count':'个'}.get(unit,unit)

def audit_claims(claims, table):
    if not isinstance(claims, list) or len(claims) > 12:
        return {'status': 'UNSUPPORTED', 'findings': [{'code': 'CLAIMS_SCHEMA'}], 'rendered': [], 'accepted': []}
    facts = table['facts']; findings = []; rendered = []; accepted = []
    for index, claim in enumerate(claims):
        try:
            if type(claim) is not dict: raise ValueError('CLAIM_SCHEMA')
            refs = claim.get('fact_refs')
            if type(refs) is not list or not 1 <= len(refs) <= 3 or any(type(r) is not str or r not in facts for r in refs):
                raise ValueError('CLAIM_REFERENCE')
            entries = [facts[r] for r in refs]
            values = [r['value'] for r in entries]
            kind = claim.get('claim_type')
            if kind == 'measured_fact':
                if set(claim) != {'claim_type', 'fact_refs', 'operation', 'value', 'unit'}: raise ValueError('CLAIM_SCHEMA')
                if any(r['unit'] != claim['unit'] for r in entries): raise ValueError('CLAIM_UNIT')
                op = claim['operation']
                if op == 'value' and len(values) == 1: expected = values[0]
                elif op == 'pair' and len(values) == 2: expected = values
                elif op == 'difference' and len(values) == 2 and all(type(v) in (int, float) for v in values): expected = values[1] - values[0]
                else: raise ValueError('CLAIM_OPERATION')
                if not same(claim['value'], expected): raise ValueError('CLAIM_VALUE_OR_DIRECTION')
                if op == 'pair': text = f'{fact_label(refs[0])} → {fact_label(refs[1])}：{render_value(values[0])} → {render_value(values[1])} {unit_label(claim["unit"])}。'
                else: text = f'{", ".join(fact_label(r) for r in refs)}：{render_value(expected)} {unit_label(claim["unit"])}。'
            elif kind == 'bounded_inference':
                if set(claim) != {'claim_type', 'fact_refs', 'operation', 'conclusion'} or len(values) != 2: raise ValueError('CLAIM_SCHEMA')
                if refs[0].rsplit('.', 1)[0] != refs[1].rsplit('.', 1)[0] or not refs[1].endswith('.tolerance') or refs[0].endswith('.tolerance'):
                    raise ValueError('CLAIM_COMPARISON_CONTEXT')
                if entries[0]['unit'] != entries[1]['unit'] or not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                    raise ValueError('CLAIM_COMPARISON_UNIT')
                exceeds = values[0] > values[1]
                expected_op = 'above_threshold' if exceeds else 'within_threshold'
                expected_conclusion = 'tested_metric_exceeds_tolerance' if exceeds else 'tested_metric_within_tolerance'
                if claim['operation'] != expected_op or claim['conclusion'] != expected_conclusion: raise ValueError('CLAIM_COMPARISON_DIRECTION')
                text = f'当前测试 {fact_label(refs[0])}={render_value(values[0])}，阈值 {render_value(values[1])}；' + ('超过阈值。' if exceeds else '在阈值内；不证明全面收敛，也不排除未经测试的原因。')
            elif kind == 'hypothesis':
                if set(claim) != {'claim_type', 'fact_refs', 'conclusion'}: raise ValueError('CLAIM_SCHEMA')
                tests = {'spatial_discretization_possible': ('check.grid_sensitivity.status', '假设：空间离散不足可能是原因之一；不是唯一原因的证明。'),
                    'settling_duration_possible': ('check.time_sensitivity.status', '假设：源结束后的运行时长可能不足；这不是时间步长检验。')}
                code = claim['conclusion']
                if code not in tests or refs != [tests[code][0]] or values != ['FAIL']: raise ValueError('CLAIM_HYPOTHESIS_UNSUPPORTED')
                text = tests[code][1]
            else:
                raise ValueError('CLAIM_TYPE_OR_UNBOUNDED_CONCLUSION')
            accepted.append(claim); rendered.append(text)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            findings.append({'claim_index': index, 'code': str(exc)})
    return {'contract': CONTRACT, 'status': 'UNSUPPORTED' if findings else 'VERIFIED_STRUCTURED_CLAIMS',
        'findings': findings, 'rendered': rendered, 'accepted': accepted,
        'facts_sha256': table['facts_sha256'], 'original_safe_response_preserved': True,
        'hypotheses_are_not_measured_causal_proofs': True}

def audit_legacy_text(text, table):
    """Flag known legacy defects; do not pretend arbitrary language is verified."""
    facts = table['facts']; findings = []
    base = facts.get('base.resolution', {}).get('value')
    grid = facts.get('grid.resolution', {}).get('value')
    if base is not None and grid is not None:
        pairs = re.findall(r'(\d+)\s*(?:→|->|和|到|至)\s*(\d+)', text)
        for first, second in pairs:
            if int(first) == base and int(second) != grid:
                findings.append({'code': 'LEGACY_GRID_VALUE_MISMATCH', 'actual_tested_pair': [base, grid]})
    clauses=re.split(r'[。！？；;\n，,]',text)
    for clause in clauses:
        step_claim=re.search(r'(不是|排除|没有).{0,16}(时间步长|Courant|time.?step)',clause,re.I)
        conservative=re.search(r'(不能|无法|不可|未能|没有).{0,6}排除.{0,16}(时间步长|Courant|time.?step)',clause,re.I)
        if step_claim and not conservative:
            findings.append({'code': 'DURATION_IS_NOT_TIMESTEP_TEST'});break
    for clause in clauses:
        convergence=re.search(r'(证明|完全|全面|保证).{0,8}(收敛|convergen)',clause,re.I)
        negated=re.search(r'(不能|不|无法|未能|尚未|不足以|does not|not).{0,8}(证明|完全|全面|保证).{0,8}(收敛|convergen)',clause,re.I)
        if convergence and not negated:
            findings.append({'code': 'UNBOUNDED_CONVERGENCE_CLAIM'});break
    return {'contract': 'legacy-text-audit-v1', 'status': 'UNSUPPORTED' if findings else 'UNVERIFIED_LEGACY_TEXT',
        'findings': findings, 'rendered': [], 'accepted': [],
        'facts_sha256': table['facts_sha256'], 'original_safe_response_preserved': True,
        'note': 'Known patterns checked; unrestricted historical prose remains unverified.'}
