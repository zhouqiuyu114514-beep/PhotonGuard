"""Outward L2 association of the actual saved E/H array and a frozen trial.

The record is a fixed periodic nearest-center piecewise constant function.
Exact rational intersection geometry partitions every trial triangle. Only
degree-three moments are needed for the cross term; trial mass is already
certified. Global phase is immaterial to an eigenspace association.
"""
from fractions import Fraction as F
from bisect import bisect_left,bisect_right
from math import comb
import numpy as np
from .interval_arithmetic import R,C,rational,stack_r,stack_c
from .strict_high_order_field import POWERS,VECTOR,SCALAR,combine,clip,rational_array,validate
from .selector_observable_bounds import sqrt_bounds
from . import higher_order_trace as high


def axis_partition(axis):
    centers=list(map(F,axis));n=len(centers)
    if n<2 or centers[0]<-2 or centers[-1]>=2 or any(a>=b for a,b in zip(centers,centers[1:])):raise ValueError('RECORD_COORDINATES')
    intervals=[]
    for i,x in enumerate(centers):
        lower=((centers[i-1] if i else centers[-1]-4)+x)/2
        upper=(x+(centers[i+1] if i+1<n else centers[0]+4))/2
        for offset in (-4,0,4):
            lo=max(F(-2),lower+offset);hi=min(F(2),upper+offset)
            if lo<hi:intervals.append((lo,hi,i))
    intervals.sort()
    if intervals[0][0]!=-2 or intervals[-1][1]!=2 or any(a[1]!=b[0] for a,b in zip(intervals,intervals[1:])):raise ValueError('PERIODIC_PARTITION')
    return [intervals[0][0]]+[x[1] for x in intervals],[x[2] for x in intervals]


def signed_area(p):
    return sum((x*yy-y*xx for (x,y),(xx,yy) in zip(p,p[1:]+p[:1])),F(0))/2


def intersections(vertices,xb,yb,xi,yi):
    """All positive-area reference polygons, with exact partition equality."""
    v=[[F(x) for x in row] for row in vertices];j0=[v[1][d]-v[0][d] for d in (0,1)];j1=[v[2][d]-v[0][d] for d in (0,1)]
    lo=[min(p[d] for p in v) for d in (0,1)];hi=[max(p[d] for p in v) for d in (0,1)]
    ix=range(max(0,bisect_right(xb,lo[0])-1),min(len(xi),bisect_left(xb,hi[0])))
    iy=range(max(0,bisect_right(yb,lo[1])-1),min(len(yi),bisect_left(yb,hi[1])))
    total=F(0);pieces=[]
    for i in ix:
        for j in iy:
            p=[(F(0),F(0)),(F(1),F(0)),(F(0),F(1))]
            for d,lower,upper in ((0,xb[i],xb[i+1]),(1,yb[j],yb[j+1])):
                p=clip(p,j0[d],j1[d],upper-v[0][d]);p=clip(p,-j0[d],-j1[d],v[0][d]-lower)
            area=signed_area(p)
            if area<0:raise ValueError('INTERSECTION_ORIENTATION')
            if area:
                total+=area;pieces.append((p,xi[i],yi[j]))
    if total!=F(1,2):raise ValueError('RECORD_PARTITION_NOT_EXACT')
    return pieces


def polygon_moments(polygons):
    """Outward vectorized Green moments of exact rational polygons."""
    n=max(map(len,polygons));values=[p+[p[-1]]*(n-len(p)) for p in polygons]
    v=rational_array(values);x,y=v[:,:,0],v[:,:,1]
    order=list(range(1,n))+[0];dx=v[:,order,0]-x;dy=v[:,order,1]-y
    def powers(z):
        p=[R(np.ones(z.lo.shape))]
        for _ in range(4):p.append(p[-1]*z)
        return p
    px,py,pdx,pdy=map(powers,(x,y,dx,dy));moments=[]
    for a,b in POWERS:
        value=R(np.zeros(x.lo.shape))
        for i in range(a+2):
            for j in range(b+1):
                coefficient=rational(F(comb(a+1,i)*comb(b,j),(a+1)*(i+j+1)))
                value=value+coefficient*px[a+1-i]*pdx[i]*py[b-j]*pdy[j]*dy
        moments.append(value.sum(axis=1))
    return stack_r(moments,axis=1)


def physical_polynomials(data,coeff,batch=128):
    ids,sign,_=high.topology(data);fields=[];dets=[]
    for start in range(0,len(ids),batch):
        stop=min(start+batch,len(ids));v=R(data['vertices'][data['triangles'][start:stop]])
        j00=v[:,1,0]-v[:,0,0];j10=v[:,1,1]-v[:,0,1];j01=v[:,2,0]-v[:,0,0];j11=v[:,2,1]-v[:,0,1]
        det=j00*j11-j01*j10
        if np.any(det.lo<=0):raise ValueError('ORIENTATION')
        inv00,inv01,inv10,inv11=j11/det,-j01/det,-j10/det,j00/det
        local=C.point(coeff[ids[start:stop]])*sign[start:stop];polys=[]
        for kind in (0,1):
            a=combine(local[:,25*kind:25*kind+15],VECTOR[0]);b=combine(local[:,25*kind:25*kind+15],VECTOR[1])
            polys.extend((a*inv00[:,None]+b*inv10[:,None],a*inv01[:,None]+b*inv11[:,None],combine(local[:,25*kind+15:25*kind+25],SCALAR)))
        fields.append(stack_c(polys,axis=1));dets.append(det)
    def concatenate(items):return R(np.concatenate([a.lo for a in items]),np.concatenate([a.hi for a in items]))
    return C(concatenate([a.re for a in fields]),concatenate([a.im for a in fields])),concatenate(dets)


