"""Outward polynomial integrals for one frozen conforming k2/P3 field.

Binary64 DOFs/vertices/materials are interpreted exactly. No quadrature is
used: reference polynomial moments and clipped-polygon moments are rational.
This fixed-s subcertificate does not associate an original returned root.
"""
from fractions import Fraction as F
from math import factorial,comb
import numpy as np
from .interval_arithmetic import R,C,rational,stack_r,stack_c
from .pump_slab_envelope import pi_interval,applicable
from .selector_observable_bounds import sqrt_bounds
from .selector_cone_bounds import conditional_cone_bounds
from .projector_budget import bound as projector_bound
from .fixed_s_rank_one import complementary_gap
from . import higher_order_trace as high
from .conforming_trials import mesh


POWERS=high.powers(3);INDEX={v:i for i,v in enumerate(POWERS)}


def multiply_poly(a,b):
    result={}
    for (i,j),x in a.items():
        for (k,l),y in b.items():result[i+k,j+l]=result.get((i+k,j+l),F(0))+x*y
    return result


def polynomial_coefficients():
    vector=[[[F(0) for _ in range(15)] for _ in POWERS] for _ in range(2)]
    for raw,poly in enumerate(high.RAW):
        for (component,a,b),value in poly.items():
            for j in range(15):vector[component][INDEX[a,b]][j]+=value*high.DUAL_EXACT[raw][j]
    scalar=[[F(0) for _ in range(10)] for _ in POWERS]
    lambdas=[{(0,0):F(1),(1,0):F(-1),(0,1):F(-1)},{(1,0):F(1)},{(0,1):F(1)}]
    for j,alpha in enumerate(high.ALPHAS):
        poly={(0,0):F(1)}
        for i,count in enumerate(alpha):
            for s in range(count):
                factor={key:3*v/F(s+1) for key,v in lambdas[i].items()}
                factor[0,0]=factor.get((0,0),F(0))-F(s,s+1)
                poly=multiply_poly(poly,factor)
        for power,value in poly.items():scalar[INDEX[power]][j]=value
    return vector,scalar


VECTOR,SCALAR=polynomial_coefficients()


def clip(polygon,a,b,c):
    """Clip exact rational reference polygon by a*x+b*y<=c."""
    if not polygon:return []
    result=[]
    for p,q in zip(polygon,polygon[1:]+polygon[:1]):
        fp=a*p[0]+b*p[1]-c;fq=a*q[0]+b*q[1]-c
        if fp<=0:result.append(p)
        if (fp<0 and fq>0) or (fp>0 and fq<0):
            t=fp/(fp-fq);result.append((p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])))
    return result


def polygon_moment(polygon,a,b):
    # Green: integral x^a y^b = integral_boundary x^(a+1)y^b dy/(a+1).
    value=F(0)
    for (x,y),(xx,yy) in zip(polygon,polygon[1:]+polygon[:1]):
        dx=xx-x;dy=yy-y
        for i in range(a+2):
            for j in range(b+1):
                value+=F(comb(a+1,i)*comb(b,j), (a+1)*(i+j+1))*x**(a+1-i)*dx**i*y**(b-j)*dy**j*dy
    return value


def exact_reference_gram():
    return [[F(factorial(a+c)*factorial(b+d),factorial(a+b+c+d+2)) for c,d in POWERS] for a,b in POWERS]


GRAM=exact_reference_gram()


def rational_array(values):
    shape=np.shape(values);flat=[rational(x) for x in np.asarray(values,dtype=object).ravel()]
    return R(np.array([x.lo.item() for x in flat]).reshape(shape),np.array([x.hi.item() for x in flat]).reshape(shape))


