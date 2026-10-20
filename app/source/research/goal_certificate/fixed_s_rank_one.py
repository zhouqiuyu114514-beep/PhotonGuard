"""Small exact recombination of hash-bound, previously verified forms.

No new integration or eigensolve. Hashes bind upstream evidence, not a new
proof of its continuous-domain or outward-assembly assumptions.
"""
import hashlib
import json
from fractions import Fraction as F
from pathlib import Path
from .selector_observable_bounds import fraction, sqrt_bounds


class Interval:
    def __init__(self, lo, hi=None):
        self.lo, self.hi = fraction(lo), fraction(lo if hi is None else hi)
        if self.lo > self.hi:
            raise ValueError('REVERSED_INTERVAL')

    def __add__(self, other):
        other = other if isinstance(other, Interval) else Interval(other)
        return Interval(self.lo+other.lo, self.hi+other.hi)
    __radd__ = __add__

    def __neg__(self):
        return Interval(-self.hi, -self.lo)

    def __sub__(self, other):
        return self + -(other if isinstance(other, Interval) else Interval(other))

    def __mul__(self, other):
        other = other if isinstance(other, Interval) else Interval(other)
        v = [a*b for a in (self.lo,self.hi) for b in (other.lo,other.hi)]
        return Interval(min(v),max(v))
    __rmul__ = __mul__

    def absmax(self):
        return max(abs(self.lo),abs(self.hi))


def read_matrix(value, dim=3):
    for key in ('real','imag'):
        a = value[key]
        if len(a)!=2 or any(len(part)!=dim or any(len(row)!=dim for row in part) for part in a):
            raise ValueError('MATRIX_SHAPE')
    return [[tuple(Interval(value[k][0][i][j],value[k][1][i][j]) for k in ('real','imag'))
             for j in range(dim)] for i in range(dim)]


def hermitian_overlap(matrix):
    for i,row in enumerate(matrix):
        if not row[i][1].lo <= 0 <= row[i][1].hi:
            raise ValueError('NONREAL_DIAGONAL')
        for j,(re,im) in enumerate(row):
            for a,b in ((re,matrix[j][i][0]),(im,-matrix[j][i][1])):
                if max(a.lo,b.lo)>min(a.hi,b.hi):
                    raise ValueError('NONHERMITIAN_ENCLOSURE')


def witness(forms, cutoff, columns):
    M,N,G = [read_matrix(forms[k]) for k in ('mass','N','continuous_graph')]
    for matrix in (M,N,G):
        hermitian_overlap(matrix)
    tau=F(1,20); c=1/(cutoff-tau)
    R=[[tuple(N[i][j][k]*(1+2*c*tau)-G[i][j][k]*c-M[i][j][k]*(tau+c*tau*tau)
              for k in (0,1)) for j in columns] for i in columns]
    hermitian_overlap(R)
    margins=[row[i][0].lo-sum(sqrt_bounds(z[0].absmax()**2+z[1].absmax()**2)[1]
                             for j,z in enumerate(row) if i!=j) for i,row in enumerate(R)]
    if min(margins)<=0:
        raise ValueError('POSITIVE_WITNESS_INSUFFICIENT')
    return {'cut_exact':str(cutoff),'columns':columns,'row_margin_exact':list(map(str,margins)),
            'row_margin_float':list(map(float,margins)),
            'R_exact':[[[[str(c.lo),str(c.hi)] for c in z] for z in row] for row in R]}


def complementary_gap(rho):
    rho=fraction(rho)
    gap=min(rho-F(1277,1000),1/F(.775)-rho,abs(rho))
    if gap<=0:
        raise ValueError('POSITIVE_COMPLEMENTARY_GAP_REQUIRED')
    return gap


def verify(root, bindings, rho=F(1283,1000)):
    root=Path(root); loaded={}
    for name, entry in bindings.items():
        path=(root/entry['path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('INPUT_PATH_ESCAPE')
        with path.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=entry['sha256']:
            raise ValueError('UPSTREAM_HASH_MISMATCH:'+name)
        if path.suffix=='.json':
            loaded[name]=json.loads(path.read_text())
    forms, model, freeze = [loaded[k] for k in ('forms','model','trial_freeze')]
    if freeze['trial_file_sha256']!=bindings['dofs']['sha256'] or freeze['model_sha256']!=bindings['model']['sha256']:
        raise ValueError('UPSTREAM_DOF_MODEL_BINDING')
    if F(forms['parameter_s_exact'])!=F(209,100) or F(forms['wavelength_exact'])!=F(.775):
        raise ValueError('FIXED_PARAMETER_BINDING')
    if model['boundary']!='periodic' or model['relative_permeability']!=1:
        raise ValueError('CONTINUOUS_MODEL_DOMAIN')
    fstar=1/F(.775)
    for key,cut,count in [('upper_target',fstar,3),('upper_low',F(32,25),2)]:
        record=loaded[key]
        if (F(record['s_exact'])!=F(209,100) or F(record['f_cut_exact'])!=cut
                or record['upper_count']!=count or record['calibration'] is not None
                or record['model_file_sha256']!=bindings['model']['sha256']
                or min(record['strict_congruence_positive_definiteness']['row_lower_bounds'])<=0):
            raise ValueError('PREVERIFIED_UPPER_RECORD_MISMATCH')
    lower2=witness(forms,F(1277,1000),[1,2])
    lower3=witness(forms,fstar,[0,1,2])
    return {'status':'FIXED_S_RANK_ONE_SUBRESULT','s_exact':'209/100',
            'rank':1,'spectral_window_exact':['32/25',str(fstar)],'left_closed':True,'right_closed':False,
            'lower_two_witness':lower2,'lower_three_witness_replay':lower3,
            'rho_exact':str(rho),'complementary_gap_lower_exact':str(complementary_gap(rho)),
            'input_bindings':bindings,'upstream_continuous_form_assumptions_inherited':True,
            'upstream_upper_counts_byte_bound_not_reassembled':True,
            'new_spatial_assemblies':0,'new_spectral_proposals':0,
            'field_error_certified':False,'root_tube_gap_certified':False,'unlocks_C':False,
            'original_target_rank_bound':False}
