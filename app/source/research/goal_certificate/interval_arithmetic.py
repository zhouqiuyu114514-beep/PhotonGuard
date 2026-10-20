"""Outward binary64 real/complex intervals for finite polynomial integrals."""
import numpy as np
from fractions import Fraction

def down(x):return np.nextafter(x,-np.inf)
def up(x):return np.nextafter(x,np.inf)

class R:
    def __init__(self,lo,hi=None):
        self.lo=np.asarray(lo,dtype=float);self.hi=np.asarray(lo if hi is None else hi,dtype=float)
    def __add__(self,b):
        b=real(b);return R(down(self.lo+b.lo),up(self.hi+b.hi))
    __radd__=__add__
    def __neg__(self):return R(-self.hi,-self.lo)
    def __sub__(self,b):return self+-real(b)
    def __rsub__(self,b):return real(b)+-self
    def __mul__(self,b):
        b=real(b);v=np.stack([self.lo*b.lo,self.lo*b.hi,self.hi*b.lo,self.hi*b.hi]);return R(down(v.min(axis=0)),up(v.max(axis=0)))
    __rmul__=__mul__
    def __truediv__(self,b):
        b=real(b)
        if np.any((b.lo<=0)&(b.hi>=0)):raise ValueError('INTERVAL_DIVISION_BY_ZERO')
        return self*R(down(1/b.hi),up(1/b.lo))
    def __rtruediv__(self,b):return real(b)/self
    def __getitem__(self,k):return R(self.lo[k],self.hi[k])
    def sum(self,axis=0):
        lo=np.moveaxis(self.lo,axis,0);hi=np.moveaxis(self.hi,axis,0)
        while len(lo)>1:
            n=len(lo)//2;c=R(lo[:2*n:2],hi[:2*n:2])+R(lo[1:2*n:2],hi[1:2*n:2])
            lo=np.concatenate([c.lo,lo[-1:]]) if len(lo)%2 else c.lo
            hi=np.concatenate([c.hi,hi[-1:]]) if len(hi)%2 else c.hi
        return R(lo[0],hi[0])
    def export(self):return [self.lo.tolist(),self.hi.tolist()]

def real(x):return x if isinstance(x,R) else R(x)
def rational(x):
    x=Fraction(x);f=float(x)
    return R(np.nextafter(f,-np.inf) if Fraction(f)>x else f,np.nextafter(f,np.inf) if Fraction(f)<x else f)

class C:
    def __init__(self,re,im=0):self.re=real(re);self.im=real(im)
    @classmethod
    def point(cls,x):return cls(np.real(x),np.imag(x))
    def __add__(self,b):
        b=complex_interval(b);return C(self.re+b.re,self.im+b.im)
    __radd__=__add__
    def __neg__(self):return C(-self.re,-self.im)
    def __sub__(self,b):return self+-complex_interval(b)
    def __rsub__(self,b):return complex_interval(b)+-self
    def __mul__(self,b):
        if isinstance(b,C):return C(self.re*b.re-self.im*b.im,self.re*b.im+self.im*b.re)
        return C(self.re*b,self.im*b)
    __rmul__=__mul__
    def __getitem__(self,k):return C(self.re[k],self.im[k])
    def conj(self):return C(self.re,-self.im)
    def sum(self,axis=0):return C(self.re.sum(axis),self.im.sum(axis))
    def times_i(self):return C(-self.im,self.re)
    def export(self):return {'real':self.re.export(),'imag':self.im.export()}

def complex_interval(x):
    if isinstance(x,C):return x
    if isinstance(x,R):return C(x,0)
    return C.point(x)

def stack_r(items,axis=0):return R(np.stack([x.lo for x in items],axis),np.stack([x.hi for x in items],axis))
def stack_c(items,axis=0):return C(stack_r([x.re for x in items],axis),stack_r([x.im for x in items],axis))

def gershgorin(matrix):
    n=matrix.re.lo.shape[0];bounds=[]
    if not np.all(np.isfinite([matrix.re.lo,matrix.re.hi,matrix.im.lo,matrix.im.hi])):raise ValueError('NONFINITE_INTERVAL_MATRIX')
    # The continuous form is Hermitian by its domain. Validate overlap of the
    # independently assembled conjugate entries; do not force symmetrization.
    assert np.all(matrix.re.lo<=matrix.re.hi.T) and np.all(matrix.re.lo.T<=matrix.re.hi)
    assert np.all(matrix.im.lo<=-matrix.im.lo.T) and np.all(-matrix.im.hi.T<=matrix.im.hi)
    for i in range(n):
        assert matrix.im.lo[i,i]<=0<=matrix.im.hi[i,i]
        lower=matrix.re.lo[i,i]
        for j in range(n):
            if i==j:continue
            a=max(abs(matrix.re.lo[i,j]),abs(matrix.re.hi[i,j]));b=max(abs(matrix.im.lo[i,j]),abs(matrix.im.hi[i,j]))
            modulus=up(np.sqrt(up(up(a*a)+up(b*b))))
            lower=down(lower-modulus)
        bounds.append(float(lower))
    return {'row_lower_bounds':bounds,'positive_definite':min(bounds)>0,'strict_margin_lower':min(bounds)}
