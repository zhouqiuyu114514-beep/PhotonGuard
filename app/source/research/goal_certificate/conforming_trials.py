"""Freeze global oriented Nedelec edge and periodic P1 node trial DOFs."""
import numpy as np
from fractions import Fraction as F

EDGES=((0,1),(1,2),(2,0))

def mesh(model,r=40,slab_calibration=False):
    n=4*r;x=np.linspace(-2,2,n+1);y=x.copy()
    req=model['task']['requirements'];a=F(req['film_thickness_um'])/2;w=F(req['ridge_width_um'])/2
    split=-a+F(req['slab_thickness_um'])
    interfaces_y=[-a,split,a] if not slab_calibration else [F(-1,2),F(1,2)]
    interfaces_x=[-w,w] if not slab_calibration else []
    for axis,interfaces in ((x,interfaces_x),(y,interfaces_y)):
        for interface in interfaces:
            v=float(interface)
            if F(v)!=interface:raise ValueError('INTERFACE_NOT_EXACTLY_REPRESENTABLE')
            j=int(np.argmin(abs(axis-v)));assert abs(axis[j]-v)<.51/r;axis[j]=v
    X,Y=np.meshgrid(x,y,indexing='ij');vertices=np.stack([X.ravel(),Y.ravel()],axis=1)
    i,j=np.meshgrid(np.arange(n),np.arange(n),indexing='ij');a0=(i*(n+1)+j).ravel();b=a0+n+1;c=b+1;d=a0+1
    tri=np.concatenate([np.stack([a0,b,c],1),np.stack([a0,c,d],1)])
    ii,jj=np.meshgrid(np.arange(n+1),np.arange(n+1),indexing='ij');node_id=((ii%n)*n+jj%n).ravel()
    pair=np.stack([node_id[tri[:,[i,j]]] for i,j in EDGES],axis=1)
    signs=np.where(pair[:,:,0]<pair[:,:,1],1,-1)
    keys=np.sort(pair,axis=-1).reshape(-1,2)
    unique,first,inverse=np.unique(keys,axis=0,return_index=True,return_inverse=True)
    edge_id=inverse.reshape(-1,3)
    assert np.all(np.bincount(inverse)==2) and np.all(np.bincount(inverse,weights=signs.ravel())==0)
    assert np.all(np.diff(x)>0) and np.all(np.diff(y)>0)
    center=vertices[tri].mean(axis=1);cx,cy=center.T
    eps=np.ones((len(tri),3))*model['top_epsilon']
    if slab_calibration:
        eps[:]=1;eps[abs(cy)<.5]=4
    else:
        eps[cy<float(-a)]=model['bottom_epsilon']
        core=((cy>float(-a))&(cy<float(split)))|((cy>float(split))&(cy<float(a))&(abs(cx)<float(w)))
        eps[core]=np.diag(model['materials']['0.775']['laboratory_epsilon'])
    # Every physical horizontal/vertical interface is a grid line. Thus no cell
    # interior is cut; centroid classification cannot replace this check.
    assert all(float(v) in y for v in interfaces_y) and all(float(v) in x for v in interfaces_x)
    return {'vertices':vertices,'triangles':tri,'periodic_node_ids':node_id,'edge_ids':edge_id,'edge_signs':signs,
            'global_edge_nodes':unique,'edge_first_local':first,'epsilon':eps,'r':np.array(r)}

def sample(a,p):
    n=a.shape[0];u=np.mod((p+2)/4*n,n);ij=np.floor(u).astype(int);f=u-ij
    i,j=ij[...,0],ij[...,1];fx,fy=f[...,0],f[...,1]
    return ((1-fx)*(1-fy))[...,None,None]*a[i,j]+(fx*(1-fy))[...,None,None]*a[(i+1)%n,j]+((1-fx)*fy)[...,None,None]*a[i,(j+1)%n]+(fx*fy)[...,None,None]*a[(i+1)%n,(j+1)%n]

def propose_from_fields(data,E,H,transform):
    v=data['vertices'][data['triangles']];first=data['edge_first_local'];ti,ei=first//3,first%3
    starts=np.empty((len(first),2));ends=starts.copy()
    for e,(i,j) in enumerate(EDGES):
        mask=ei==e;starts[mask]=v[ti[mask],i];ends[mask]=v[ti[mask],j]
    sign=data['edge_signs'].ravel()[first];vector=(ends-starts)*sign[:,None]
    n=4*int(data['r']);vertices=data['vertices'].reshape(n+1,n+1,2)[:n,:n].reshape(-1,2)
    edges=[];nodes=[]
    for kind,field in enumerate((E,H)):
        proposed=(sample(field,starts)+4*sample(field,(starts+ends)/2)+sample(field,ends))/6
        edge=np.einsum('ecm,ec->em',proposed[:,:2,:],vector)
        W=transform[4*kind:4*kind+4]
        edges.append(edge@W);nodes.append(sample(field,vertices)[:,2,:]@W)
    data.update(edge_dofs=np.stack(edges,axis=1),node_z_dofs=np.stack(nodes,axis=1))
    return data

def propose_analytic(data,field,dimension):
    v=data['vertices'][data['triangles']];first=data['edge_first_local'];ti,ei=first//3,first%3
    starts=np.empty((len(first),2));ends=starts.copy()
    for e,(i,j) in enumerate(EDGES):
        mask=ei==e;starts[mask]=v[ti[mask],i];ends[mask]=v[ti[mask],j]
    vector=(ends-starts)*data['edge_signs'].ravel()[first,None]
    n=4*int(data['r']);nodes=data['vertices'].reshape(n+1,n+1,2)[:n,:n].reshape(-1,2)
    # Proposal interpolation may round; each shared resulting coefficient is
    # then treated exactly. No interpolated field is itself a certificate.
    values=(field(starts)+4*field((starts+ends)/2)+field(ends))/6
    edge=np.einsum('ekcm,ec->ekm',values[:,:,:2,:],vector)
    data.update(edge_dofs=edge,node_z_dofs=field(nodes)[:,:,2,:])
    return data

def audit(data):
    tri=data['triangles'];ids=data['periodic_node_ids'];pairs=np.stack([ids[tri[:,[i,j]]] for i,j in EDGES],axis=1)
    signs=np.where(pairs[:,:,0]<pairs[:,:,1],1,-1)
    assert np.array_equal(signs,data['edge_signs'])
    assert np.array_equal(np.sort(pairs,axis=-1),data['global_edge_nodes'][data['edge_ids']])
    assert np.all(np.bincount(data['edge_ids'].ravel())==2)
    assert np.all(np.bincount(data['edge_ids'].ravel(),weights=signs.ravel())==0)
    for key in ('edge_dofs','node_z_dofs'):assert np.isfinite(data[key]).all()
    # Shared node IDs/edge IDs ARE the exact equality constraints; no tolerance
    # is used to accept near-equal separately stored periodic traces.
    return {'status':'PASS','global_edges':len(data['global_edge_nodes']),'periodic_nodes':len(data['node_z_dofs']),
            'triangles':len(tri),'shared_oriented_edge_dofs_exact':True,'periodic_node_dofs_exact':True,
            'tangential_and_longitudinal_continuity':'By common global DOF topology and exact Nedelec/P1 shape polynomials; normal transverse components may jump'}
