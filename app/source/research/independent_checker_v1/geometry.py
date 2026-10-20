"""Independent periodic topology, fitted material, and rational clipping."""
from fractions import Fraction as F
from bisect import bisect_left,bisect_right
import numpy as np
from .reference import EDGES

def validate(data,coeff,model):
    v=data['vertices'];tr=data['triangles'];nodes=data['periodic_node_ids']
    if v.shape!=(6561,2) or v.dtype!=np.float64 or not np.isfinite(v).all():raise ValueError('VERTICES')
    if tr.shape!=(12800,3) or coeff.shape!=(384000,) or coeff.dtype!=np.complex128 or not np.isfinite(coeff).all():raise ValueError('FIELD_FORMAT')
    if model['boundary']!='periodic' or model['task']['numerics']['domain_um']!=[4,4] or model['transverse_bloch_k']!=[0,0] or model['relative_permeability']!=1:raise ValueError('FIXED_DOMAIN')
    coords=[tuple(map(F,p)) for p in v];periodic={};pair_ids={};incidence={};area=F(0)
    for i,p in enumerate(coords):
        point=tuple((a+2)%4 for a in p);n=int(nodes[i])
        if n in periodic and periodic[n]!=point:raise ValueError('PERIODIC_NODE')
        periodic[n]=point
    if len(periodic)!=6400 or len(set(periodic.values()))!=6400:raise ValueError('PERIODIC_NODE_COUNT')
    req=model['task']['requirements'];half=F(req['film_thickness_um'])/2;width=F(req['ridge_width_um'])/2;split=-half+F(req['slab_thickness_um'])
    epsilon=model['materials']['0.775']['laboratory_epsilon']
    if any(epsilon[i][j] for i in range(3) for j in range(3) if i!=j):raise ValueError('DIAGONAL_EPSILON')
    core=[]
    for t,vertices in enumerate(tr):
        p=[coords[i] for i in vertices];lo=[min(x[d] for x in p) for d in (0,1)];hi=[max(x[d] for x in p) for d in (0,1)]
        determinant=(p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[2][0]-p[0][0])*(p[1][1]-p[0][1])
        if determinant<=0:raise ValueError('ORIENTATION')
        area+=determinant/2
        for e,(a,b) in enumerate(EDGES):
            na,nb=int(nodes[vertices[a]]),int(nodes[vertices[b]]);key=tuple(sorted((na,nb)));sign=1 if na<nb else -1;eid=int(data['edge_ids'][t,e])
            if int(data['edge_signs'][t,e])!=sign:raise ValueError('EDGE_ORIENTATION')
            if tuple(data['global_edge_nodes'][eid])!=key:raise ValueError('EDGE_BINDING')
            if key in pair_ids and pair_ids[key]!=eid:raise ValueError('DUPLICATE_EDGE')
            pair_ids[key]=eid;incidence.setdefault(eid,[]).append(sign)
        bottom=hi[1]<=-half;ln=(-half<=lo[1] and hi[1]<=split) or (split<=lo[1] and hi[1]<=half and -width<=lo[0] and hi[0]<=width)
        air=lo[1]>=half or (lo[1]>=split and (hi[0]<=-width or lo[0]>=width))
        if not (bottom or ln or air):raise ValueError('MATERIAL_INTERFACE_CROSSING')
        weight=[epsilon[i][i] for i in range(3)] if ln else [model['bottom_epsilon'] if bottom else model['top_epsilon']]*3
        if not np.array_equal(data['epsilon'][t],weight):raise ValueError('MATERIAL_BINDING')
        core.append(-width<=lo[0] and hi[0]<=width and -half<=lo[1] and hi[1]<=half)
    if area!=16 or len(incidence)!=19200 or any(sorted(x)!=[-1,1] for x in incidence.values()):raise ValueError('PERIODIC_PAIRING_AREA')
    # Reconstruct the public DOF serialization, without importing its implementation.
    nt=len(tr);ne=len(incidence);nn=len(periodic);offset=3*ne+6*nt;nd=offset+nn+2*ne+nt
    ids=[];signs=[]
    for t,verts in enumerate(tr):
        row=[];sign=[]
        for e in range(3):
            ei=int(data['edge_ids'][t,e]);orientation=int(data['edge_signs'][t,e])
            row.extend(3*ei+j for j in range(3));sign.extend((orientation,1,orientation))
        row.extend(3*ne+6*t+j for j in range(6));sign.extend([1]*6)
        row.extend(offset+int(nodes[i]) for i in verts);sign.extend([1]*3)
        for e in range(3):
            ei=int(data['edge_ids'][t,e]);order=(0,1) if data['edge_signs'][t,e]>0 else (1,0)
            row.extend(offset+nn+2*ei+j for j in order);sign.extend([1,1])
        row.append(offset+nn+2*ne+t);sign.append(1)
        ids.append(row+[x+nd for x in row]);signs.append(sign*2)
    return np.array(ids),np.array(signs),np.array(core),{'triangles':nt,'paired_edges':ne,'periodic_nodes':nn,'area_exact':str(area),'tangential_trace':'Exact edge moment unisolvence, reversal (-,+,-), and shared periodic DOFs; P3 shared endpoint and edge-node traces'}