def inside_box_gram(vertices,limit):
    values=[];cut_cells=0;full=rational_array(GRAM)
    for triangle in vertices:
        if np.all(abs(triangle)<=float(limit)):
            values.append(full);continue
        if any(np.min(triangle[:,axis])>=float(limit) or np.max(triangle[:,axis])<=-float(limit) for axis in (0,1)):
            values.append(R(np.zeros((10,10))));continue
        cut_cells+=1
        v=[[F(x) for x in row] for row in triangle];p=[(F(0),F(0)),(F(1),F(0)),(F(0),F(1))]
        for axis in (0,1):
            a=v[1][axis]-v[0][axis];b=v[2][axis]-v[0][axis]
            p=clip(p,a,b,limit-v[0][axis]);p=clip(p,-a,-b,limit+v[0][axis])
        moments={(a,b):polygon_moment(p,a,b) for a,b in high.powers(6)}
        values.append(rational_array([[moments[a+c,b+d] for c,d in POWERS] for a,b in POWERS]))
    return stack_r(values),cut_cells


def combine(dofs,matrix):
    polys=[]
    for row in matrix:
        terms=[dofs[:,j]*rational(c) for j,c in enumerate(row) if c]
        polys.append(stack_c(terms,axis=1).sum(axis=1) if terms else C.point(np.zeros(dofs.re.lo.shape[0],complex)))
    return stack_c(polys,axis=1)


def derivative(poly,axis):
    out=[]
    for a,b in POWERS:
        source=(a+1,b) if axis==0 else (a,b+1);factor=source[axis]
        out.append(poly[:,INDEX[source]]*factor if source in INDEX else C.point(np.zeros(poly.re.lo.shape[0],complex)))
    return stack_c(out,axis=1)


def inner(a,b,moments,det):
    products=a.re[:,:,None]*b.re[:,None,:]+a.im[:,:,None]*b.im[:,None,:]
    return (products*moments).sum(axis=2).sum(axis=1)*det


def validate(data,model,coeff):
    applicable(model);expected=mesh(model,20)
    for key in ('triangles','periodic_node_ids','edge_ids','edge_signs','global_edge_nodes','edge_first_local'):
        if not np.array_equal(data[key],expected[key]):raise ValueError('TOPOLOGY_BINDING:'+key)
    vertices=data['vertices']
    if vertices.dtype!=np.float64 or vertices.shape!=(6561,2) or not np.isfinite(vertices).all():raise ValueError('VERTEX_FORMAT')
    grid=vertices.reshape(81,81,2);x=grid[:,0,0];y=grid[0,:,1]
    if not np.all(grid[:,:,0]==x[:,None]) or not np.all(grid[:,:,1]==y[None,:]):raise ValueError('TENSOR_GEOMETRY')
    if x[0]!=-2 or x[-1]!=2 or y[0]!=-2 or y[-1]!=2 or np.any(np.diff(x)<=0) or np.any(np.diff(y)<=0):raise ValueError('PERIODIC_DOMAIN')
    req=model['task']['requirements'];a=F(req['film_thickness_um'])/2;w=F(req['ridge_width_um'])/2;split=-a+F(req['slab_thickness_um'])
    for axis,cuts in ((x,[-w,w]),(y,[-a,split,a])):
        if any(F(float(c))!=c or float(c) not in axis for c in cuts):raise ValueError('EXACT_INTERFACE_REQUIRED')
    eps=np.asarray(model['materials']['0.775']['laboratory_epsilon'])
    if not np.array_equal(eps,np.diag(np.diag(eps))) or min(np.diag(eps))<=0:raise ValueError('POSITIVE_DIAGONAL_EPSILON')
    v=vertices[data['triangles']];lo=v.min(axis=1);hi=v.max(axis=1)
    bottom=hi[:,1]<=float(-a);slab=(lo[:,1]>=float(-a))&(hi[:,1]<=float(split))
    cap=(lo[:,1]>=float(split))&(hi[:,1]<=float(a))&(lo[:,0]>=float(-w))&(hi[:,0]<=float(w))
    top=(lo[:,1]>=float(a))|((lo[:,1]>=float(split))&((hi[:,0]<=float(-w))|(lo[:,0]>=float(w))))
    if not np.all(bottom|slab|cap|top):raise ValueError('TRIANGLE_CROSSES_MATERIAL_INTERFACE')
    material=np.full((12800,3),model['top_epsilon'],float);material[bottom]=model['bottom_epsilon'];material[slab|cap]=np.diag(eps)
    if not np.array_equal(data['epsilon'],material):raise ValueError('PIECEWISE_MATERIAL_BINDING')
    if coeff.dtype!=np.complex128 or coeff.shape!=(384000,) or not np.isfinite(coeff).all():raise ValueError('DOF_FORMAT')
    core=(lo[:,0]>=float(-w))&(hi[:,0]<=float(w))&(lo[:,1]>=float(-a))&(hi[:,1]<=float(a))
    if np.any(~core & (hi[:,0]>float(-w))&(lo[:,0]<float(w))&(hi[:,1]>float(-a))&(lo[:,1]<float(a))):
        raise ValueError('CORE_MASK_NOT_EXACTLY_FITTED')
    return core


