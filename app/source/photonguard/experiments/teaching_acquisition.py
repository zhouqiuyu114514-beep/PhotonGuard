"""Separate frozen teaching object. Never receives fitted parameters or analyzer state."""
import hashlib
import io
import json
import secrets
from pathlib import Path
from ..core import digest
from ..workflow import atomic_json
from .inverse_models import SLIT, GAUSSIAN


def create(private_root, ident, model):
    import numpy as np
    folder=Path(private_root)/ident;folder.mkdir(parents=True,exist_ok=False)
    seed=secrets.randbits(32);rng=np.random.default_rng(seed)
    obj={'schema':'photonguard.frozen-teaching.v1','model':model,'seed':seed,'wavelength_nm':633.,
         'geometry':{'a':float(rng.uniform(17,25)),'d':float(rng.uniform(160,205)),'x0':float(rng.uniform(-.15,.15))} if model==SLIT else {'w0':float(rng.uniform(70,90)),'z0':float(rng.uniform(25,55))},
         'noise':.01 if model==SLIT else .5,'focal_length_mm':200.,'max_followups':2}
    atomic_json(folder/'object.json',obj)
    return {'commitment_sha256':digest(obj),'source_kind':'SYNTHETIC_TEACHING','note':'独立冻结教学对象；补采不读取拟合估计；同理想物理模型，非实测'}


def acquire(private_root, ident, commitment, *, model, acquisition_index, lower, upper, points, positions=None):
    import numpy as np
    obj=json.loads((Path(private_root)/ident/'object.json').read_text())
    if digest(obj)!=commitment or model!=obj['model']:raise ValueError('教学对象承诺不一致')
    if type(acquisition_index) is not int or not 0<=acquisition_index<=2 or type(points) is not int or not (20 if model==SLIT else 3)<=points<=201:raise ValueError('教学补采不超过两轮；双缝 20–201 点，高斯 3–201 点')
    if not isinstance(lower,(int,float)) or not isinstance(upper,(int,float)) or not np.isfinite([lower,upper]).all() or not lower<upper or max(abs(lower),abs(upper))>(10 if model==SLIT else 500):raise ValueError('教学扫描范围无效')
    x=np.linspace(lower,upper,points) if positions is None else np.asarray(positions,dtype=float)
    if x.ndim!=1 or len(x)!=points or not np.isfinite(x).all() or not np.all(np.diff(x)>0) or x[0]!=lower or x[-1]!=upper:raise ValueError('指定采样位置必须严格递增并符合已批准范围')
    rng=np.random.default_rng(obj['seed']+1009*acquisition_index);g=obj['geometry']
    if model==SLIT:
        q=(x-g['x0'])/(obj['wavelength_nm']*1e-6*obj['focal_length_mm']);u=np.pi*g['a']*.001*q
        envelope=np.ones(len(x));mask=u!=0;envelope[mask]=(np.sin(u[mask])/u[mask])**2
        y=(1.-.09*acquisition_index)*envelope*(1+np.cos(2*np.pi*g['d']*.001*q))/2+.04+.015*acquisition_index
        header='position_mm,intensity_relative'
    else:
        w=g['w0']*.001;y=1000*np.sqrt(w*w+((x-g['z0'])*obj['wavelength_nm']*1e-6/(np.pi*w))**2);header='z_mm,radius_1e2_um'
    y+=rng.normal(0,obj['noise'],len(x));out=io.StringIO();np.savetxt(out,np.column_stack([x,y]),delimiter=',',header=header,comments='')
    return out.getvalue()
