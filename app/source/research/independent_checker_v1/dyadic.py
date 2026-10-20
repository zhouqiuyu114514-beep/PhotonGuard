"""Integer endpoints on a 2^-96 lattice; no binary floating arithmetic inside.

Every multiplication/division rounds endpoints outwards using integer floor.
NumPy supplies array iteration only; Python integers cannot overflow.
"""
from fractions import Fraction
import numpy as np

BITS=96
S=1<<BITS

def minimum(a,b):return np.minimum(np.asarray(a,dtype=object),np.asarray(b,dtype=object))
def maximum(a,b):return np.maximum(np.asarray(a,dtype=object),np.asarray(b,dtype=object))

def fraction(x):
    return Fraction(float(x)) if isinstance(x,np.floating) else Fraction(int(x)) if isinstance(x,np.integer) else Fraction(x)

class Q:
    def __init__(self,lo,hi=None,*,raw=False):
        if raw:
            self.lo=np.asarray(lo,dtype=object);self.hi=np.asarray(hi,dtype=object)
        else:
            a=np.asarray(lo,dtype=object)
            def lower(x):v=fraction(x)*S;return v.numerator//v.denominator
            def upper(x):v=fraction(x)*S;return -((-v.numerator)//v.denominator)
            self.lo=np.frompyfunc(lower,1,1)(a)
            self.hi=np.frompyfunc(upper,1,1)(np.asarray(lo if hi is None else hi,dtype=object))
            self.lo=np.asarray(self.lo,dtype=object);self.hi=np.asarray(self.hi,dtype=object)
        if np.any(self.lo>self.hi):raise ValueError('REVERSED_DYADIC_INTERVAL')
    @staticmethod
    def ensure(v):return v if isinstance(v,Q) else Q(v)
    def __add__(self,b):
        b=Q.ensure(b);return Q(self.lo+b.lo,self.hi+b.hi,raw=True)
    __radd__=__add__
    def __neg__(self):return Q(-self.hi,-self.lo,raw=True)
    def __sub__(self,b):return self+-Q.ensure(b)
    def __rsub__(self,b):return Q.ensure(b)+-self
    def __mul__(self,b):
        b=Q.ensure(b);v=[self.lo*b.lo,self.lo*b.hi,self.hi*b.lo,self.hi*b.hi]
        lo=minimum(minimum(v[0],v[1]),minimum(v[2],v[3]))
        hi=maximum(maximum(v[0],v[1]),maximum(v[2],v[3]))
        return Q(lo//S,-((-hi)//S),raw=True)
    __rmul__=__mul__
    def __truediv__(self,b):
        b=Q.ensure(b)
        if np.any((b.lo<=0)&(b.hi>=0)):raise ValueError('ZERO_INTERVAL_DIVISOR')
        v=[(a*S,d) for a in (self.lo,self.hi) for d in (b.lo,b.hi)]
        low=[a//d for a,d in v];high=[-((-a)//d) for a,d in v]
        return Q(minimum(minimum(low[0],low[1]),minimum(low[2],low[3])),maximum(maximum(high[0],high[1]),maximum(high[2],high[3])),raw=True)
    def __rtruediv__(self,b):return Q.ensure(b)/self
    def __getitem__(self,item):return Q(self.lo[item],self.hi[item],raw=True)
    def sum(self,axis=None):return Q(np.sum(self.lo,axis=axis),np.sum(self.hi,axis=axis),raw=True)
    def export(self):return [str(Fraction(int(self.lo),S)),str(Fraction(int(self.hi),S))]

def stack(xs,axis=0):return Q(np.stack([x.lo for x in xs],axis),np.stack([x.hi for x in xs],axis),raw=True)

class Z:
    def __init__(self,re,im=0):self.re=Q.ensure(re);self.im=Q.ensure(im)
    @staticmethod
    def point(z):return Z(Q(np.real(z)),Q(np.imag(z)))
    def __add__(self,b):
        if not isinstance(b,Z):b=Z(b)
        return Z(self.re+b.re,self.im+b.im)
    __radd__=__add__
    def __neg__(self):return Z(-self.re,-self.im)
    def __sub__(self,b):return self+-b
    def __mul__(self,b):
        if isinstance(b,Z):return Z(self.re*b.re-self.im*b.im,self.re*b.im+self.im*b.re)
        return Z(self.re*b,self.im*b)
    __rmul__=__mul__
    def __getitem__(self,i):return Z(self.re[i],self.im[i])
    def sum(self,axis=None):return Z(self.re.sum(axis),self.im.sum(axis))
    def times_i(self):return Z(-self.im,self.re)
    def conj(self):return Z(self.re,-self.im)
    def export(self):return {'real':self.re.export(),'imag':self.im.export()}

def zstack(xs,axis=0):return Z(stack([z.re for z in xs],axis),stack([z.im for z in xs],axis))

def pi_bounds(n=44):
    def atan(q):
        partial=sum((Fraction((-1)**k,(2*k+1)*q**(2*k+1)) for k in range(n)),Fraction())
        term=Fraction(1,(2*n+1)*q**(2*n+1))
        return (partial,partial+term) if n%2==0 else (partial-term,partial)
    a,b=atan(5),atan(239)
    return 16*a[0]-4*b[1],16*a[1]-4*b[0]
