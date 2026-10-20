"""Declared observation/noise contracts; no calibration inferred from fitted data.

Kernel offsets are physical millimetres and weights are integrated nonnegative
quadrature masses.  Evaluation samples the analytic geometry at x-offset; it
never filters a sampled array or pads a finite measured scan.
"""
import copy
import math
from ..core import digest

LEGACY = 'EQUAL_DATASET_TRAINING_COUNT'
EQUAL_MSE = 'equal_dataset_mse'
INDEPENDENT = 'declared_independent_noise'
SOURCES = {'USER_DECLARED', 'INDEPENDENT_CALIBRATION', 'TEACHING_GENERATOR'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_observation(group, model):
    value = group.get('observation', {'kind': 'UNKNOWN'})
    if not isinstance(value, dict) or value.get('kind') not in {
        'UNKNOWN', 'POINT_SAMPLE', 'AVERAGING_UNKNOWN', 'CALIBRATED_INTENSITY_AVERAGE'
    }:
        raise ValueError('观测方式须为点采样、平均方式未知或已校准强度平均核')
    if value['kind'] != 'CALIBRATED_INTENSITY_AVERAGE':
        if set(value) != {'kind'}:
            raise ValueError('仅已校准平均方式允许提供观测核')
        return value
    if model != 'double_slit_width_spacing_v1' or set(value) != {'kind', 'kernel'}:
        raise ValueError('已校准强度平均核仅适用于当前双缝强度模型')
    kernel = value['kernel']
    if not isinstance(kernel, dict) or set(kernel) != {'offsets_mm', 'weights', 'source', 'reference'}:
        raise ValueError('核须明确物理偏移、归一权重、来源与校准参考')
    x, w = kernel['offsets_mm'], kernel['weights']
    if (not isinstance(x, list) or not isinstance(w, list) or not 1 <= len(x) <= 65
            or len(x) != len(w) or any(not finite(v) or abs(v) > 20 for v in x)
            or any(b <= a for a, b in zip(x, x[1:]))
            or any(not finite(v) or v < 0 for v in w) or abs(sum(w) - 1.) > 1e-12):
        raise ValueError('核需要 1–65 个递增物理坐标与非负归一积分权重；不自动归一或猜像素宽度')
    if not isinstance(kernel['source'],str) or kernel['source'] not in SOURCES or not isinstance(kernel['reference'], str) or not 1 <= len(kernel['reference'].strip()) <= 500:
        raise ValueError('须声明核的独立校准、用户输入或教学校准来源；拟合低残差不是校准')
    return value


def validate_noise(noise, rows, *, future=False):
    required = {'sigma', 'independent', 'source', 'reference'}
    if not future:
        required.add('acquisition_id')
    if not isinstance(noise, dict) or set(noise) != required:
        raise ValueError('独立噪声协议须明确 sigma、独立性、来源、参考和稳定观测 ID')
    if noise['independent'] is not True or not isinstance(noise['source'],str) or noise['source'] not in SOURCES:
        raise ValueError('独立性及噪声来源必须明确声明，不能由数值尺度推断')
    if not isinstance(noise['reference'], str) or not 1 <= len(noise['reference'].strip()) <= 500:
        raise ValueError('请提供噪声/独立性声明的参考说明')
    if not future and (not isinstance(noise['acquisition_id'], str) or not 1 <= len(noise['acquisition_id'].strip()) <= 160):
        raise ValueError('每次真实采集需要稳定观测 ID；拆文件不构成新采集')
    sigma = noise['sigma']
    values = sigma if isinstance(sigma, list) else [sigma]
    if isinstance(sigma, list) and len(sigma) != rows or any(not finite(v) or not 1e-9 <= v <= 1e6 for v in values):
        raise ValueError('sigma 必须为已声明正标准差，或与每个观测一一对应的数组')
    return noise


def validate_protocol(groups, settings):
    mode = settings.get('weighting')
    if mode not in (LEGACY, EQUAL_MSE, INDEPENDENT):
        raise ValueError('请选择每组均方误差等权或明确逐点独立噪声协议')
    units = 'STANDARDIZED_NOISE_SD' if mode == INDEPENDENT else 'SCALE_NORMALIZED_GROUP_RMS'
    if 'f_scale_units' in settings and settings['f_scale_units'] != units:
        raise ValueError('稳健尺度单位与残差协议不一致')
    if mode != LEGACY and settings.get('loss') == 'soft_l1' and settings.get('f_scale_units') != units:
        raise ValueError('切换稳健拟合协议须明确 f_scale_units，不能悄悄改变异常点折扣')
    if 'future_noise' in settings:
        noise = settings['future_noise'];sigma = noise.get('sigma') if isinstance(noise, dict) else None
        validate_noise(noise, len(sigma) if isinstance(sigma, list) else 1, future=True)
    seen_ids, seen_data = set(), set()
    for group in groups:
        validate_observation(group, settings['model'])
        noise = group.get('noise')
        if noise is not None:
            validate_noise(noise, group['dataset']['rows'])
            ident = noise['acquisition_id']
            if ident in seen_ids:
                raise ValueError('同一次观测的文件须先合并；不能通过拆文件新增信息或独立曝光参数')
            seen_ids.add(ident)
        if mode == INDEPENDENT:
            if noise is None or group.get('scale_source') != 'KNOWN_MEASUREMENT_SD':
                raise ValueError('独立噪声协议需要每组显式噪声和独立性声明，不自动将 scale 作为真实 sigma')
            ds = group['dataset']
            if ds.get('sd_um'):
                declared=noise['sigma'] if isinstance(noise['sigma'],list) else [noise['sigma']]*ds['rows']
                if any(not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12) for a,b in zip(declared,ds['sd_um'])):
                    raise ValueError('独立噪声声明与半径 CSV 的逐点标准差冲突；请先核对来源')
            fingerprint = digest({k: ds[k] for k in ('x_mm', 'intensity', 'radius_um') if k in ds})
            if fingerprint in seen_data:
                raise ValueError('复制同一份观测不能成为独立重复测量')
            seen_data.add(fingerprint)


