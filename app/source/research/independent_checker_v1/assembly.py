"""Streaming Maxwell integrals from independently reconstructed polynomials."""
from fractions import Fraction as F
import numpy as np
from .dyadic import Q,Z,stack,zstack,pi_bounds
from .reference import VECTOR,SCALAR,P,BERN,GRAM,powers,triangle_moments
from .geometry import box,pixel_triangles,axis_partition

def combine(dofs,matrix):
    rows=[]
    for row in matrix:
        value=Z.point(np.zeros(dofs.re.lo.shape[0],complex))
        for j,c in enumerate(row):
            if c:value=value+dofs[:,j]*Q(c)
        rows.append(value)
    return zstack(rows,axis=1)

def physical(data,coeff,ids,sign,cells):
    v=Q(data['vertices'][data['triangles'][cells]])
    j00=v[:,1,0]-v[:,0,0];j10=v[:,1,1]-v[:,0,1];j01=v[:,2,0]-v[:,0,0];j11=v[:,2,1]-v[:,0,1]
    det=j00*j11-j01*j10
    if np.any(det.lo<=0):raise ValueError('INTERVAL_JACOBIAN')
    inv=(j11/det,-j01/det,-j10/det,j00/det)
    local=Z.point(coeff[ids[cells]]*sign[cells]);fields=[]
    for k in (0,25):
        a=combine(local[:,k:k+15],VECTOR[0]);b=combine(local[:,k:k+15],VECTOR[1])
        fields.extend((a*inv[0][:,None]+b*inv[2][:,None],a*inv[1][:,None]+b*inv[3][:,None],combine(local[:,k+15:k+25],SCALAR)))
    return fields,det,inv

def differentiate(p,axis):
    result=[]
    for a,b in P:
        src=(a+1,b) if axis==0 else (a,b+1)
        result.append(p[:,P.index(src)]*src[axis] if src in P else Z.point(np.zeros(p.re.lo.shape[0],complex)))
    return zstack(result,axis=1)

def real_inner(a,b,gram,det):
    value=((a.re[:,:,None]*b.re[:,None,:]+a.im[:,:,None]*b.im[:,None,:])*gram).sum(axis=2).sum(axis=1)
    return value*det

def clipped_grams(vertices):
    degree6=powers(6);full=[F(__import__('math').factorial(a)*__import__('math').factorial(b),__import__('math').factorial(a+b+2)) for a,b in degree6]
    moments=[];cuts=0;limit=F(.45)*4;pending=[];owners=[]
    for triangle in vertices:
        fans=box(triangle,-limit,limit,-limit,limit)
        if len(fans)==1 and fans[0]==((F(0),F(0)),(F(1),F(0)),(F(0),F(1))):moments.append(Q(full))
        elif fans:
            owners.append((len(moments),len(pending),len(fans)));pending.extend(fans)
            moments.append(None);cuts+=1
        else:moments.append(Q([0]*28))
    if pending:
        integrated=triangle_moments(pending,6)
        for i,begin,count in owners:moments[i]=integrated[begin:begin+count].sum(axis=0)
    m=stack(moments);index=np.array([[degree6.index((a+c,b+d)) for c,d in P] for a,b in P])
    return m[:,index],cuts

