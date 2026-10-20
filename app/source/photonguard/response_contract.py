"""Expose existing public validator constraints without changing frozen tools."""
import copy


def response_schema(intake):
    semantic = intake.semantic
    schema = copy.deepcopy(semantic.read(intake.PILOT / 'public-contract/response.schema.json'))
    schema['$id'] = 'urn:photonguard:semantic-intake-response:validator-aligned-2'
    refusal = schema['properties']['refusal']['properties']
    refusal['reason_codes']['items']['enum'] = list(semantic.REASONS)
    schema['allOf'] = [{
        'if': {'properties': {'review_status': {'const': 'OUT_OF_SCOPE'}}},
        'then': {'properties': {'refusal': {'properties': {
            'reason_codes': {'minItems': 1}, 'text': {'type': 'string', 'minLength': 1}}}}},
        'else': {'properties': {'refusal': {'properties': {
            'reason_codes': {'maxItems': 0}, 'text': {'type': 'null'}}}}},
    }]
    for key, kind in zip(semantic.KEYS, semantic.TYPES):
        field = schema['properties']['fields']['properties'][key]
        proposed = {}
        if kind == 'boolean':
            proposed = {'value': {'type': 'boolean'}, 'unit': {'type': 'null'}}
        elif kind == 'enum':
            proposed = {'value': {'type': 'string'}, 'unit': {'type': 'null'}}
        elif kind == 'integer':
            proposed = {'value': {'type': 'integer'}, 'unit': {'type': 'null'}}
        elif kind == 'number':
            proposed = {'value': {'type': ['number', 'string']}, 'unit': {'enum': [None, 'dimensionless', '1']}}
        elif kind == 'quantity':
            units = ['deg', '°'] if key == 'incidence_angle' else list(semantic.LENGTH)
            proposed = {'value': {'type': ['number', 'string']}, 'unit': {'enum': units}}
        proposed['evidence'] = {'minItems': 1}
        field['allOf'] = [{
            'if': {'properties': {'status': {'const': 'proposed'}}},
            'then': {'properties': proposed},
            'else': {'properties': {'value': {'type': 'null'}, 'unit': {'type': 'null'}}},
        }, {
            'if': {'properties': {'status': {'const': 'conflict'}}},
            'then': {'properties': {'evidence': {'minItems': 2}}},
        }]
    return schema


PUBLIC_RULES = (
    '遵守提供的 JSON schema 和公开语义合同，缺项或冲突通过 questions 追问。'
    'REVIEW_REQUIRED 与 CLARIFICATION_REQUIRED 时 refusal 必须是 '
    '{"reason_codes":[],"text":null}；只有 OUT_OF_SCOPE 才填写合法拒绝代码和说明。'
    '未知、冲突和不支持字段的 value、unit 必须都是 null，不擅自选择冲突值。'
    'wavelength_samples 表示等波长采样点数；频率点数不能替代它。'
    '每个未知或冲突字段都需要对应 questions.targets。待检脚本只描述实现，不能当成独立需求。'
)
