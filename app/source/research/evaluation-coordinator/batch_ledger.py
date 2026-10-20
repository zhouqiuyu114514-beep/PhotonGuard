"""Separate small-batch approval binding, reusing audited atomic ledger I/O.

The original diagnostic authorization cap and ledger are unchanged. This binding
accepts only the explicitly frozen semantic budget/model and a new filename.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from photonguard.backend import _decimal,_iso_timestamp
from photonguard.cny_budget import PersistentCnyLedger,CnyApproval


class SemanticBatchLedger(PersistentCnyLedger):
    def _binding(self):
        a=self.authorization;c=self.cny
        if (a is None or a.approved is not True or a.model!='deepseek-flash' or
                type(a.max_calls) is not int or not 1<=a.max_calls<=12 or
                not isinstance(a.reference,str) or not a.reference.startswith(('semantic-small-','DEV_')) or
                self.path.name!='new-semantic-budget.ledger.json' or not isinstance(c,CnyApproval)):
            raise ValueError('invalid separate semantic approval')
        if (not _iso_timestamp(a.rates.checked_at) or not _iso_timestamp(c.checked_at) or
                a.rates.source!='https://api-docs.deepseek.com/quick_start/pricing/' or
                c.source!='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/' or
                not Decimal(0)<_decimal(a.total_budget_usd)<=Decimal('0.75') or
                not Decimal(0)<_decimal(c.total_budget_cny)<=Decimal('5') or
                _decimal(a.rates.input_usd_per_million)!=Decimal('0.3') or
                _decimal(a.rates.output_usd_per_million)!=Decimal('1.2') or
                _decimal(c.input_cny_per_million)!=Decimal('2') or
                _decimal(c.output_cny_per_million)!=Decimal('8')):
            raise ValueError('unfrozen rates or semantic budget')
        value={'binding_version':'semantic-small-separate-v1','reference':a.reference,'model':a.model,
               'max_calls':a.max_calls,'usd_limit':str(_decimal(a.total_budget_usd)),
               'cny_limit':str(_decimal(c.total_budget_cny)),'usd_rates':['0.3','1.2'],
               'cny_rates':['2','8'],'checked_at':[a.rates.checked_at,c.checked_at],
               'sources':[a.rates.source,c.source]}
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
