"""One-shot GUI batch ledger with a conservative model-context reservation.

The old semantic and diagnostic ledgers are untouched. A pending dispatch owns
its worst-case reservation until a complete, checked usage record settles it.
"""
from decimal import Decimal, InvalidOperation
import os
import secrets

from .backend import _decimal, _strict_json
from .workflow_model import SemanticBatchLedger


# DeepSeek publishes a 1M-token context for deepseek-flash. Reserve 1 Mi tokens
# so the bound is conservative whether the displayed M is decimal or binary.
CONTEXT_INPUT_BOUND = 1_048_576
OUTPUT_BOUND = 4096
MAX_LEDGER_BYTES = 16384


class GuiBatchLedger(SemanticBatchLedger):
    def _quote(self, prompt_tokens, completion_tokens):
        usd = ((Decimal(prompt_tokens) * _decimal(self.authorization.rates.input_usd_per_million)
                + Decimal(completion_tokens) * _decimal(self.authorization.rates.output_usd_per_million))
               / Decimal(1_000_000))
        return usd, self._cny_bound(usd)

    def worst_quote(self):
        return self._quote(CONTEXT_INPUT_BOUND, OUTPUT_BOUND)

    def _empty(self):
        return {'schema_version': 3, 'approval_sha256': self._binding(),
                'attempts': 0, 'live_provider_attempts': 0,
                'settled_usd': '0', 'settled_cny': '0',
                'reserved_usd': '0', 'reserved_cny': '0',
                'pending': None, 'halted': False}

    def _read(self, *, require_existing=False):
        if not self.path.exists():
            if require_existing:
                raise ValueError('Existing GUI batch ledger required')
            return self._empty()
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as stream:
                raw = stream.read(MAX_LEDGER_BYTES + 1)
            if len(raw) > MAX_LEDGER_BYTES:
                raise ValueError('Oversized GUI batch ledger')
            value = _strict_json(raw.decode('utf-8'))
            if type(value) is not dict or set(value) != set(self._empty()):
                raise ValueError('GUI batch ledger fields differ')
            if (type(value['schema_version']) is not int or value['schema_version'] != 3
                    or value['approval_sha256'] != self._binding()
                    or type(value['attempts']) is not int
                    or not 0 <= value['attempts'] <= self.authorization.max_calls
                    or type(value['live_provider_attempts']) is not int
                    or not 0 <= value['live_provider_attempts'] <= value['attempts']
                    or type(value['halted']) is not bool):
                raise ValueError('GUI batch binding or counters differ')
            amounts = {}
            for field in ('settled_usd', 'settled_cny', 'reserved_usd', 'reserved_cny'):
                if type(value[field]) is not str:
                    raise ValueError('GUI batch amount type differs')
                amounts[field] = Decimal(value[field])
                if not amounts[field].is_finite() or amounts[field] < 0:
                    raise ValueError('GUI batch amount invalid')
            if (amounts['reserved_usd'] > _decimal(self.authorization.total_budget_usd)
                    or amounts['reserved_cny'] > _decimal(self.cny.total_budget_cny)
                    or amounts['reserved_usd'] < amounts['settled_usd']
                    or amounts['reserved_cny'] < amounts['settled_cny']
                    or amounts['reserved_cny'] < self._cny_bound(amounts['reserved_usd'])):
                raise ValueError('GUI batch budget invalid')
            pending = value['pending']
            if pending is None:
                if (amounts['reserved_usd'] != amounts['settled_usd']
                        or amounts['reserved_cny'] != amounts['settled_cny']):
                    raise ValueError('Unowned GUI reservation')
            else:
                if (type(pending) is not dict or set(pending) != {'id', 'usd', 'cny', 'live'}
                        or type(pending['id']) is not str or len(pending['id']) != 32
                        or any(ch not in '0123456789abcdef' for ch in pending['id'])
                        or type(pending['live']) is not bool
                        or type(pending['usd']) is not str or type(pending['cny']) is not str
                        or not value['attempts']):
                    raise ValueError('GUI reservation invalid')
                worst_usd, worst_cny = self.worst_quote()
                if (Decimal(pending['usd']) != worst_usd or Decimal(pending['cny']) != worst_cny
                        or amounts['reserved_usd'] != amounts['settled_usd'] + worst_usd
                        or amounts['reserved_cny'] != amounts['settled_cny'] + worst_cny):
                    raise ValueError('GUI reservation mismatch')
            if value['attempts'] == 0 and amounts['reserved_usd'] != 0:
                raise ValueError('GUI batch attempt and amount mismatch')
            return value
        except (ValueError, TypeError, KeyError, InvalidOperation, UnicodeError):
            raise ValueError('GUI batch ledger corrupt or belongs to another approval') from None

    def reserve(self, amount, live, *, require_existing=False):
        raise ValueError('GUI batch requires context-bound reserve_worst')

    def reserve_worst(self, live, *, require_existing=True):
        if type(live) is not bool:
            raise ValueError('Explicit dispatch kind required')
        worst_usd, worst_cny = self.worst_quote()
        if worst_cny >= _decimal(self.cny.total_budget_cny):
            raise ValueError('A single worst-case request cannot fit the approval')
        with self._locked():
            value = self._read(require_existing=require_existing)
            next_usd = Decimal(value['reserved_usd']) + worst_usd
            next_cny = Decimal(value['reserved_cny']) + worst_cny
            if (value['halted'] or value['pending'] is not None
                    or value['attempts'] >= self.authorization.max_calls
                    or next_usd > _decimal(self.authorization.total_budget_usd)
                    or next_cny > _decimal(self.cny.total_budget_cny)):
                raise ValueError('GUI batch pending, stopped, or worst-case budget exhausted')
            guard = getattr(self, 'reservation_guard', None)
            if guard is not None:
                # The optional stricter stage bound is checked inside the same
                # cumulative lock, before any reservation or counter mutation.
                guard(value.copy(), next_cny)
            value['pending'] = {'id': secrets.token_hex(16), 'usd': str(worst_usd),
                                'cny': str(worst_cny), 'live': live}
            value['attempts'] += 1
            value['live_provider_attempts'] += int(live)
            value['reserved_usd'], value['reserved_cny'] = str(next_usd), str(next_cny)
            self._write(value)
            return value

    def settle_usage(self, reservation_id, usage):
        if (type(usage) is not dict
                or any(type(usage.get(name)) is not int or usage[name] < 0
                       for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']
                or usage['prompt_tokens'] > CONTEXT_INPUT_BOUND
                or usage['completion_tokens'] > OUTPUT_BOUND):
            raise ValueError('Incomplete or out-of-bound provider usage')
        for name in ('prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'):
            if name in usage and (type(usage[name]) is not int
                                  or not 0 <= usage[name] <= usage['prompt_tokens']):
                raise ValueError('Invalid cache usage')
        if ('prompt_cache_hit_tokens' in usage and 'prompt_cache_miss_tokens' in usage
                and usage['prompt_cache_hit_tokens'] + usage['prompt_cache_miss_tokens']
                != usage['prompt_tokens']):
            raise ValueError('Inconsistent cache usage')
        details = usage.get('completion_tokens_details')
        if details is not None and (type(details) is not dict
                                    or type(details.get('reasoning_tokens', 0)) is not int
                                    or details.get('reasoning_tokens', 0) != 0):
            raise ValueError('Unexpected thinking tokens')
        actual_usd, actual_cny = self._quote(usage['prompt_tokens'], usage['completion_tokens'])
        worst_usd, worst_cny = self.worst_quote()
        if actual_usd > worst_usd or actual_cny > worst_cny:
            raise ValueError('Reported usage exceeds worst-case reservation')
        with self._locked():
            value = self._read(require_existing=True)
            pending = value['pending']
            if (value['halted'] or pending is None or type(reservation_id) is not str
                    or pending['id'] != reservation_id):
                raise ValueError('No matching unsettled GUI reservation')
            value['settled_usd'] = str(Decimal(value['settled_usd']) + actual_usd)
            value['settled_cny'] = str(Decimal(value['settled_cny']) + actual_cny)
            value['reserved_usd'] = str(Decimal(value['reserved_usd']) - worst_usd + actual_usd)
            value['reserved_cny'] = str(Decimal(value['reserved_cny']) - worst_cny + actual_cny)
            value['pending'] = None
            self._write(value)
            return value
