from fractions import Fraction as F
import numpy as np
import pytest
import subprocess,sys
from pathlib import Path
from research.goal_certificate.interval_arithmetic import R,C
from research.goal_certificate.upper_dense import matmul,positive_definite
from research.goal_certificate.spectral_count_upper import rect,tail_coercivity,transverse_basis_exact
from test_goal_certificate import model

def test_dense_signed_complex_products_enclose_exact_rationals():
    a=np.array([[1+2j,1e-40-3j,4-5j],[-2j,3+4j,-1e80]],complex)
    b=np.array([[1e-50+2j,-1],[-3j,1e-40],[1e-80,2j]],complex)
    result=matmul(C.point(a),C.point(b))
    for i in range(2):
        for j in range(2):
            re=im=F(0)
            for k in range(3):
                ar,ai,br,bi=map(F,(a[i,k].real,a[i,k].imag,b[k,j].real,b[k,j].imag))
                re+=ar*br-ai*bi;im+=ar*bi+ai*br
            assert F(result.re.lo[i,j])<=re<=F(result.re.hi[i,j])
            assert F(result.im.lo[i,j])<=im<=F(result.im.hi[i,j])

def test_dense_interval_width_and_subnormal_enclosure():
    a=R([[1.,-2.]],[[1.1,-1.9]]);b=R([[3.],[4.]],[[3.1],[4.1]])
    out=matmul(C(a),C(b))
    for x in (F(1.),F(1.1)):
        for y in (F(-2.),F(-1.9)):
            for z in (F(3.),F(3.1)):
                for w in (F(4.),F(4.1)):assert F(out.re.lo[0,0])<=x*z+y*w<=F(out.re.hi[0,0])
    tiny=np.nextafter(0.,1.);out=matmul(C.point(np.array([[tiny]])),C.point(np.array([[tiny]])))
    assert F(out.re.lo[0,0])<=F(tiny)**2<=F(out.re.hi[0,0])

def test_dense_positive_definiteness_requires_hermitian_and_strict_margin():
    with pytest.raises(ValueError,match='IMAGINARY_DIAGONAL|IMAG_HERMITIAN'):positive_definite(C.point(np.eye(2)*(1+1j)))
    assert not positive_definite(C.point(np.diag([1.,0.])))['positive_definite']
    assert positive_definite(C.point(np.diag([1.,2.])))['positive_definite']

def test_rectangle_zero_exact_and_conjugate_symmetry():
    v=rect(0,F(-1,2),F(1,2));assert F(float(v.re.lo))<=F(1,4)<=F(float(v.re.hi))
    p,n=rect(3,F(-3,10),F(1,10)),rect(-3,F(-3,10),F(1,10))
    assert p.re.lo==n.re.lo and p.re.hi==n.re.hi and p.im.lo==-n.im.hi

def test_entire_tail_is_checked_before_matrix_construction():
    with pytest.raises(ValueError,match='TAIL_NOT_COERCIVE'):tail_coercivity(model(),0,F(209,100),1/F(.775),'uniform-isotropic')
    assert tail_coercivity(model(),4,F(209,100),1/F(.775),'uniform-isotropic')[-1]>0

def test_transverse_map_encloses_exact_divergence_constraint():
    x,y=np.array([-2,0,3]),np.array([1,2,-1]);k=F(71,29)
    J,_=transverse_basis_exact(x,y,k,F(5,4),F(20))
    for i in range(3):
        for j in range(6):
            lo=F(int(x[i]),4)*F(J[0].re.lo[i,j])+F(int(y[i]),4)*F(J[1].re.lo[i,j])+k*F(J[2].re.lo[i,j])
            hi=F(int(x[i]),4)*F(J[0].re.hi[i,j])+F(int(y[i]),4)*F(J[1].re.hi[i,j])+k*F(J[2].re.hi[i,j])
            assert lo<=0<=hi

def test_upper_cli_optimization_cannot_create_output(tmp_path):
    result=subprocess.run([sys.executable,'-B','-O','-m','research.goal_certificate.spectral_count_upper_cli','--model',str(tmp_path/'missing'),'--s','209/100','--f-cut','1','--upper-cap','3','--out',str(tmp_path/'out')],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and 'CERTIFICATE_OPTIMIZATION_UNSUPPORTED' in result.stderr and not (tmp_path/'out').exists()
