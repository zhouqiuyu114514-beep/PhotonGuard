"""DEV regression only: exact scalar normalization, no pilot labels or model output."""
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
import semantic_intake as adapter


def dev_view_candidate(scalar):
    contract=adapter.read(adapter.PUBLIC/'semantic_contract.json')
    values=['1D',0,1,True,True,True,1,1,scalar,1.4,235,410,790,191]
    units=[None,'deg',None,None,None,None,None,None,None,None,'nm','nm','nm',None]
    lines=['DEV synthetic structural value for '+key for key in adapter.KEYS]
    packet={'schema_version':'pg-semantic-intake-1','case_id':'DEV-SCALAR-ROUNDTRIP','synthetic':True,'request_zh':'DEV offline structural regression only','documents':[{'id':'D1','title':'DEV source','lines':lines}]}
    view={'semantic_contract':contract,'packet':packet,'clarification_documents':[]}
    view['input_sha256']=adapter.digest(view)
    fields={k:{'status':'proposed','value':v,'unit':u,'evidence':[{'document':'D1','line':i+1,'quote':lines[i]}]} for i,(k,v,u) in enumerate(zip(adapter.KEYS,values,units))}
    candidate={'case_id':packet['case_id'],'input_sha256':view['input_sha256'],'review_status':'REVIEW_REQUIRED','fields':fields,'questions':[],'conflicts':[],'refusal':{'reason_codes':[],'text':None}}
    return view,candidate


class ScalarRoundTripTests(unittest.TestCase):
    def test_legal_scalar_forms_preserve_exact_value_and_public_bounds(self):
        for value in ['1e128','1e1000','1e-1000','1'*128+'e1','1.'+'2'*127,'0e1000','-0e-1000','1.720000','235']:
            with self.subTest(value=value):
                view,candidate=dev_view_candidate(value)
                before=adapter.number(value)
                normalized=adapter.normalize(view,candidate,view['input_sha256'])
                after=normalized['fields']['film_index']['value']
                self.assertEqual(adapter.number(after),before)
                self.assertEqual(normalized['fields']['film_index']['unit'],'dimensionless')
                self.assertEqual(adapter.normalize(view,normalized,view['input_sha256']),normalized)
                json.dumps(normalized,ensure_ascii=False,allow_nan=False)

    def test_raw_json_numeric_scalar_preserves_lexeme(self):
        view,candidate=dev_view_candidate('PLACEHOLDER')
        raw=json.dumps(candidate).replace('"PLACEHOLDER"','1e128')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'candidate.json';p.write_text(raw)
            loaded=adapter.read(p,decimal_numbers=True)
            self.assertIsInstance(loaded['fields']['film_index']['value'],Decimal)
            normalized=adapter.normalize(view,loaded,view['input_sha256'])
            self.assertEqual(adapter.number(normalized['fields']['film_index']['value']),Decimal('1e128'))

    def test_invalid_scalars_are_still_rejected(self):
        for value in ['1e1001','1e-1001','1'*129,True,{},'NaN','Infinity']:
            with self.subTest(value=value):
                view,candidate=dev_view_candidate(value)
                with self.assertRaises(ValueError):adapter.normalize(view,candidate,view['input_sha256'])

    def test_unresolved_null_never_becomes_scalar(self):
        view,candidate=dev_view_candidate(None)
        candidate['fields']['film_index'].update(status='unknown',value=None,unit=None,evidence=[])
        candidate['review_status']='CLARIFICATION_REQUIRED'
        candidate['questions']=[{'targets':['film_index'],'text':'DEV request missing index'}]
        normalized=adapter.normalize(view,candidate,view['input_sha256'])
        self.assertIsNone(normalized['fields']['film_index']['value'])
        self.assertIsNone(normalized['fields']['film_index']['unit'])

if __name__=='__main__':unittest.main(verbosity=2)