def endpoints(data,coeff,ids,sign,core,cells,parameters,shifts,progress=None,batch=64):
    sums=[{k:Q(0) for k in ('mass','electric','electric_L2','Ex','core','inner_box','residual2','N')} for _ in parameters]
    inverse_pi=1/(2*Q(*pi_bounds()));full=Q(GRAM);cut_count=0
    for start in range(0,len(cells),batch):
        group=np.array(cells[start:start+batch]);fields,det,inv=physical(data,coeff,ids,sign,group)
        dx=[differentiate(p,0)*inv[0][:,None]+differentiate(p,1)*inv[2][:,None] for p in fields]
        dy=[differentiate(p,0)*inv[1][:,None]+differentiate(p,1)*inv[3][:,None] for p in fields]
        bern=[combine(p,BERN) for p in fields]
        norms=[real_inner(p,p,full,det) for p in bern]
        boxgram,ncut=clipped_grams(data['vertices'][data['triangles'][group]]);cut_count+=ncut
        weights=Q(np.concatenate((data['epsilon'][group],np.ones((len(group),3))),axis=1))
        e=sum((norms[c]*weights[:,c] for c in range(3)),Q(np.zeros(len(group))))
        mass=(e+sum(norms[3:],Q(np.zeros(len(group))))).sum()
        el=e.sum();l2=sum((norms[c].sum() for c in range(3)),Q(0))
        inner=sum((real_inner(fields[c],fields[c],boxgram,det)*weights[:,c] for c in range(3)),Q(np.zeros(len(group)))).sum()
        common={'mass':mass,'electric':el,'electric_L2':l2,'Ex':norms[0].sum(),'core':(e*Q(core[group].astype(int))).sum(),'inner_box':inner}
        for values,s,sigma in zip(sums,parameters,shifts):
            k=Q(F(s)/F(.775))
            action=[(dy[5]*inverse_pi).times_i()+fields[4]*k,-fields[3]*k-(dx[5]*inverse_pi).times_i(),((dx[4]-dy[3])*inverse_pi).times_i(),
                -(dy[2]*inverse_pi).times_i()-fields[1]*k,fields[0]*k+(dx[2]*inverse_pi).times_i(),-((dx[1]-dy[0])*inverse_pi).times_i()]
            for name,value in common.items():values[name]=values[name]+value
            for c in range(6):
                nb=combine(action[c],BERN)
                residual=nb-bern[c]*(Q(sigma)*weights[:,c,None])
                values['residual2']=values['residual2']+(real_inner(residual,residual,full,det)/weights[:,c]).sum()
                values['N']=values['N']+real_inner(bern[c],nb,full,det).sum()
        if progress:progress('endpoint',min(start+batch,len(cells)),len(cells))
    result=[]
    for values,s,sigma in zip(sums,parameters,shifts):
        values['outer']=values['electric']-values['inner_box']
        result.append({'s_exact':str(s),'arbitrary_residual_shift_exact':str(sigma),'integrals':{k:v.export() for k,v in values.items()},'geometry':{'clipped_triangles':cut_count,'method':'Bernstein mass and fan-triangulated barycentric moments; integer outward endpoints','triangles':len(cells)}})
    return result

def record(data,coeff,ids,sign,cells,record_path,progress=None,batch=24):
    with np.load(record_path,allow_pickle=False) as z:
        E=z['E'];H=z['H'];x=z['x_um'];y=z['y_um']
    if E.shape!=(320,320,1,3) or H.shape!=E.shape or E.dtype!=np.complex128 or H.dtype!=np.complex128 or not np.isfinite(E).all() or not np.isfinite(H).all():raise ValueError('RECORD_FIELD_FORMAT')
    raw=np.concatenate((E[:,:,0,:],H[:,:,0,:]),axis=2);xb,xi=axis_partition(x);yb,yi=axis_partition(y)
    mass=Q(0);cross=Z(0);covered=Q(0);fans_total=0
    for start in range(0,len(cells),batch):
        group=np.array(cells[start:start+batch]);fields,det,_=physical(data,coeff,ids,sign,group);pending=[]
        for local,t in enumerate(group):
            pending.extend((local,triangle,i,j) for triangle,i,j in pixel_triangles(data['vertices'][data['triangles'][t]],xb,xi,yb,yi))
        fans_total+=len(pending)
        for begin in range(0,len(pending),1024):
            pieces=pending[begin:begin+1024];local=np.array([p[0] for p in pieces]);i=np.array([p[2] for p in pieces]);j=np.array([p[3] for p in pieces])
            moments=triangle_moments([p[1] for p in pieces],3);piece_area=moments[:,0]*det[local]
            weights=Q(np.concatenate((data['epsilon'][group[local]],np.ones((len(pieces),3))),axis=1))
            stored=Z.point(raw[i,j]);norm=Q(np.zeros(len(pieces)))
            for c in range(6):
                integral=(fields[c][local]*moments).sum(axis=1)*det[local]
                cross=cross+(stored[:,c].conj()*integral*weights[:,c]).sum()
                norm=norm+(stored.re[:,c]*stored.re[:,c]+stored.im[:,c]*stored.im[:,c])*weights[:,c]
            mass=mass+(norm*piece_area).sum();covered=covered+piece_area.sum()
        if progress:progress('record',min(start+batch,len(cells)),len(cells))
    return {'record_mass':mass.export(),'cross_record_trial':cross.export(),'covered_area':covered.export(),
        'exact_triangle_partition_equalities':len(cells),'fan_triangles':fans_total,'method':'Exact rational clipping, fan triangulation and barycentric moments; no Green formula',
        'reconstruction':'Original E/H jointly, periodic nearest stored center with exact midpoint cells'}
