"""Outward interval dense products under IEEE binary64 round-to-nearest.

Four REAL BLAS products bound a complex product; no complex-BLAS error model.
Each real dot uses gamma_(2n+2), including product/summation and subnormal slack.
"""
from fractions import Fraction as F
import numpy as np
from .interval_arithmetic import R,C,up,down,rational

def validate(a):
    for x in (a.re,a.im):
        if not np.isfinite(x.lo).all() or not np.isfinite(x.hi).all() or np.any(x.lo>x.hi):raise ValueError('INVALID_MATRIX_INTERVAL')

def transpose(a):return C(R(a.re.lo.T,a.re.hi.T),R(-a.im.hi.T,-a.im.lo.T))

def midpoint(a):return (a.re.lo/2+a.re.hi/2)+1j*(a.im.lo/2+a.im.hi/2)

def positive_dot_upper(a,b):
    n=a.shape[1];g=float(rational(F(2*n+2,2**53-(2*n+2))).hi)
    value=a@b
    if not np.isfinite(value).all():raise ValueError('DOT_OVERFLOW')
    tiny=up((4*n+4)*np.nextafter(0.,1.))
    return up(up(value+tiny)/down(1-g))

def real_product(a,b):
    am=a.lo/2+a.hi/2;bm=b.lo/2+b.hi/2
    ar=up(np.maximum(abs(am-a.lo),abs(a.hi-am)));br=up(np.maximum(abs(bm-b.lo),abs(b.hi-bm)))
    n=am.shape[1];g=float(rational(F(2*n+2,2**53-(2*n+2))).hi)
    mid=am@bm
    err=up(positive_dot_upper(abs(am),abs(bm))*g)
    err=up(err+positive_dot_upper(abs(am),br));err=up(err+positive_dot_upper(ar,abs(bm)))
    err=up(err+positive_dot_upper(ar,br));err=up(err+up((4*n+4)*np.nextafter(0.,1.)))
    if not np.isfinite(mid).all():raise ValueError('DOT_OVERFLOW')
    return R(down(mid-err),up(mid+err))

def matmul(a,b):
    validate(a);validate(b)
    def broadcast(v):
        shape=np.broadcast_shapes(v.re.lo.shape,v.re.hi.shape,v.im.lo.shape,v.im.hi.shape)
        if len(shape)!=2:raise ValueError('MATRIX_DIMENSION')
        return C(R(np.broadcast_to(v.re.lo,shape),np.broadcast_to(v.re.hi,shape)),R(np.broadcast_to(v.im.lo,shape),np.broadcast_to(v.im.hi,shape)))
    a,b=broadcast(a),broadcast(b)
    return C(real_product(a.re,b.re)-real_product(a.im,b.im),real_product(a.re,b.im)+real_product(a.im,b.re))

def positive_definite(a):
    validate(a)
    if a.re.lo.ndim!=2 or a.re.lo.shape[0]!=a.re.lo.shape[1]:raise ValueError('SQUARE_MATRIX_REQUIRED')
    if np.any(a.re.lo>a.re.hi.T) or np.any(a.re.lo.T>a.re.hi):raise ValueError('REAL_HERMITIAN_OVERLAP')
    if np.any(a.im.lo>-a.im.lo.T) or np.any(-a.im.hi.T>a.im.hi):raise ValueError('IMAG_HERMITIAN_OVERLAP')
    if np.any(np.diag(a.im.lo)>0) or np.any(np.diag(a.im.hi)<0):raise ValueError('IMAGINARY_DIAGONAL')
    x=np.maximum(abs(a.re.lo),abs(a.re.hi));y=np.maximum(abs(a.im.lo),abs(a.im.hi))
    off=up(np.sqrt(up(up(x*x)+up(y*y))));np.fill_diagonal(off,0)
    sums=R(off).sum(axis=1).hi;bounds=down(np.diag(a.re.lo)-sums)
    return {'positive_definite':bool(np.min(bounds)>0),'strict_margin_lower':float(np.min(bounds)),'row_lower_bounds':bounds.tolist()}
