"""One frozen same-model corner-graded tensor mesh; no parameter sweep."""
from fractions import Fraction as F
import numpy as np
from .conforming_trials import mesh,EDGES
from .shared_trace_proposal import geometry,quadrature
from . import higher_order_trace as high


def segment(a,b,n,grading):
    t=np.linspace(0,1,n+1)
    if grading=='left':u=t*t
    elif grading=='right':u=1-(1-t)**2
    elif grading=='both':u=(1-np.cos(np.pi*t))/2
    else:raise ValueError('UNKNOWN_GRADING')
    values=float(a)+(float(b)-float(a))*u;values[0]=float(a);values[-1]=float(b)
    if np.any(np.diff(values)<=0):raise ValueError('STRICTLY_INCREASING_AXIS')
    return values


def graded_mesh(model):
    req=model['task']['requirements'];w=F(req['ridge_width_um'])/2;a=F(req['film_thickness_um'])/2
    split=-a+F(req['slab_thickness_um'])
    xs=[segment(-2,-w,20,'right'),segment(-w,w,40,'both'),segment(w,2,20,'left')]
    ys=[segment(-2,-a,28,'right'),segment(-a,split,12,'right'),segment(split,a,16,'both'),segment(a,2,24,'left')]
    x=np.concatenate([z[:-1] for z in xs]+[xs[-1][-1:]])
    y=np.concatenate([z[:-1] for z in ys]+[ys[-1][-1:]])
    X,Y=np.meshgrid(x,y,indexing='ij');data=mesh(model,20);data['vertices']=np.stack((X.ravel(),Y.ravel()),axis=1)
    centers=data['vertices'][data['triangles']].mean(axis=1);cx,cy=centers.T
    eps=np.full((len(centers),3),model['top_epsilon'],float);eps[cy<float(-a)]=model['bottom_epsilon']
    inside=((cy>float(-a))&(cy<float(split)))|((cy>float(split))&(cy<float(a))&(abs(cx)<float(w)))
    eps[inside]=np.diag(model['materials']['0.775']['laboratory_epsilon']);data['epsilon']=eps
    data['mesh_kind']=np.array('corner-graded-20261010-v1')
    return data


def field_from_coefficients(data,coeff):
    """Frozen piecewise polynomial reconstruction, preserving coordinate axes."""
    n=int(round(np.sqrt(len(data['triangles'])/2)));vertices=data['vertices'].reshape(n+1,n+1,2)
    x=vertices[:,0,0];y=vertices[0,:,1];ids,sign,nd=high.topology(data)
    def evaluate(points):
        shape=points.shape[:-1];p=np.mod(points.reshape(-1,2)+2,4)-2
        i=np.minimum(np.searchsorted(x,p[:,0],side='right')-1,n-1)
        j=np.minimum(np.searchsorted(y,p[:,1],side='right')-1,n-1)
        sx=(p[:,0]-x[i])/(x[i+1]-x[i]);sy=(p[:,1]-y[j])/(y[j+1]-y[j])
        upper=sx<sy;cell=i*n+j+upper*n*n
        bary=np.stack((1-sx,sx-sy,sy),axis=1)
        bary[upper]=np.stack((1-sy[upper],sx[upper],sy[upper]-sx[upper]),axis=1)
        v=data['vertices'][data['triangles'][cell]];jac=np.stack((v[:,1]-v[:,0],v[:,2]-v[:,0]),axis=2);inv=np.linalg.inv(jac)
        vec,curl,scalar,grad=high.reference(bary);local=coeff[ids[cell]]*sign[cell]
        value=np.zeros((len(p),6),complex)
        for kind in (0,1):
            ref=np.einsum('qci,qi->qc',vec,local[:,25*kind:25*kind+15])
            value[:,3*kind:3*kind+2]=np.einsum('qc,qcd->qd',ref,inv)
            value[:,3*kind+2]=np.einsum('qi,qi->q',scalar,local[:,25*kind+15:25*kind+25])
        return value.reshape(shape+(6,))
    return evaluate


def interpolate_high(data,field):
    ids,sign,nd=high.topology(data);nt=len(ids);local=np.zeros((nt,50),complex)
    bary,w=quadrature(4);t,ew=np.polynomial.legendre.leggauss(4);t=(t+1)/2;ew=ew/2
    for start in range(0,nt,64):
        stop=min(nt,start+64);v,jac,inv,det=geometry(data,start,stop)
        for edge,(i,j) in enumerate(EDGES):
            direction=v[:,j]-v[:,i];pts=v[:,i,None,:]+t[None,:,None]*direction[:,None,:]
            values=field(pts)
            for kind in (0,1):
                tangent=np.einsum('bqc,bc->bq',values[:,:,3*kind:3*kind+2],direction)
                for moment,leg in enumerate((np.ones(4),2*t-1,6*t*t-6*t+1)):
                    local[start:stop,25*kind+3*edge+moment]=np.sum(tangent*ew*leg,axis=1)
        pts=np.einsum('qi,bic->bqc',bary,v);value=field(pts)
        for kind in (0,1):
            pull=np.einsum('bqc,bcd->bqd',value[:,:,3*kind:3*kind+2],jac)
            for d in (0,1):
                for j,test in enumerate((np.ones(len(w)),bary[:,1],bary[:,2])):
                    local[start:stop,25*kind+9+3*d+j]=np.sum(pull[:,:,d]*w*test,axis=1)
        points=np.einsum('qi,bic->bqc',np.array(high.ALPHAS,float)/3,v);value=field(points)
        local[start:stop,15:25]=value[:,:,2];local[start:stop,40:50]=value[:,:,5]
    values=local*sign;count=np.bincount(ids.ravel(),minlength=nd)
    return (np.bincount(ids.ravel(),weights=values.real.ravel(),minlength=nd)+1j*np.bincount(ids.ravel(),weights=values.imag.ravel(),minlength=nd))/count
