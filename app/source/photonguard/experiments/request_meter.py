"""Layered request accounting; local failures never become empty model replies."""
from ..workflow_model import wire
from ..workflow import write_once

class BatchFrozen(RuntimeError):pass

class RequestMeter:
    def __init__(self,client,folder,limit,*,live=True):
        self.client=client;self.folder=folder;self.limit=limit;self.live=live;self.rows=[];self.frozen=False
    def call(self,ident,payload):
        if self.frozen:raise BatchFrozen('BATCH_ALREADY_FROZEN')
        if len(self.rows)>=self.limit:raise BatchFrozen('REQUEST_WINDOW_EXHAUSTED')
        row={'request_slot':len(self.rows)+1,'id':ident,'preflight_rejected':False,'dispatch_attempted':False,'provider_response_received':False,'usage_verified':False,'mode':'REAL_API' if self.live else 'INJECTED_CLIENT'}
        self.rows.append(row);before=self.client.ledger.snapshot()['attempts'] if self.live else None
        try:
            if wire.credential_risk(payload):raise ValueError('PUBLIC_CONTEXT_PREFLIGHT_REJECTED')
            self.client.preflight()
        except Exception as exc:
            row.update(preflight_rejected=True,failure='LOCAL_PREFLIGHT_FAILURE',error_type=type(exc).__name__);self.frozen=True
            write_once(self.folder/(ident+'-meter.json'),row);raise BatchFrozen('LOCAL_PREFLIGHT_FAILURE') from exc
        try:
            response=self.client.complete(ident,payload)
            audit=response.get('audit',{});row['provider_response_received']=self.live and audit.get('status')=='ASSISTANT_RETURNED'
            row['usage_verified']=self.live and isinstance(audit.get('usage'),dict) and all(type(audit['usage'].get(k)) is int for k in ('prompt_tokens','completion_tokens'))
            if self.live and not row['provider_response_received']:
                row['failure']='PROVIDER_RECEIPT_UNKNOWN';self.frozen=True;raise BatchFrozen('PROVIDER_RECEIPT_UNKNOWN')
            row['mock_response_received']=not self.live
            return response
        except Exception as exc:
            self.frozen=True;row.setdefault('failure','PROVIDER_OR_TRANSPORT_FAILURE');row['error_type']=type(exc).__name__
            raise BatchFrozen(row['failure']) from exc
        finally:
            if self.live:
                row['dispatch_attempted']=self.client.ledger.snapshot()['attempts']>before
                if row.get('failure') and not row['dispatch_attempted']:row.update(failure='LOCAL_PREFLIGHT_FAILURE',preflight_rejected=True)
                row['provider_received']='YES' if row['provider_response_received'] else 'UNKNOWN' if row['dispatch_attempted'] else 'NO'
            write_once(self.folder/(ident+'-meter.json'),row)
