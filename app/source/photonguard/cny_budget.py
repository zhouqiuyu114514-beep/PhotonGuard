"""One persistent ledger enforcing published CNY prices alongside USD audits."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import hashlib
import json
import os
from urllib.parse import urlsplit

from .backend import PersistentBudgetLedger, _decimal, _iso_timestamp, _strict_json


@dataclass(frozen=True)
class CnyApproval:
    total_budget_cny: str
    input_cny_per_million: str
    output_cny_per_million: str
    checked_at: str
    source: str


class PersistentCnyLedger(PersistentBudgetLedger):
    """Atomic dual-currency reservation; one file and one attempt counter.

    Conversion is a conservative ratio of paired published token tariffs,
    never a purported exchange rate. Actual CNY estimates use CNY prices.
    The parent POSIX locking, atomic write and fsync implementation is reused.
    """
    def __init__(self, authorization, ledger_path, cny_approval):
        super().__init__(authorization, ledger_path)
        self.cny = cny_approval

    def _binding(self):
        usd_binding = super()._binding()
        if not isinstance(self.cny, CnyApproval) or not _iso_timestamp(self.cny.checked_at):
            raise ValueError("Dated CNY approval required")
        url = urlsplit(self.cny.source)
        if (url.scheme != "https" or url.netloc != "api-docs.deepseek.com"
                or not url.path.startswith("/zh-cn/quick_start/pricing")):
            raise ValueError("Official CNY tariff source required")
        data = {"usd_approval_sha256": usd_binding, "currency": "CNY",
                "total_budget_cny": str(_decimal(self.cny.total_budget_cny)),
                "input_cny_per_million": str(_decimal(self.cny.input_cny_per_million)),
                "output_cny_per_million": str(_decimal(self.cny.output_cny_per_million)),
                "checked_at": self.cny.checked_at, "source": self.cny.source}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _cny_bound(self, amount):
        with localcontext() as ctx:
            ctx.prec = 60
            ctx.rounding = ROUND_CEILING
            rates = self.authorization.rates
            factor = max(_decimal(self.cny.input_cny_per_million) /
                         _decimal(rates.input_usd_per_million),
                         _decimal(self.cny.output_cny_per_million) /
                         _decimal(rates.output_usd_per_million))
            return (amount * factor).quantize(Decimal("0.000000000001"),
                                              rounding=ROUND_CEILING)

    def _read(self, *, require_existing=False):
        binding = self._binding()
        if not self.path.exists():
            if require_existing:
                raise ValueError("Existing approval ledger required")
            return {"schema_version": 2, "approval_sha256": binding,
                    "attempts": 0, "live_provider_attempts": 0,
                    "reserved_usd": "0", "reserved_cny": "0", "halted": False}
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("Oversized ledger")
            value = _strict_json(raw.decode("utf-8"))
            fields = {"schema_version", "approval_sha256", "attempts",
                      "live_provider_attempts", "reserved_usd", "reserved_cny", "halted"}
            if (type(value) is not dict or set(value) != fields
                    or type(value["schema_version"]) is not int or value["schema_version"] != 2
                    or value["approval_sha256"] != binding):
                raise ValueError("Mismatched ledger")
            usd, cny = (Decimal(value[k]) for k in ("reserved_usd", "reserved_cny"))
            if (type(value["reserved_usd"]) is not str or type(value["reserved_cny"]) is not str
                    or not usd.is_finite() or not cny.is_finite()
                    or not 0 <= usd <= _decimal(self.authorization.total_budget_usd)
                    or not 0 <= cny <= _decimal(self.cny.total_budget_cny)
                    or cny < self._cny_bound(usd)
                    or type(value["attempts"]) is not int
                    or not 0 <= value["attempts"] <= self.authorization.max_calls
                    or type(value["live_provider_attempts"]) is not int
                    or not 0 <= value["live_provider_attempts"] <= value["attempts"]
                    or type(value["halted"]) is not bool
                    or (value["attempts"] == 0) != (usd == 0)
                    or (usd == 0) != (cny == 0)):
                raise ValueError("Invalid ledger")
            return value
        except (ValueError, TypeError, KeyError, InvalidOperation, UnicodeError):
            raise ValueError("CNY ledger corrupt or belongs to another approval") from None

    def reserve(self, amount, live, *, require_existing=False):
        amount = _decimal(amount)
        with self._locked():
            # GUI live intake requires a provisioned ledger. Check while holding
            # the same lock as the reservation, so a missing file cannot reset
            # an exhausted approval between the GUI preflight and this write.
            value = self._read(require_existing=require_existing)
            usd = Decimal(value["reserved_usd"]) + amount
            cny = Decimal(value["reserved_cny"]) + self._cny_bound(amount)
            if (value["halted"] or value["attempts"] >= self.authorization.max_calls
                    or usd > _decimal(self.authorization.total_budget_usd)
                    or cny > _decimal(self.cny.total_budget_cny)):
                raise ValueError("CNY/USD budget or attempt limit exhausted")
            value.update(attempts=value["attempts"] + 1,
                         live_provider_attempts=value["live_provider_attempts"] + int(live),
                         reserved_usd=str(usd), reserved_cny=str(cny))
            self._write(value)
            return value

    def estimated_cny(self, usage):
        if (not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                for k in ("prompt_tokens", "completion_tokens"))):
            raise ValueError("Valid token usage required")
        return ((Decimal(usage["prompt_tokens"]) * _decimal(self.cny.input_cny_per_million)
                 + Decimal(usage["completion_tokens"]) * _decimal(self.cny.output_cny_per_million))
                / Decimal(1000000))