def residual_divisor(group, mask, settings):
    """Same objective units for actual residuals and design Jacobians."""
    import numpy as np
    if settings['weighting'] == INDEPENDENT:
        sigma = group['noise']['sigma']
        return np.asarray(sigma)[mask] if isinstance(sigma, list) else sigma
    ds = group['dataset']
    scale = np.asarray(ds['sd_um'])[mask] if ds.get('sd_um') else group['scale']
    return scale * np.sqrt(mask.sum())


def protocol_description(settings):
    independent = settings['weighting'] == INDEPENDENT
    return {
        'mode': settings['weighting'],
        'residual_formula': '(prediction-observation)/declared_sigma_i' if independent else '(prediction-observation)/(declared_scale_i*sqrt(n_train_group))',
        'f_scale_units': 'STANDARDIZED_NOISE_SD' if independent else 'SCALE_NORMALIZED_GROUP_RMS',
        'scale_interpretation': ('声明独立噪声下的局部线性尺度；稳健损失仅用线性代理；不是置信区间'
                                 if independent else '每组均方误差目标的灵敏度尺度，不是独立采样 Fisher 方差；未作夹心方差估计'),
        'confidence_interval': None,
    }


def assessment(group):
    value = group.get('observation', {'kind': 'UNKNOWN'})
    calibrated = value['kind'] == 'CALIBRATED_INTENSITY_AVERAGE'
    return {'kind': value['kind'], 'calibrated_kernel_used': calibrated,
            'calibration_reference': value['kernel']['reference'] if calibrated else None,
            'status': 'DECLARED_CALIBRATION_APPLIED' if calibrated else 'OBSERVATION_ASSUMPTION_NOT_VERIFIED',
            'note': '低残差不能排除强度平均与幅度/背景混淆；已知强度核也不代表任意相干像差。'}


def merge_acquisition_fragments(groups, settings):
    """Explicit pre-import merger. Return fresh raw CSV plus canonical groups.

    The caller saves the returned CSV before importing. No existing store record
    is edited, no observations are dropped, and conflicting exposure/calibration
    metadata cannot be combined. Sorting restores the one acquisition's split.
    """
    from . import observations, gaussian_inference
    buckets = {}
    for index, group in enumerate(groups):
        if digest({k: v for k, v in group['dataset'].items() if k != 'sha256'}) != group['dataset']['sha256']:
            raise ValueError('分片数据哈希不一致')
        validate_observation(group, settings['model'])
        if group.get('noise') is None:
            buckets[('ungrouped', index)] = [group]
        else:
            validate_noise(group['noise'], group['dataset']['rows'])
            buckets.setdefault(('acquisition', group['noise']['acquisition_id']), []).append(group)
    merged, files = [], {}
    for fragments in buckets.values():
        if len(fragments) == 1:
            merged.append(copy.deepcopy(fragments[0]));continue
        first = fragments[0];slit = settings['model'] == 'double_slit_width_spacing_v1'
        def metadata(g):
            return {k: v for k, v in g.items() if k not in ('dataset', 'raw_file', 'noise', 'fragment_provenance')} | {
                'noise': {k: v for k, v in g['noise'].items() if k != 'sigma'},
                'source': {k: g['dataset'].get(k) for k in ('source_kind', 'source_name', 'license')}}
        if any(metadata(g) != metadata(first) for g in fragments):
            raise ValueError('同一观测分片的曝光、固定条件、校准或来源冲突，不能静默合并')
        records=[]
        for g in fragments:
            ds=g['dataset'];sigma=g['noise']['sigma'];values=ds['intensity'] if slit else ds['radius_um']
            for i,(x,y) in enumerate(zip(ds['x_mm'],values)):
                records.append((x,y,sigma[i] if isinstance(sigma,list) else sigma,ds.get('sd_um',[None]*len(values))[i] if ds.get('sd_um') else None))
        records.sort(key=lambda row:row[0])
        if any(a[0]>=b[0] for a,b in zip(records,records[1:])):
            raise ValueError('分片存在重复坐标/重复记录；不能把复制的数据当成新观测')
        include_sd=not slit and all(r[3] is not None for r in records)
        if not slit and any(r[3] is not None for r in records) and not include_sd:
            raise ValueError('半径分片标准差列不一致')
        header='position_mm,intensity_relative' if slit else 'z_mm,radius_1e2_um'+(',radius_sd_um' if include_sd else '')
        raw=header+'\n'+'\n'.join(','.join(repr(v) for v in ([r[0],r[1],r[3]] if include_sd else r[:2])) for r in records)+'\n'
        source={k:first['dataset'][k] for k in ('source_kind','source_name')};source['license_name']=first['dataset']['license']
        ds=observations.parse_csv(raw,**source) if slit else gaussian_inference.parse_csv(raw,**source)
        item=copy.deepcopy(first);item['dataset']=ds;item['raw_file']='merged-'+digest([g['dataset']['sha256'] for g in fragments])[:16]+'.csv'
        sigmas=[r[2] for r in records];item['noise']['sigma']=sigmas[0] if len(set(sigmas))==1 else sigmas
        item['fragment_provenance']=[{'dataset_sha256':g['dataset']['sha256'],'raw_sha256':g['dataset']['raw_sha256'],'raw_file':g['raw_file']} for g in fragments]
        files[item['raw_file']]=raw;merged.append(item)
    return {'groups':merged,'raw_csv_by_file':files}
