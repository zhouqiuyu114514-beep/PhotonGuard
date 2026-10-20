"""Offline replay of the observed coordinator failure; no paid calls or keys."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

import live_transport as live
import continue_live_small_batch as continuation
from batch_ledger import SemanticBatchLedger
from photonguard.backend import ApprovedRates,BackendAuthorization,TransportResponse
from photonguard.cny_budget import CnyApproval


class ContinuationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        date=datetime.now(timezone.utc).isoformat()
        auth=BackendAuthorization(True,'DEV_CONTINUATION','deepseek-flash','0.75',12,
            ApprovedRates('0.3','1.2',date,'https://api-docs.deepseek.com/quick_start/pricing/'))
        cny=CnyApproval('5','2','8',date,'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
        self.ledger=SemanticBatchLedger(auth,Path(self.temp.name)/'new-semantic-budget.ledger.json',cny)
        self.key='sk-DEVmockcontinuation000'
        self.reply={'id':'DEV','model':'deepseek-flash','choices':[{'finish_reason':'stop',
            'message':{'role':'assistant','content':'DEV MOCK NOT OBSERVED'}}],
            'usage':{'prompt_tokens':5,'completion_tokens':5,'total_tokens':10}}

    def test_four_actual_undispatched_requests_fit_without_changing_messages(self):
        session=continuation.ROOT/'local-validation/semantic-live-small-20261006'
        rows=[]
        for path in sorted((session/'observations').glob('*/turn-02/request.json')):
            payload=json.loads(path.read_text());before=json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()
            sent=[]
            def mock(req):sent.append(req.body);return TransportResponse(200,json.dumps(self.reply).encode())
            result=live.complete(payload,self.key,self.ledger,transport=mock)
            self.assertGreater(len(before),65536);self.assertLessEqual(len(before),live.MAX_REQUEST_BYTES)
            self.assertEqual(sent,[before]);self.assertEqual(result['audit']['request_sha256'],live.digest(before))
            self.assertEqual(result['audit']['transport_kind'],'injected_mock');rows.append(path)
        self.assertEqual(len(rows),4)
        self.assertGreaterEqual(live.INPUT_BOUND,live.MAX_REQUEST_BYTES+1024)

    def test_tool_operational_commentary_is_retained_but_not_called_a_final(self):
        message={'role':'assistant','content':"I'll read public documents first.",
            'tool_calls':[{'id':'DEV','type':'function','function':{'name':'export_visible_input','arguments':'{}'}}]}
        before=json.dumps(message);self.assertEqual(continuation.candidate_contents(message),[])
        self.assertEqual(json.dumps(message),before)

    def test_every_final_including_empty_and_malformed_remains_a_submission(self):
        for raw in ('','{broken','[]','null','approval forbidden extra text'):
            self.assertEqual(continuation.candidate_contents({'role':'assistant','content':raw}),
                [('ASSISTANT_FINAL_CONTENT',raw)])

    def test_tool_draft_invalid_arguments_are_not_filtered_out(self):
        for raw in ('{broken','{"candidate":null}','{"candidate":[]}'):
            message={'role':'assistant','content':None,'tool_calls':[{'id':'DEV','type':'function',
                'function':{'name':'review_public_candidate','arguments':raw}}]}
            self.assertEqual(len(continuation.candidate_contents(message)),1)

    def test_tool_draft_numeric_lexemes_are_not_reconstructed(self):
        raw='{ "candidate": {"value":1e128,"quote":"\\u4e2d"} }'
        message={'role':'assistant','content':None,'tool_calls':[{'id':'DEV','type':'function',
            'function':{'name':'review_public_candidate','arguments':raw}}]}
        self.assertEqual(continuation.candidate_contents(message)[0][1],'{"value":1e128,"quote":"\\u4e2d"}')

    def test_existing_four_reservations_stay_consumed_and_total_cannot_exceed_twelve(self):
        payload={'model':'deepseek-flash','messages':[{'role':'user','content':'DEV'}],
            'max_tokens':4096,'thinking':{'type':'disabled'},'stream':False}
        calls=[]
        def mock(req):calls.append(1);raise OSError('DEV MOCK')
        for _ in range(4):live.complete(payload,self.key,self.ledger,transport=mock)
        before=self.ledger.snapshot();self.assertEqual(before['attempts'],4)
        for _ in range(8):live.complete(payload,self.key,self.ledger,transport=mock)
        self.assertEqual(self.ledger.snapshot()['attempts'],12)
        with self.assertRaises(ValueError):live.complete(payload,self.key,self.ledger,transport=mock)
        self.assertEqual(len(calls),12)
        self.assertGreater(float(self.ledger.snapshot()['reserved_cny']),float(before['reserved_cny']))


if __name__=='__main__':unittest.main(verbosity=2)