def integrate_record(data,coeff,model,record_path,logger=None):
    validate(data,model,coeff)
    with np.load(record_path,allow_pickle=False) as z:
        x=z['x_um'];y=z['y_um'];E=z['E'];H=z['H']
        if x.dtype!=np.float64 or y.dtype!=np.float64 or E.shape!=(320,320,1,3) or H.shape!=E.shape or E.dtype!=np.complex128 or H.dtype!=np.complex128:
            raise ValueError('ORIGINAL_RECORD_FORMAT')
        if not np.isfinite(E).all() or not np.isfinite(H).all():raise ValueError('FINITE_RECORD')
        raw=np.concatenate((E[:,:,0,:],H[:,:,0,:]),axis=2)
    xb,xi=axis_partition(x);yb,yi=axis_partition(y);polys,det=physical_polynomials(data,coeff)
    cross=C.point(0j);record_mass=R(0);area=R(0);partitions=0;pending=[]
    def consume(pieces):
        polygons=[r[1] for r in pieces];tri=np.array([r[0] for r in pieces]);i=np.array([r[2] for r in pieces]);j=np.array([r[3] for r in pieces])
        moments=polygon_moments(polygons);weights=R(np.concatenate((data['epsilon'][tri],np.ones((len(tri),3))),axis=1))
        source=C.point(raw[i,j]);integral=(polys[tri]*moments[:,None,:]).sum(axis=2)*det[tri,None]
        overlap=(source.conj()*integral*weights).sum(axis=1).sum(axis=0)
        norm=(source.re*source.re+source.im*source.im)*weights
        piece_area=moments[:,0]*det[tri]
        return overlap,(norm.sum(axis=1)*piece_area).sum(),piece_area.sum()
    for ti,triangle in enumerate(data['triangles']):
        parts=intersections(data['vertices'][triangle],xb,yb,xi,yi);partitions+=1
        pending.extend((ti,p,i,j) for p,i,j in parts)
        if len(pending)>=1024 or ti+1==len(data['triangles']):
            overlap,norm,a=consume(pending);cross=cross+overlap;record_mass=record_mass+norm;area=area+a;pending=[]
        if logger is not None and (ti+1)%1280==0:logger({'record_triangles':ti+1,'total_triangles':len(data['triangles'])})
    if record_mass.lo<=0 or not np.isfinite([record_mass.lo,record_mass.hi,cross.re.lo,cross.re.hi,cross.im.lo,cross.im.hi]).all():raise ValueError('INVALID_RECORD_INTEGRAL')
    if not area.lo<=16<=area.hi:raise ValueError('DOMAIN_AREA')
    return {'record_mass':record_mass.export(),'cross_record_trial':cross.export(),'covered_area':area.export(),
        'exact_triangle_partition_equalities':partitions,'reconstruction':'Periodic nearest stored center, piecewise constant original E/H jointly; exact midpoint Voronoi boundaries',
        'unweighted_record_coordinates_used':True,'material':'Original continuous fitted piecewise epsilon, not the production pixel epsilon',
        'cross_polynomial_degree':3,'quadrature_used':False}


def distance_bound(integrals,trial_mass,eta):
    mr_lo,mr_hi=map(F,integrals['record_mass']);mt_lo,mt_hi=map(F,trial_mass);eta=F(eta)
    if min(mr_lo,mt_lo)<=0 or eta<0:raise ValueError('NORMALIZATION_DOMAIN')
    def minabs(pair):
        lo,hi=map(F,pair)
        if lo>hi:raise ValueError('REVERSED_COMPLEX_INTERVAL')
        return F(0) if lo<=0<=hi else min(abs(lo),abs(hi))
    cross=integrals['cross_record_trial'];magnitude=sqrt_bounds(minabs(cross['real'])**2+minabs(cross['imag'])**2)[0]
    denominator=sqrt_bounds(mr_hi*mt_hi)[1];overlap_lower=magnitude/denominator
    if not 0<=overlap_lower<=1:raise ValueError('CAUCHY_SCHWARZ_CONSISTENCY')
    delta=sqrt_bounds(2-2*overlap_lower)[1];total=delta+eta
    projection_lower=max(F(0),1-total**2/2)**2 if total<sqrt_bounds(F(2))[0] else F(0)
    return {'record_to_trial_distance_upper_exact':str(delta),'record_to_trial_distance_upper':float(delta),
        'uniform_trial_to_eigenstate_distance_upper_exact':str(eta),'record_to_eigenstate_distance_upper_exact':str(total),
        'record_to_eigenstate_distance_upper':float(total),'target_projection_mass_fraction_lower_exact':str(projection_lower),
        'target_projection_mass_fraction_lower':float(projection_lower),'preregistered_quarter_distance_passes':total<=F(1,4),
        'unique_dominant_rank_one_component':projection_lower>F(1,2),
        'scope':'Unique nearest normalized continuous eigenstate up to phase inside the certified simple-branch root tube; not an all-spectrum largest-neff claim'}
