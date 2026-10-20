"""Radius observations with explicit width convention; no squared-radius fitting."""
import csv
import hashlib
import io
import itertools
import math
import re
from ..core import digest
from .observations import SOURCE_KINDS, MAX_BYTES

MODEL = 'gaussian_caustic_m2fixed1_v1'


def parse_csv(text, *, source_kind, source_name, license_name='', diameter_conversion=False):
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise ValueError('CSV 必须为 UTF-8 且不超过 2 MiB')
    if source_kind not in SOURCE_KINDS or not isinstance(source_name, str) or not 1 <= len(source_name.strip()) <= 300:
        raise ValueError('请明确数据来源')
    if not isinstance(license_name, str) or len(license_name) > 300 or source_kind == 'LICENSED_PUBLIC' and not license_name.strip():
        raise ValueError('请明确公开资料许可')
    from ..workflow_model import wire
    if wire.credential_risk([text, source_name, license_name]):raise ValueError('数据不能包含密钥')
    try:rows = list(itertools.islice(csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True), 5002))
    except csv.Error:raise ValueError('CSV 格式无效') from None
    header = [v.strip() for v in rows[0]] if rows else []
    diameter = len(header) >= 2 and header[1] == 'diameter_1e2_um'
    width = 'diameter_1e2_um' if diameter else 'radius_1e2_um'
    sd_name = 'diameter_sd_um' if diameter else 'radius_sd_um'
    if header not in (['z_mm', width], ['z_mm', width, sd_name]):
        raise ValueError('需要 z_mm,radius_1e2_um，可选 radius_sd_um；FWHM 或未知宽度定义须先核对')
    if diameter and diameter_conversion is not True:raise ValueError('直径输入需明确批准除以 2 转成 1/e² 半径（标准差同时转换）')
    if not 1 <= len(rows)-1 <= 5000:raise ValueError('数据需要 1–5000 行；单平面仅保存，不能唯一估计')
    values=[]
    for row in rows[1:]:
        if len(row)!=len(header) or any(not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', v.strip()) for v in row):raise ValueError('CSV 含缺项、公式或非数值')
        v=list(map(float,row))
        if any(not math.isfinite(a) or abs(a)>1e8 for a in v) or v[1]<=0 or len(v)==3 and v[2]<=0:raise ValueError('半径和标准差须为有限正数')
        values.append(v)
    z=[v[0] for v in values]
    if any(b<=a for a,b in zip(z,z[1:])):raise ValueError('z 坐标须严格递增；未删除任何观测')
    factor=.5 if diameter else 1.
    result={'schema':'photonguard.radius-observations.v1','raw_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'source_kind':source_kind,'source_name':source_name.strip(),'license':license_name or 'USER_DECLARED_LOCAL_USE',
            'columns':header,'rows':len(z),'x_mm':z,'radius_um':[v[1]*factor for v in values],
            'sd_um':[v[2]*factor for v in values] if len(header)==3 else None,
            'conversion':'EXPLICIT_DIAMETER_DIVIDE_TWO' if diameter else 'NONE',
            'width_definition':'intensity 1/e^2 radius','cleaning':'NONE; all original rows retained',
            'questions':['单平面半径对应一族束腰解，不能唯一估计 w0/z0'] if len(z)<3 else []}
    result['sha256']=digest(result);return result


def predict(z, w0_um, z0_mm, wavelength_nm):
    import numpy as np
    rayleigh_mm=np.pi*(w0_um*.001)**2/(wavelength_nm*1e-6)
    return w0_um*np.sqrt(1+((np.asarray(z)-z0_mm)/rayleigh_mm)**2)