def cut(poly,a,b,c):
    if not poly:return []
    result=[];previous=poly[-1];previous_value=a*previous[0]+b*previous[1]-c
    for point in poly:
        value=a*point[0]+b*point[1]-c
        if (value<=0)!=(previous_value<=0):
            ratio=previous_value/(previous_value-value)
            result.append(tuple(previous[d]+ratio*(point[d]-previous[d]) for d in (0,1)))
        if value<=0:result.append(point)
        previous,previous_value=point,value
    clean=[]
    for p in result:
        if not clean or p!=clean[-1]:clean.append(p)
    if len(clean)>1 and clean[0]==clean[-1]:clean.pop()
    return clean

def fan(poly):
    out=[]
    for i in range(1,len(poly)-1):
        a,b,c=poly[0],poly[i],poly[i+1]
        d=(b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1])
        if d<0:raise ValueError('CLIP_ORIENTATION')
        if d:out.append((a,b,c))
    return out

def box(vertices,xlo,xhi,ylo,yhi):
    p=[tuple(map(F,row)) for row in vertices];poly=[(F(0),F(0)),(F(1),F(0)),(F(0),F(1))]
    for d,lo,hi in ((0,xlo,xhi),(1,ylo,yhi)):
        a=p[1][d]-p[0][d];b=p[2][d]-p[0][d]
        poly=cut(poly,a,b,hi-p[0][d]);poly=cut(poly,-a,-b,p[0][d]-lo)
    return fan(poly)

def area(tri):
    a,b,c=tri
    return ((b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]))/2

def axis_partition(axis):
    a=list(map(F,axis))
    if len(a)!=320 or a[0]!=-2 or any(x>=y for x,y in zip(a,a[1:])) or a[-1]>=2:raise ValueError('RECORD_COORDINATES')
    cells=[]
    for i,x in enumerate(a):
        left=(x+(a[i-1] if i else a[-1]-4))/2;right=(x+(a[i+1] if i<319 else a[0]+4))/2
        for shift in (-4,0,4):
            lo=max(F(-2),left+shift);hi=min(F(2),right+shift)
            if lo<hi:cells.append((lo,hi,i))
    cells.sort()
    if cells[0][0]!=-2 or cells[-1][1]!=2 or any(a[1]!=b[0] for a,b in zip(cells,cells[1:])):raise ValueError('RECORD_PARTITION')
    return [cells[0][0]]+[c[1] for c in cells],[c[2] for c in cells]

def pixel_triangles(vertices,xb,xi,yb,yi):
    v=[tuple(map(F,row)) for row in vertices];lo=[min(p[d] for p in v) for d in (0,1)];hi=[max(p[d] for p in v) for d in (0,1)]
    result=[];total=F(0)
    for i in range(max(0,bisect_right(xb,lo[0])-1),min(len(xi),bisect_left(xb,hi[0]))):
        for j in range(max(0,bisect_right(yb,lo[1])-1),min(len(yi),bisect_left(yb,hi[1]))):
            for triangle in box(v,xb[i],xb[i+1],yb[j],yb[j+1]):
                total+=area(triangle);result.append((triangle,xi[i],yi[j]))
    if total!=F(1,2):raise ValueError('PIXEL_EXACT_PARTITION')
    return result
