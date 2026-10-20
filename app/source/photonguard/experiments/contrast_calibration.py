"""A single-frequency reference plus independent dark samples, never a PSF."""
import copy
import math
from ..core import digest
from .inverse_models import finite

TYPE='CONTRAST_AT_FREQUENCY'
POLICY={'version':'contrast-reference-v1','max_rows':201,'min_rows':8,'max_condition_number':1e6,
        'absolute_signal_floor':1e-8,'minimum_signal_to_noise':5.,'max_runs_per_root':2}


def validate(data):
    required={'frequency_per_mm','input_contrast','position_unit','x_mm','reference_intensity','dark_intensity',
              'reference','dark','linear_response','saturated','source_kind'}
    if not isinstance(data,dict) or set(data)!=required:raise ValueError('请提供参照、暗场、已知频率/对比度、物理坐标和采集配置')
    if not finite(data['frequency_per_mm']) or not 0<data['frequency_per_mm']<=1e6 or data['position_unit']!='mm':raise ValueError('频率和物理刻度需已知（每毫米、mm）')
    if not finite(data['input_contrast']) or not 0<data['input_contrast']<=1:raise ValueError('输入参照对比度必须已知且在 (0,1]')
    if data['linear_response'] is not True or data['saturated'] is not False:raise ValueError('非线性、饱和或未经声明的响应不能用于本校准')
    if data['source_kind'] not in ('USER_PROVIDED','SYNTHETIC_TEACHING'):raise ValueError('请明确资料来源')
    for key in ('reference','dark'):
        meta=data[key]
        if not isinstance(meta,dict) or set(meta)!={'capture_id','config_id','source'} or any(not isinstance(v,str) or not 1<=len(v.strip())<=300 for v in meta.values()):raise ValueError('参照和暗场都需独立采集标识、共同配置标识和来源')
    if data['reference']['capture_id']==data['dark']['capture_id'] or data['reference']['config_id']!=data['dark']['config_id']:raise ValueError('暗场须独立采集且配置与参照一致')
    for key in ('x_mm','reference_intensity','dark_intensity'):
        arr=data[key]
        if not isinstance(arr,list) or not POLICY['min_rows']<=len(arr)<=POLICY['max_rows'] or any(not finite(v) for v in arr):raise ValueError('每组需 8–201 个有限样本')
    if len(data['x_mm'])!=len(data['reference_intensity']) or any(b<=a for a,b in zip(data['x_mm'],data['x_mm'][1:])):raise ValueError('参照样本与递增物理坐标必须逐点对应')
    if any(abs(x)>1e6 for x in data['x_mm']):raise ValueError('物理坐标超出本有限校准范围')
    return copy.deepcopy(data)


def analyze(data):
    import numpy as np
    data=validate(data);x=np.asarray(data['x_mm']);y=np.asarray(data['reference_intensity']);dark=np.asarray(data['dark_intensity'])
    phase=2*np.pi*data['frequency_per_mm']*x;matrix=np.column_stack([np.ones(len(x)),np.cos(phase),np.sin(phase)])
    rank=int(np.linalg.matrix_rank(matrix));condition=float(np.linalg.cond(matrix))
    if rank!=3 or not math.isfinite(condition) or condition>POLICY['max_condition_number']:raise ValueError('频率与采样位置产生退化或病态设计，不能分离常数和正余弦分量')
    coef=np.linalg.lstsq(matrix,y,rcond=None)[0];pred=matrix@coef;rmse=float(np.sqrt(np.mean((pred-y)**2)))
    b=float(dark.mean());dark_sd=float(dark.std(ddof=1));dc=float(coef[0]-b)
    floor=max(POLICY['absolute_signal_floor'],POLICY['minimum_signal_to_noise']*max(rmse,dark_sd/math.sqrt(len(dark))))
    if dc<=floor:raise ValueError('去暗场后的平均信号近零或低于声明的信噪门槛，只能保留原资料')
    modulation=float(np.hypot(coef[1],coef[2]));h=modulation/(dc*data['input_contrast'])
    result={'type':TYPE,'status':'DESCRIPTIVE_ESTIMATE' if h<=1 else 'OUTSIDE_PASSIVE_RANGE_NEEDS_REVIEW',
        'frequency_per_mm':data['frequency_per_mm'],'estimated_contrast_transfer':h,'known_input_contrast':data['input_contrast'],
        'dark_mean':b,'reference_mean_minus_dark':dc,'fitted_coefficients':coef.tolist(),'reference_fit_rmse':rmse,
        'checks':{'rank':rank,'condition_number':condition,'signal_floor':floor,'linear_response':'DECLARED_TRUE',
            'saturation':'DECLARED_FALSE','configuration_match':True,'independent_capture_ids':True},
        'reference':data['reference'],'dark':data['dark'],'source_kind':data['source_kind'],
        'input_sha256':digest(data),'policy':POLICY,'resources':{'linear_reference_fits':1,'nonlinear_fits':0,'fft_calls':0},
        'scope':'仅对应已知单频参照的对比传递幅值；不是完整核、PSF、缝宽认证或置信区间。配置与线性来自资料声明。',
        'kernel_reconstruction':None,'confidence_interval':None,'raw_data_retained':True}
    result['id']=digest(result);return result