def integrate(data,coeff,model,rho,s=F(209,100),batch=128,logger=None):
    core=validate(data,model,coeff);ids,sign,nd=high.topology(data)
    rho=F(rho);k=rational(F(s)/F(.775));pl,ph=pi_interval();inverse_pi=1/(2*R(rational(pl).lo,rational(ph).hi))
    full=rational_array(GRAM);sums={key:R(0) for key in ('mass','electric','electric_L2','Ex','core','inner_box','residual2','N')};clipped=0
    for start in range(0,len(ids),batch):
        stop=min(start+batch,len(ids));vertices=data['vertices'][data['triangles'][start:stop]];v=R(vertices)
        j00=v[:,1,0]-v[:,0,0];j10=v[:,1,1]-v[:,0,1];j01=v[:,2,0]-v[:,0,0];j11=v[:,2,1]-v[:,0,1]
        det=j00*j11-j01*j10
        if np.any(det.lo<=0):raise ValueError('NONPOSITIVE_INTERVAL_DETERMINANT')
        inv00=j11/det;inv01=-j01/det;inv10=-j10/det;inv11=j00/det
        local=C.point(coeff[ids[start:stop]])*sign[start:stop];fields=[]
        for kind in (0,1):
            u=combine(local[:,25*kind:25*kind+15],VECTOR[0]);z=combine(local[:,25*kind:25*kind+15],VECTOR[1])
            fields.extend((u*inv00[:,None]+z*inv10[:,None],u*inv01[:,None]+z*inv11[:,None],combine(local[:,25*kind+15:25*kind+25],SCALAR)))
        dx=[derivative(f,0)*inv00[:,None]+derivative(f,1)*inv10[:,None] for f in fields]
        dy=[derivative(f,0)*inv01[:,None]+derivative(f,1)*inv11[:,None] for f in fields]
        action=[(dy[5]*inverse_pi).times_i()+fields[4]*k,-fields[3]*k-(dx[5]*inverse_pi).times_i(),
            ((dx[4]-dy[3])*inverse_pi).times_i(),-(dy[2]*inverse_pi).times_i()-fields[1]*k,
            fields[0]*k+(dx[2]*inverse_pi).times_i(),-((dx[1]-dy[0])*inverse_pi).times_i()]
        box,ncut=inside_box_gram(vertices,F(.45)*4);clipped+=ncut
        material=R(data['epsilon'][start:stop]);electric=R(np.zeros(stop-start))
        for component,(f,nf) in enumerate(zip(fields,action)):
            weight=material[:,component] if component<3 else R(np.ones(stop-start))
            norm=inner(f,f,full,det);sums['mass']=sums['mass']+(norm*weight).sum()
            residual=nf-f*(rational(rho)*weight[:,None])
            sums['residual2']=sums['residual2']+(inner(residual,residual,full,det)/weight).sum()
            sums['N']=sums['N']+inner(f,nf,full,det).sum()
            if component<3:
                electric=electric+norm*weight;sums['electric_L2']=sums['electric_L2']+norm.sum()
                sums['inner_box']=sums['inner_box']+(inner(f,f,box,det)*weight).sum()
                if component==0:sums['Ex']=sums['Ex']+norm.sum()
        sums['electric']=sums['electric']+electric.sum();sums['core']=sums['core']+(electric*core[start:stop]).sum()
        if logger is not None and (stop%1280==0 or stop==len(ids)):
            logger({'triangles_integrated':stop,'total_triangles':len(ids)})
    if any(not np.isfinite([v.lo.item(),v.hi.item()]).all() or v.lo>v.hi for v in sums.values()):raise ValueError('INVALID_INTERVAL')
    if sums['mass'].lo<=0 or sums['electric'].lo<=0 or sums['electric_L2'].lo<=0:raise ValueError('POSITIVE_NORMS_REQUIRED')
    sums['outer']=sums['electric']-sums['inner_box']
    sums['outer']=R(max(0,sums['outer'].lo.item()),max(0,sums['outer'].hi.item()))
    return sums,{'exact_clipped_triangles':clipped,'core_region':'exact fitted whole triangles','outer_region':'total electric energy minus exact rational clipped central-box integrals',
        'polynomial_degree':3,'integral_moment_degree':6,'quadrature_used':False,
        'basis':'exact reference moment dual and P3 nodal polynomials; covariant Piola with outward geometry',
        'numeric_assumptions':'IEEE binary64 nonoverflow outward-nextafter arithmetic, inherited package assumptions'}


