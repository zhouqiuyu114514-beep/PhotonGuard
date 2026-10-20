"""Exact small-form continuation and conditional root-tube inequalities.

Counts, common DOFs, model and field integration must be independently bound
by the execution runner. These functions do not certify arbitrary caller data.
"""
from fractions import Fraction as F
from .fixed_s_rank_one import Interval,read_matrix,hermitian_overlap,witness
from .selector_observable_bounds import sqrt_bounds


def recombine_forms(first,last,s):
    s0,s1=F(first['parameter_s_exact']),F(last['parameter_s_exact']);s=F(s)
    if s0==s1 or first['wavelength_exact']!=last['wavelength_exact']:
        raise ValueError('PARAMETER_BINDING')
    t=(s-s0)/(s1-s0);result={'parameter_s_exact':str(s),'wavelength_exact':first['wavelength_exact']}
    g2=read_matrix(last['G2'])
    for key in ('mass','N','continuous_graph'):
        a,b=read_matrix(first[key]),read_matrix(last[key]);matrix=[]
        for i in range(3):
            row=[]
            for j in range(3):
                entry=[]
                for c in (0,1):
                    if key=='mass':
                        lo=max(a[i][j][c].lo,b[i][j][c].lo);hi=min(a[i][j][c].hi,b[i][j][c].hi)
                        value=Interval(lo,hi)
                    else:
                        value=a[i][j][c]*(1-t)+b[i][j][c]*t
                        if key=='continuous_graph':value=value-g2[i][j][c]*(t*(1-t)*(s1-s0)**2)
                    entry.append(value)
                row.append(tuple(entry))
            matrix.append(row)
        hermitian_overlap(matrix)
        result[key]={name:[[[str(matrix[i][j][c].lo if end==0 else matrix[i][j][c].hi) for j in range(3)] for i in range(3)] for end in (0,1)] for c,name in enumerate(('real','imag'))}
    result['scope']='Exact affine N and quadratic G identity on bound common trial DOFs; valid also for extrapolation'
    return result


def endpoint_temple(rayleigh,residual2,a,b):
    lo,hi=map(F,rayleigh);r2=F(residual2);a,b=F(a),F(b)
    if not a<lo<=hi<b or r2<0:raise ValueError('TEMPLE_GAP_OR_VARIANCE')
    return [lo-r2/(b-hi),hi+r2/(lo-a)]


def tube_bounds(endpoints,sc,h,a,b,lip):
    sc,h,a,b,lip=map(F,(sc,h,a,b,lip))
    if h<=0 or lip<=0 or sc-h<=F(209,100):raise ValueError('FROZEN_TUBE_GEOMETRY')
    ray=[list(map(F,x['true_rayleigh_interval'])) for x in endpoints]
    r2=[F(x['true_rayleigh_residual2_upper']) for x in endpoints]
    if len(ray)!=2:raise ValueError('TWO_ENDPOINTS_REQUIRED')
    aa=a+lip*h;bb=b-lip*h
    lo=min(v[0] for v in ray);hi=max(v[1] for v in ray)
    gap=min(lo-aa,bb-hi,lo)
    if gap<=0:raise ValueError('ROOT_TUBE_UNISOLATED')
    q=sqrt_bounds(max(r2))[1]/gap
    if q>=1:raise ValueError('ROOT_TUBE_PROJECTION_UNCERTIFIED')
    eta=sqrt_bounds(2-2*sqrt_bounds(1-q*q)[0])[1]
    derivative=[(ray[1][0]-ray[0][1])/(2*h),(ray[1][1]-ray[0][0])/(2*h)]
    lower_derivative=derivative[0]-2*lip*eta
    enclosures=[endpoint_temple(v,r,aa,bb) for v,r in zip(ray,r2)]
    target=1/F(.775);existence=enclosures[0][1]<target<enclosures[1][0]
    return {'status':'CONDITIONAL_ROOT_TUBE_BOUNDS','J_exact':list(map(str,(sc-h,sc+h))),
        'a_J_exact':str(aa),'b_J_exact':str(bb),'gap_lower_exact':str(gap),'gap_lower':float(gap),
        'q_upper_exact':str(q),'q_upper':float(q),'eta_upper_exact':str(eta),
        'trial_derivative_interval_exact':list(map(str,derivative)),
        'eigenvalue_derivative_lower_exact':str(lower_derivative),'eigenvalue_derivative_lower':float(lower_derivative),
        'endpoint_eigenvalue_enclosures_exact':[list(map(str,x)) for x in enclosures],
        'endpoint_eigenvalue_enclosures':[[float(y) for y in x] for x in enclosures],
        'root_existence_if_bound_inputs':existence,'root_uniqueness_if_bound_inputs':existence and lower_derivative>0,
        'true_rayleigh_required':True,'common_frozen_field_required':True,'counts_required':True}
