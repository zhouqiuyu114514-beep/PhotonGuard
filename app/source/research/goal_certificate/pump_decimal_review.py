"""Independent Decimal enclosure of the supersolution jump inequalities.

Uses a different alternating-term count and explicit interval operations. Decimal
transcendental exp/sqrt are correctly rounded; one outward ULP encloses them.
"""
from decimal import Decimal as D, localcontext, ROUND_FLOOR, ROUND_CEILING

def verify(wavelength):
    with localcontext() as ctx:
        ctx.prec=72
        def bound(x,up):return x.next_plus() if up else x.next_minus()
        def point(x):return (D(x),D(x))
        def add(a,b):return bound(a[0]+b[0],False),bound(a[1]+b[1],True)
        def neg(a):return -a[1],-a[0]
        def mul(a,b):
            v=[x*y for x in a for y in b];return bound(min(v),False),bound(max(v),True)
        def reciprocal(a):
            assert a[0]>0;return bound(1/a[1],False),bound(1/a[0],True)
        def div(a,b):return mul(a,reciprocal(b))
        def sqrt(a):return bound(a[0].sqrt(),False),bound(a[1].sqrt(),True)
        def atan(q):
            x=div(point(1),point(q));x2=mul(x,x);power=x;s=point(0)
            for j in range(100):
                term=div(power,point(2*j+1));s=add(s,term if j%2==0 else neg(term));power=mul(power,x2)
            term=div(power,point(201));return s[0],add(s,term)[1]
        pi=add(mul(point(16),atan(5)),neg(mul(point(4),atan(239))))
        wave=(min(D.from_float(float(wavelength)),D('1.55')),max(D.from_float(float(wavelength)),D('1.55')))
        k=div(mul(point(2),pi),wave)
        h=sqrt(mul(mul(k,k),point('0.6875')))
        alpha=sqrt(mul(mul(k,k),point('2.1285')))
        x=mul(h,point('.3'));x2=mul(x,x)
        sine=point(0);cosine=point(0);st=x;ct=point(1)
        for j in range(32):
            sine=add(sine,st if j%2==0 else neg(st));cosine=add(cosine,ct if j%2==0 else neg(ct))
            st=div(mul(st,x2),point((2*j+2)*(2*j+3)))
            ct=div(mul(ct,x2),point((2*j+1)*(2*j+2)))
        # First omitted term is positive; bound the alternating remainder.
        sine=(sine[0],add(sine,st)[1]);cosine=(cosine[0],add(cosine,ct)[1])
        tangent=div(sine,cosine)
        z=mul(mul(alpha,point('1.7')),point(2))
        exponential=(bound(z[0].exp(),False),bound(z[1].exp(),True))
        tanh=div(add(exponential,point(-1)),add(exponential,point(1)))
        right=mul(alpha,tanh);left=mul(h,tangent)
        te=add(right,neg(left));tm=add(div(right,point('2.074')),neg(div(left,point('4.89'))))
        assert x[1]<pi[0]/2 and cosine[0]>0 and te[0]>D('.4684') and tm[0]>D('1.7323')
        return {'scalar_review_passed':True,'precision_decimal_digits':72,
                'TE_margin_interval':[str(x) for x in te],'TM_margin_interval':[str(x) for x in tm],
                'method':'Independent Decimal intervals, 100-term Machin, sine/cosine alternating remainder, correctly-rounded exp/sqrt widened one ULP'}