def teaching(seed=8101):
    """Independent synthetic observer. Analyzer receives samples, not kernel truth."""
    import numpy as np
    if type(seed) is not int or not 0<=seed<2**32:raise ValueError('教学种子无效')
    nu=1.;d=.1;h=math.cos(2*math.pi*nu*d)
    kernels=[{'offsets_mm':[-d,d],'weights':[.5,.5]},
             {'offsets_mm':[-.25,0.,.25],'weights':[(1-h)/2,h,(1-h)/2]}]
    x=np.linspace(-1.5,1.5,61);contrast=.8;phase=.3;gain=1.2;background=.07
    def observe(kernel):return background+gain*sum(w*(1+contrast*np.cos(2*np.pi*nu*(x-offset)+phase)) for offset,w in zip(kernel['offsets_mm'],kernel['weights']))
    first=observe(kernels[0]);second=observe(kernels[1]);rng=np.random.default_rng(seed)
    data={'frequency_per_mm':nu,'input_contrast':contrast,'position_unit':'mm','x_mm':x.tolist(),
          'reference_intensity':(first+rng.normal(0,.001,len(x))).tolist(),'dark_intensity':(background+rng.normal(0,.0005,24)).tolist(),
          'reference':{'capture_id':f'teaching-reference-{seed}','config_id':'reference-demo-linear-v1','source':'独立合成观察器：已知正弦参照'},
          'dark':{'capture_id':f'teaching-dark-{seed}','config_id':'reference-demo-linear-v1','source':'同配置独立合成暗场'},
          'linear_response':True,'saturated':False,'source_kind':'SYNTHETIC_TEACHING'}
    # Explanatory teaching evidence is kept outside the analyzer input.
    amplitude=gain*contrast*h;mean=background+gain
    lesson={'source_kind':'SYNTHETIC_TEACHING','known_teaching_transfer':h,'distinct_kernels':kernels,
        'maximum_noiseless_difference':float(np.max(np.abs(first-second))),
        'without_dark_equivalent_family':[{'assumed_background':b,'compatible_gain':mean-b,'compatible_transfer':amplitude/((mean-b)*contrast)} for b in (0.,.07,.2)],
        'explanation':'没有暗场时，多组背景、增益与传递率可产生相同单频曲线；独立暗场补足其中一项。两个不同核仍有相同单频传递，因此不能从本结果还原完整核。'}
    return data,lesson


def action(store,s,data):
    from ..workflow import WorkflowError,write_once
    from .observation_group import root_record
    if data['type']=='inverse_calibration_example':
        inputs,lesson=teaching();s['calibration_draft']={'inputs':inputs,'lesson':lesson,'status':'NOT_ANALYZED'}
        store.save(s);return s
    if data.get('approve') is not True:raise WorkflowError('请核对校准输入并单独批准小型线性计算')
    inputs=validate(data.get('inputs'));root=root_record(store,s);ledger=root['inverse_ledger']
    # Explicit bounded extension of the existing root, never reset old counters.
    ledger.setdefault('calibration_runs_reserved',0);ledger.setdefault('max_calibration_runs',POLICY['max_runs_per_root'])
    if ledger['calibration_runs_reserved']>=ledger['max_calibration_runs']:raise WorkflowError('本研究任务的两次小型校准额度已用完',409)
    ledger['calibration_runs_reserved']+=1;store.save(root)
    if root['id']==s['id']:s['revision']=root['revision']
    folder=store.folder(s['id'])/'calibrations'/str(ledger['calibration_runs_reserved']);folder.mkdir(parents=True,exist_ok=False)
    write_once(folder/'input.json',inputs)
    try:result=analyze(inputs)
    except ValueError as exc:
        failure={'status':'REJECTED','reason':str(exc),'input_sha256':digest(inputs)}
        write_once(folder/'result.json',failure);s['calibration_attempt']=failure;store.save(s);return s
    write_once(folder/'result.json',result)
    if s.get('contrast_calibration'):s.setdefault('calibration_history',[]).append(s['contrast_calibration'])
    s['contrast_calibration']=result|{'evidence_record_id':s['id'],'evidence_directory':folder.name}
    s['calibration_attempt']={'status':result['status'],'id':result['id']}
    store.save(s);store.event(s,'CONTRAST_CALIBRATION_COMPLETED',{'id':result['id'],'type':TYPE,'actor':'EXPLICIT_API_APPROVAL_NOT_HUMAN_CERTIFICATION'})
    return s


def verify(store,s):
    import json
    value=s.get('contrast_calibration')
    if not value:return
    from ..workflow import WorkflowError
    origin=value.get('evidence_record_id');directory=value.get('evidence_directory')
    if not isinstance(directory,str) or not directory.isdigit():raise WorkflowError('校准证据路径无效',409)
    folder=store.folder(origin)/'calibrations'/directory
    original=json.loads((folder/'result.json').read_text());inputs=json.loads((folder/'input.json').read_text())
    if original!={k:v for k,v in value.items() if k not in ('evidence_record_id','evidence_directory')} or original['id']!=digest({k:v for k,v in original.items() if k!='id'}) or digest(inputs)!=original['input_sha256']:raise WorkflowError('校准原资料或结果发生变化',409)