def summarize(sums,rho,model,geometry_receipt):
    intervals={k:v.export() for k,v in sums.items()};mass=sums['mass'];el=sums['electric'];l2=sums['electric_L2']
    residual_upper=sqrt_bounds(F(sums['residual2'].hi.item())/F(mass.lo.item()))[1]
    a_lower=sqrt_bounds(F(el.lo.item())/F(mass.hi.item()))[0];gap=complementary_gap(rho);q=residual_upper/gap
    def ratio(num,den):
        value=num/den;return [max(F(0),F(value.lo.item())),min(F(1),F(value.hi.item()))]
    p=ratio(sums['Ex'],l2);c=ratio(sums['core'],el);o=ratio(sums['outer'],el)
    mean=el/l2;mean_bounds=[F(mean.lo.item()),F(mean.hi.item())]
    regions=[[[value if i==j else 0 for j in range(3)] for i in range(3)] for value in (model['top_epsilon'],model['bottom_epsilon'])]
    regions.append(model['materials']['0.775']['laboratory_epsilon']);epsmin=min(F(matrix[i][i]) for matrix in regions for i in range(3))
    gamma=sqrt_bounds(mean_bounds[1]/epsmin)[1]
    budget=projector_bound(q,a_lower);error=F(budget['electric_error_upper_exact'])
    selector=conditional_cone_bounds(p,c,o,error,gamma,epsilon_regions=regions,mean_epsilon=mean_bounds)
    passed=q<=F(139,1000) and a_lower>=F(7,10) and selector['strict_filters_would_pass_if_inputs_certified']
    return {'status':'FIXED_S_FIELD_SELECTOR_SUBCERTIFICATE' if passed else 'FIELD_ERROR_UNCERTIFIED',
        's_exact':'209/100','rho_exact':str(F(rho)),'normalization_and_integrals':intervals,
        'residual_upper_exact':str(residual_upper),'residual_upper':float(residual_upper),'gap_lower_exact':str(gap),
        'q_upper_exact':str(q),'q_upper':float(q),'electric_norm_lower_exact':str(a_lower),'electric_norm_lower':float(a_lower),
        'trial_observables_exact':{'Ex':list(map(str,p)),'core':list(map(str,c)),'outer':list(map(str,o)),'mean_epsilon':list(map(str,mean_bounds))},
        'projector_bound':budget,'selector_cone_propagation':selector,'geometry_receipt':geometry_receipt,
        'proof_scope':'Fixed-s rank3 eigenprojection only, inherits bound original continuous model and rank-one count evidence',
        'field_error_certified':passed,'fixed_s_selector_certified':passed,'C_entry_allowed':passed,
        'root_tube_certified':False,'original_returned_record_bound':False,'target_rank_status':'TARGET_MODE_RANK_UNBOUND',
        'QPM':'INCONCLUSIVE','design':'NOT_EVALUATED'}
