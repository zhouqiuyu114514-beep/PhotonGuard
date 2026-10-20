"""Construct the moment dual and nodal basis directly from defining functionals."""
from fractions import Fraction as F
from math import factorial,comb
from functools import lru_cache
from .dyadic import Q,stack

def powers(n):return [(d-j,j) for d in range(n+1) for j in range(d+1)]
P=powers(3)
ALPHA=[(3,0,0),(0,3,0),(0,0,3),(2,1,0),(1,2,0),(0,2,1),(0,1,2),(1,0,2),(2,0,1),(1,1,1)]
EDGES=((0,1),(1,2),(2,0))

def inverse(A):
    n=len(A);work=[[F(x) for x in row]+[F(i==j) for j in range(n)] for i,row in enumerate(A)]
    for c in range(n):
        pivot=next(r for r in range(c,n) if work[r][c]);work[pivot],work[c]=work[c],work[pivot]
        scale=work[c][c];work[c]=[x/scale for x in work[c]]
        for r in range(n):
            if r!=c:
                scale=work[r][c]
                if scale:work[r]=[a-scale*b for a,b in zip(work[r],work[c])]
    assert all(work[i][j]==(i==j) for i in range(n) for j in range(n))
    return [row[n:] for row in work]

def basis():
    raw=[{(c,a,b):F(1)} for c in (0,1) for a,b in powers(2)]
    raw += [{(0,2-b,b+1):F(-1),(1,3-b,b):F(1)} for b in range(3)]
    vertices=((0,0),(1,0),(0,1));leg=((1,),(-1,2),(1,-6,6));rows=[]
    for u,v in EDGES:
        x,y=vertices[u];dx=vertices[v][0]-x;dy=vertices[v][1]-y
        for weight in leg:
            row=[]
            for poly in raw:
                total=F(0)
                for (c,a,b),coef in poly.items():
                    for i in range(a+1):
                        for j in range(b+1):
                            v=coef*(dx,dy)[c]*comb(a,i)*comb(b,j)*x**(a-i)*y**(b-j)*dx**i*dy**j
                            total+=v*sum((F(w,i+j+k+1) for k,w in enumerate(weight)),F(0))
                row.append(total)
            rows.append(row)
    for c in (0,1):
        for a,b in powers(1):
            rows.append([sum((z*F(factorial(i+a)*factorial(j+b),factorial(i+j+a+b+2)) for (d,i,j),z in p.items() if d==c),F(0)) for p in raw])
    dual=inverse(rows)
    vector=[[[sum((raw[k].get((c,a,b),0)*dual[k][j] for k in range(15)),F(0)) for j in range(15)] for a,b in P] for c in (0,1)]
    vandermonde=[[(F(alpha[1],3)**a)*(F(alpha[2],3)**b) for a,b in P] for alpha in ALPHA]
    scalar=inverse(vandermonde)
    return vector,scalar,rows,dual

VECTOR,SCALAR,MOMENT,DUAL=basis()

def falling(n,k):return factorial(n)//factorial(n-k) if n>=k else 0
BERN=[[F(falling(alpha[1],a)*falling(alpha[2],b),falling(3,a+b)) for a,b in P] for alpha in ALPHA]

def multi(alpha):return factorial(sum(alpha))//prod(factorial(v) for v in alpha)
def prod(xs):
    v=1
    for x in xs:v*=x
    return v
GRAM=[[F(multi(a)*multi(b),56*multi(tuple(x+y for x,y in zip(a,b)))) for b in ALPHA] for a in ALPHA]

def compositions(n):return [(a,b,n-a-b) for a in range(n+1) for b in range(n-a+1)]

@lru_cache(None)
def terms(i,j):
    return [(a,b,F(multi(a)*multi(b)*prod(factorial(x+y) for x,y in zip(a,b)),factorial(i+j+2))) for a in compositions(i) for b in compositions(j)]

def triangle_moments(triangles,degree):
    """Reference polygon fan triangles, integrated by barycentric Dirichlet moments.

    Integral lambda^alpha = det(J) * product(alpha!)/(sum(alpha)+2)!.
    The list contains positive triangles and no oriented-boundary formula.
    """
    v=Q(triangles);x=v[:,:,0];y=v[:,:,1]
    det=(x[:,1]-x[:,0])*(y[:,2]-y[:,0])-(x[:,2]-x[:,0])*(y[:,1]-y[:,0])
    xp=[Q([1]*len(triangles))];yp=[Q([1]*len(triangles))]
    # Cache each vertex-coordinate power; all finite precision steps are rounded.
    X=[[Q([1]*len(triangles))] for _ in range(3)];Y=[[Q([1]*len(triangles))] for _ in range(3)]
    for k in range(1,degree+1):
        for c in range(3):X[c].append(X[c][-1]*x[:,c]);Y[c].append(Y[c][-1]*y[:,c])
    result=[]
    for i,j in powers(degree):
        value=Q([0]*len(triangles))
        for a,b,coefficient in terms(i,j):
            term=Q(coefficient)
            for c in range(3):
                if a[c]:term=term*X[c][a[c]]
                if b[c]:term=term*Y[c][b[c]]
            value=value+term
        result.append(value*det)
    return stack(result,axis=1)
