"""Independent reassembly checker. Never trusts a supplied 'verified' Boolean.

Running verify() performs TWO new local matrix assemblies (zero physical eigen
solves). Reproduction therefore needs its own explicit resource plan; stored JSON
matrix replay alone is an integrity check, not a new integration certificate.
"""
from fractions import Fraction as F
import numpy as np
from .pump_slab_envelope import applicable
from .conforming_trials import mesh,audit
from .interval_graph_matrix import assemble

def validate_trials(model,data):
    applicable(model)
    material=model['materials']['0.775']
    if material['wavelength_um']!=.775:raise ValueError('SH_WAVELENGTH_BINDING')
    eps=np.array(material['laboratory_epsilon'])
    if eps.shape!=(3,3) or not np.isfinite(eps).all() or not np.array_equal(eps,np.diag(np.diag(eps))) or np.any(np.diag(eps)<=0):raise ValueError('SH_POSITIVE_DIAGONAL_MATERIAL')
    expected=mesh(model,40)
    for key,value in expected.items():
        if key not in data or not np.array_equal(data[key],value):raise ValueError('MODEL_MESH_MATERIAL_BINDING:'+key)
    if data['edge_dofs'].shape!=(76800,2,3) or data['node_z_dofs'].shape!=(25600,2,3):raise ValueError('TRIAL_SPACE_DIMENSION')
    if data['edge_dofs'].dtype!=np.dtype('complex128') or data['node_z_dofs'].dtype!=np.dtype('complex128'):raise ValueError('TRIAL_DOF_PRECISION')
    return audit(data)

def verify(model,data):
    trace=validate_trials(model,data);wave=F(model['materials']['0.775']['wavelength_um'])
    low,_=assemble(data,wave,F(1,2));high,_=assemble(data,wave,F(209,100))
    passed=all(x['positive_definiteness']['positive_definite'] for x in (low,high))
    return {'status':'CONTINUOUS_LOW_SPECTRAL_COUNT_VERIFIED' if passed else 'WITNESS_INSUFFICIENT',
      'parameter_interval_exact':['1/2','209/100'],'frequency_interval_exact':['1/20',str(1/wave)],
      'minimum_positive_spectral_dimension':3 if passed else None,'common_trial_space':True,'trace':trace,
      'endpoints':[low,high],'matrix_concavity_verified_by_gram_structure':True,
      'theorem':'p(T)=(T-tau)-c(T-tau)^2 is nonpositive outside (tau,target). A positive 3D restriction forces a spectral projection of dimension>=3. R2=-c Gram(T1V) gives common-space concavity.',
      'target_mode_rank_bound':False,'target_neff_lower_bound_certified':False,
      'new_spatial_assemblies':2,'new_physical_eigensolves':0,'new_API_calls':0}
