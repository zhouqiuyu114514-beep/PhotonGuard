"""Human-reviewed semantic projection; never approves, imports or solves."""
from decimal import Decimal
from .core import digest, task_problem
from .workflow_intake import review

def project(intake, options):
    if intake and intake.get('kind') == 'film_stack_task_v2':
        from .film_stack_intake import project_stack
        return project_stack(intake, options)
    if not intake or not intake.get('confirmation') or intake['status'] != 'HUMAN_REVIEWED':
        raise ValueError('先逐项核对并确认当前 AI 草稿；未知或冲突不能映射。')
    result = intake['result']
    if intake['confirmation'].get('result_sha256') != digest(result):
        raise ValueError('草稿已改变，旧确认不能用于映射。')
    answer = result['normalized_response']
    # Revalidate the currently stored draft using its independently bound input.
    import json
    verified = review(intake, 'offline', json.dumps(answer, ensure_ascii=False))
    answer = verified['normalized_response']
    if not verified['confirmable']:
        raise ValueError('仍有缺项、冲突或范围问题；请保存暂停，不得选边。')
    if not isinstance(options, dict) or set(options) != {'units_um','linear','field_component','mapping_source','accept_sampling','accept_decimal_projection','background','goal','role'}:
        raise ValueError('映射确认字段不完整。')
    if type(options['units_um']) not in (int,float) or options['units_um'] != 1 or options['linear'] is not True or options['field_component'] != 'Ex':
        raise ValueError('需要有独立依据的1微米尺度、线性介质与正入射Ex；不符合则停止。')
    if options['accept_sampling'] is not True or options['accept_decimal_projection'] is not True:
        raise ValueError('请明确审阅实际等波长求解方案及单位/精度映射。')
    for k in ('mapping_source','background','goal','role'):
        if not isinstance(options[k], str) or not 3 <= len(options[k].strip()) <= 4000:
            raise ValueError('需要已有资料的补充出处、背景、目标及角色；没有资料请暂停。')
    fields = answer['fields']
    if any(f['status'] != 'proposed' for f in fields.values()):
        raise ValueError('只能映射全部已提出且人工确认的字段。')
    def number(key, divisor=1):
        return float(Decimal(str(fields[key]['value'])) / Decimal(divisor))
    task = {'schema_version':1,'case_id':answer['case_id'] + '-wavelength-v1',
        'physics':{'dimensions':1,'angle_deg':number('incidence_angle'),
            'mu':number('relative_permeability'),'lossless':fields['lossless']['value'],
            'isotropic':fields['isotropic']['value'],'dispersive':not fields['nondispersive']['value'],
            'n_incident':number('incident_index'),'n_exit':number('exit_index')},
        'units_um':options['units_um'], 'layers':[{'n':number('film_index'),
            'thickness_um':number('film_thickness',1000)}],
        'wavelength_um':[number('wavelength_min',1000),number('wavelength_max',1000)],
        'nfreq':int(number('wavelength_samples')), 'sampling':{'kind':'equal_wavelength'},
        'sources':[{'kind':'independent-semantic-intent','reference':intake['view']['input_sha256'],
            'note':intake['source_text']}, {'kind':'human-supplied-mapping-basis',
            'reference':options['mapping_source'].strip(),
            'note':'Explicitly reviewed units=1um, linear and Ex; requested wavelength grid preserved.'}],
        'intent_note':'Human-reviewed task draft; preserve original equal-wavelength demand. No interpolation.'}
    problem = task_problem(task)
    if problem: raise ValueError(problem['reason'])
    from .sampling import description
    record = {'schema_version':1,'semantic_input_sha256':intake['view']['input_sha256'],
        'semantic_result_sha256':digest(result),'native_task_sha256':digest(task),
        'original_request':intake['source_text'],'options':options,
        'sampling':description(task),'decimal_to_float_review':True,
        'task_approved':False,'solver_calls':0}
    context = {'background':options['background'],'goal':options['goal'],'role':options['role'],
        'materials':intake['source_text'],'parameter_source':options['mapping_source'],
        'unknowns':'All required task fields reviewed; script correctness is not yet known.'}
    return task, record, context
