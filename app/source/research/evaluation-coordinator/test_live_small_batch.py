"""Mock transport regressions: no provider calls, real keys or pilot answers."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
import live_transport as live
from photonguard.backend import ApprovedRates,BackendAuthorization,TransportResponse
from photonguard.cny_budget import CnyApproval
from batch_ledger import SemanticBatchLedger


class LiveTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.key='sk-DEVfakecredential123456'
        self.date=datetime.now(timezone.utc).isoformat()
        self.auth=BackendAuthorization(True,'DEV_NEW_AUTH','deepseek-flash','0.75',12,
            ApprovedRates('0.3','1.2',self.date,'https://api-docs.deepseek.com/quick_start/pricing/'))
        self.cny=CnyApproval('5','2','8',self.date,'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
        self.ledger=SemanticBatchLedger(self.auth,self.root/'new-semantic-budget.ledger.json',self.cny)
        self.payload={'model':'deepseek-flash','messages':[{'role':'user','content':'DEV only'}],
            'max_tokens':4096,'thinking':{'type':'disabled'},'stream':False,'temperature':0}

    def envelope(self,content='{"DEV":true}',finish='stop',**extra):
        return {'id':'DEV-COMPLETION','model':'deepseek-flash','choices':[{'index':0,
            'finish_reason':finish,'message':{'role':'assistant','content':content}}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120},**extra}

    def send(self,envelope):
        body=json.dumps(envelope).encode()
        return live.complete(self.payload,self.key,self.ledger,
            transport=lambda req:TransportResponse(200,body))

    def test_malformed_candidate_remains_exact_and_http_body_is_absent(self):
        raw='  {broken\\u0041  '
        result=self.send(self.envelope(raw))
        self.assertEqual(result['assistant']['content'],raw)
        self.assertIsNone(result['audit']['response'])
        self.assertEqual(result['audit']['status'],'ASSISTANT_RETURNED')

    def test_twelfth_dispatch_reserves_and_thirteenth_does_not_send(self):
        calls=[]
        def mock(req):calls.append(1);raise OSError(self.key)
        for _ in range(12):
            result=live.complete(self.payload,self.key,self.ledger,transport=mock)
            self.assertEqual(result['audit']['status'],'TRANSPORT_FAILURE')
        with self.assertRaises(ValueError):live.complete(self.payload,self.key,self.ledger,transport=mock)
        self.assertEqual(len(calls),12);self.assertEqual(self.ledger.snapshot()['attempts'],12)
        self.assertNotIn(self.key,json.dumps(result))

    def test_cny_cap_blocks_before_dispatch(self):
        cny=CnyApproval('0.01','2','8',self.date,self.cny.source)
        folder=self.root/'LOW';folder.mkdir()
        ledger=SemanticBatchLedger(self.auth,folder/'new-semantic-budget.ledger.json',cny);calls=[]
        with self.assertRaises(ValueError):
            live.complete(self.payload,self.key,ledger,transport=lambda req:calls.append(1))
        self.assertEqual(calls,[]);self.assertEqual(ledger.snapshot()['attempts'],0)

    def test_credentials_in_unknown_envelope_fields_are_not_persisted(self):
        result=self.send(self.envelope(extra={'authorization':self.key,self.key:'hidden'}))
        self.assertNotIn(self.key,json.dumps(result));self.assertIsNone(result['audit']['response'])

    def test_escaped_key_in_candidate_stops_without_raw_retention(self):
        raw=json.dumps({'note':''.join('\\u%04x'%ord(c) for c in self.key)})
        result=self.send(self.envelope(raw))
        self.assertEqual(result['audit']['status'],'SAFETY_STOP');self.assertIsNone(result['assistant'])
        self.assertEqual(self.ledger.snapshot()['attempts'],1)

    def test_json_keys_and_stringified_inner_json_are_checked(self):
        for content in [json.dumps({self.key:1}),json.dumps({'note':json.dumps({'password':'DEV-hidden'})})]:
            self.assertTrue(live.credential_risk(content,self.key))
        self.assertFalse(live.credential_risk('{broken',self.key))

    def test_usage_over_reservation_halts_further_dispatches(self):
        env=self.envelope();env['usage']={'prompt_tokens':live.INPUT_BOUND+1,'completion_tokens':1,'total_tokens':live.INPUT_BOUND+2}
        result=self.send(env);self.assertTrue(result['audit']['usage_exceeded_reservation'])
        self.assertTrue(self.ledger.snapshot()['halted'])
        with self.assertRaises(ValueError):self.send(self.envelope())

    def test_truncated_completion_still_preserves_candidate(self):
        result=self.send(self.envelope('{partial',finish='length'))
        self.assertEqual(result['audit']['status'],'INCOMPLETE_RETURN')
        self.assertEqual(result['assistant']['content'],'{partial')

    def test_exact_tool_argument_numeric_and_unicode_lexemes(self):
        arguments='{ "candidate" : {"value":1e128,"quote":"\\u4e2d"} }'
        env=self.envelope(None,finish='tool_calls')
        env['choices'][0]['message']['tool_calls']=[{'id':'DEV-tool','type':'function',
            'function':{'name':'review_public_candidate','arguments':arguments}}]
        result=self.send(env)
        self.assertEqual(result['assistant']['tool_calls'][0]['function']['arguments'],arguments)
        self.assertEqual(live.raw_member(arguments,'candidate'),'{"value":1e128,"quote":"\\u4e2d"}')

    def test_request_echo_of_key_never_reserves_or_sends(self):
        self.payload['messages'][0]['content']=self.key
        with self.assertRaises(ValueError):self.send(self.envelope())
        self.assertEqual(self.ledger.snapshot()['attempts'],0)


if __name__=='__main__':unittest.main(verbosity=2)
