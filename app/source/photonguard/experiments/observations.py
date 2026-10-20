"""Data-only, immutable one-dimensional observations; no implicit physical scale."""
import csv
import hashlib
import io
import itertools
import math
import re
from ..core import digest

MAX_BYTES = 2 * 1024 * 1024
UNITS = {'mm': 1., 'um': .001, 'm': 1000.}
SOURCE_KINDS = {'USER_PROVIDED', 'LICENSED_PUBLIC', 'SYNTHETIC_TEACHING'}


def parse_csv(text, *, position_unit=None, source_kind='USER_PROVIDED', source_name='', license_name=''):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('CSV 必须为 UTF-8 文本且不超过 2 MiB')
    if source_kind not in SOURCE_KINDS or not isinstance(source_name, str) or not 1 <= len(source_name.strip()) <= 300:
        raise ValueError('请明确数据来源类型和来源说明')
    if not isinstance(license_name,str) or len(license_name)>300:raise ValueError('许可说明必须为最多 300 字符的文本')
    if source_kind == 'LICENSED_PUBLIC' and not license_name.strip():
        raise ValueError('公开数据需填写许可或授权说明')
    from ..workflow_model import wire
    if wire.credential_risk([text, source_name, license_name]):
        raise ValueError('数据或来源说明含疑似密钥，请移除')
    try:rows = list(itertools.islice(csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True),5002))
    except csv.Error:raise ValueError('CSV 引号、字段长度或行结构无效；未清洗原始数据') from None
    if not rows or len(rows[0]) != 2 or rows[0][1].strip() != 'intensity_relative':
        raise ValueError('仅接受两列：position_mm（或 position_um / position_m / pixel / position）和 intensity_relative')
    header = [s.strip() for s in rows[0]]
    named = {'position_mm':'mm', 'position_um':'um', 'position_m':'m', 'pixel':'pixel', 'position':None}
    if header[0] not in named:
        raise ValueError('位置列名称不支持；请明确两列及位置单位')
    unit = named[header[0]]
    if position_unit not in (None, '', 'mm', 'um', 'm', 'pixel'):
        raise ValueError('位置单位仅支持 mm、um、m 或 pixel')
    if unit and position_unit and position_unit != unit:
        raise ValueError('所选单位与 CSV 列名冲突；pixel 不能仅改标签变成长度')
    unit = unit or position_unit or None
    if not 20 <= len(rows) - 1 <= 5000:
        raise ValueError('CSV 需要 20–5000 行观测；不静默删除空行或异常行')
    pairs = []
    for row in rows[1:]:
        if len(row) != 2 or any(not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', s.strip()) for s in row):
            raise ValueError('CSV 含非数值、缺项或公式；没有执行或清洗任何单元格')
        values = list(map(float, row))
        if any(not math.isfinite(v) or abs(v) > 1e8 for v in values):
            raise ValueError('观测必须为有限且范围内的数值')
        pairs.append(values)
    x, y = map(list, zip(*pairs))
    if any(b <= a for a,b in zip(x,x[1:])):
        raise ValueError('位置坐标必须严格递增且不重复；请核对原始采集数据')
    value = {'schema':'photonguard.observations.v1', 'raw_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
             'columns':header,'position_unit':unit,'source_kind':source_kind,'source_name':source_name.strip(),
             'license':license_name or 'USER_DECLARED_LOCAL_USE',
             'position':x,'x_mm':[v*UNITS[unit] for v in x] if unit in UNITS else None,'intensity':y,
             'rows':len(x),'cleaning':'NONE; all rows retained; robust loss does not delete observations',
             'questions':[] if unit in UNITS else ['缺少物理长度刻度；不能从像素或未知单位报告 μm 缝距。']}
    value['sha256'] = digest(value)
    return value


def verify(dataset, raw):
    if hashlib.sha256(raw).hexdigest() != dataset['raw_sha256'] or digest({k:v for k,v in dataset.items() if k!='sha256'}) != dataset['sha256']:
        raise ValueError('原始数据或单位/来源记录发生变化，停止拟合与导出')


def preview(dataset):
    return {k:dataset[k] for k in ('sha256','raw_sha256','columns','position_unit','source_kind','source_name','license','rows','questions','cleaning')} | {
        'position_range':[dataset['position'][0],dataset['position'][-1]],
        'intensity_range':[min(dataset['intensity']),max(dataset['intensity'])],
        'first_rows':list(zip(dataset['position'][:8],dataset['intensity'][:8]))}
