"""Additional exact cover and adversarial checks; no field integration."""
from fractions import Fraction as F
import numpy as np
from .reference import MOMENT,DUAL

def tensor_cover(data,model):
    vertices=data['vertices'];grid=vertices.reshape(81,81,2);x=grid[:,0,0];y=grid[0,:,1]
    if not np.array_equal(grid[:,:,0],np.broadcast_to(x[:,None],(81,81))) or not np.array_equal(grid[:,:,1],np.broadcast_to(y[None,:],(81,81))):raise ValueError('NON_TENSOR_GRID')
    if x[0]!=-2 or x[-1]!=2 or y[0]!=-2 or y[-1]!=2 or np.any(np.diff(x)<=0) or np.any(np.diff(y)<=0):raise ValueError('TENSOR_DOMAIN')
    expected=[]
    for half in (0,1):
        for i in range(80):
            for j in range(80):
                a=i*81+j;b=(i+1)*81+j;c=b+1;d=a+1
                expected.append((a,b,c) if half==0 else (a,c,d))
    if not np.array_equal(data['triangles'],expected):raise ValueError('RECTANGULAR_COVER_TRIANGULATION')
    expected_nodes=[(i%80)*80+j%80 for i in range(81) for j in range(81)]
    if not np.array_equal(data['periodic_node_ids'],expected_nodes):raise ValueError('PERIODIC_SERIALIZATION')
    req=model['task']['requirements'];w=F(req['ridge_width_um'])/2;h=F(req['film_thickness_um'])/2;slab=F(req['slab_thickness_um'])-h
    if not {-w,w}<=set(map(F,x)) or not {-h,slab,h}<=set(map(F,y)):raise ValueError('FITTED_CORE_AND_MATERIAL_LINES')
    return {'status':'EXACT_TENSOR_COVER_PASS','cells':12800,'overlap_or_holes':False,'periodic_seams_exact':True,'core_and_material_fitted':True,'new_integrations':0}

def check_dual(dual=DUAL):
    if any(sum(MOMENT[i][k]*dual[k][j] for k in range(15))!=(i==j) for i in range(15) for j in range(15)):raise ValueError('MOMENT_DUAL_PARITY')
    return True
