"""Zelmon 1997 Table 1, undoped congruent LN; fixed-temperature development model."""
import math
import numpy as np

MODEL_ID='zelmon1997-congruent-21C-v1'
SOURCE='https://doi.org/10.1364/JOSAB.14.003319'
COEFFICIENTS={'extraordinary':[2.9804,.02047,.5981,.0666,8.9543,416.08],
    'ordinary':[2.6734,.01764,1.2290,.05914,12.614,474.6]}
# Rows express laboratory x,y,z in crystal coordinates X,Y,Z.
XCUT_ROTATION=np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]])

def refractive_index(wavelength_um,axis,*,model_id=MODEL_ID,temperature_c=21,composition='undoped-congruent'):
    if model_id!=MODEL_ID or composition!='undoped-congruent' or type(temperature_c) not in (int,float) or temperature_c!=21:
        raise ValueError('材料组成/温度/模型不支持；不把未掺杂21℃公式用于MgO或温度扫描。')
    if type(wavelength_um) not in (int,float) or not math.isfinite(wavelength_um) or not .4<=wavelength_um<=5 or axis not in COEFFICIENTS:
        raise ValueError('材料波长需要0.4–5微米且晶轴明确。')
    q=wavelength_um*wavelength_um;a,b,c,d,e,f=COEFFICIENTS[axis]
    n2=1+a*q/(q-b)+c*q/(q-d)+e*q/(q-f)
    if n2<=0:raise ValueError('介电函数非正。')
    return math.sqrt(n2)

def dielectric_tensor(wavelength_um,rotation=None,**conditions):
    no=refractive_index(wavelength_um,'ordinary',**conditions)
    ne=refractive_index(wavelength_um,'extraordinary',**conditions)
    matrix=XCUT_ROTATION if rotation is None else np.asarray(rotation,dtype=float)
    if matrix.shape!=(3,3) or not np.all(np.isfinite(matrix)) or not np.allclose(matrix@matrix.T,np.eye(3),rtol=0,atol=1e-12) or not np.isclose(np.linalg.det(matrix),1,rtol=0,atol=1e-12):
        raise ValueError('晶轴旋转需要正交右手矩阵。')
    crystal=np.diag([no*no,no*no,ne*ne]);lab=matrix@crystal@matrix.T
    return {'model_id':MODEL_ID,'source':SOURCE,'temperature_c':21,'composition':'undoped-congruent',
        'wavelength_um':wavelength_um,'n_o':no,'n_e':ne,'crystal_epsilon':crystal.tolist(),
        'crystal_to_lab_rows':matrix.tolist(),'laboratory_epsilon':lab.tolist(),
        'coordinates':('lab x=crystal Z; lab y=crystal X; propagation lab z=crystal Y'
            if np.allclose(matrix,XCUT_ROTATION,rtol=0,atol=1e-12) else 'explicit proper rotation; consult crystal_to_lab_rows'),
        'material_frozen_at_this_wavelength':True,'native_dispersive_eigenproblem':False}
