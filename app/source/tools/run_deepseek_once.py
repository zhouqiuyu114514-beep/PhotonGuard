"""Interactive, single authorized diagnostic. Key is held only in memory."""
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import getpass
import json
import os
from pathlib import Path
import ssl
import sys
import time
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, HTTPSHandler, Request
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photonguard.backend import (ApprovedRates, BackendAuthorization, BackendError,
                                DeepSeekBackend, DeepSeekConfig, _NoRedirects, _redact)
from photonguard.cny_budget import CnyApproval, PersistentCnyLedger
from photonguard.core import load, write_json, digest
from photonguard.exchange import action_to_patch, save_exchange
from photonguard.runner import verify_evidence

SESSION = ROOT / "local-validation/deepseek-live-20261006"
LEDGER = ROOT / "local-validation/deepseek-budget.ledger.json"


def authenticate(key, model):
    """One non-generation GET, same TLS/proxy/redirect policy as live backend."""
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
                          _NoRedirects())
    request = Request("https://api.deepseek.com/models", method="GET",
                      headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with opener.open(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                return {"authenticated": False, "reason": "unexpected_status_or_redirect"}
            raw = response.read(1048577)
            if len(raw) > 1048576:
                return {"authenticated": False, "reason": "oversized_metadata"}
            body = json.loads(raw.decode("utf-8"))
            models = [item["id"] for item in body.get("data", [])
                      if isinstance(item, dict) and isinstance(item.get("id"), str)]
            return {"authenticated": model in models, "http_status": 200,
                    "requested_model_available": model in models,
                    "model_ids": _redact(models, key), "generation_requests": 0}
    except HTTPError as exc:
        code = exc.code
        exc.close()
        return {"authenticated": False, "http_status": code, "generation_requests": 0}
    except Exception:
        return {"authenticated": False, "reason": "authentication_transport_or_json_error",
                "generation_requests": 0}


def interactive_terminal():
    return sys.stdin.isatty() and sys.stderr.isatty()


def run():
    if not interactive_terminal():
        raise ValueError("Run this script in an interactive Ubuntu terminal; key input must not be piped")
    if (SESSION / "summary.json").exists():
        raise ValueError("This session is already finished. No retry or new paid request allowed")
    plan = load(SESSION / "plan.json")
    auth_data = plan["authorization"]
    authorization = BackendAuthorization(**{**auth_data, "rates": ApprovedRates(**auth_data["rates"])})
    ledger = PersistentCnyLedger(authorization, LEDGER, CnyApproval(**plan["cny_approval"]))
    ledger_state = ledger.snapshot()
    if ledger_state["attempts"] or ledger_state["halted"]:
        raise ValueError("An attempt is already reserved; this approval cannot be retried")
    age = (datetime.now(timezone.utc) -
           datetime.fromisoformat(authorization.rates.checked_at.replace("Z", "+00:00"))).total_seconds()
    if not 0 <= age <= 86400:
        raise ValueError("Price approval is stale; refresh the plan before proceeding")
    evidence = ROOT / plan["evidence"]
    request = load(SESSION / "diagnostic-request.json")
    if not verify_evidence(evidence) or digest(request) != plan["diagnostic_request_sha256"]:
        raise ValueError("Evidence or prepared diagnostic request changed")
    print("DeepSeek first diagnostic: deepseek-flash; ONE paid attempt maximum.")
    print("CNY hard limit 0.28; worst-case reservation about 0.278528. No automatic retry.")
    print("Key is not echoed, saved, passed to solver processes, or sent to this chat.")
    warnings.simplefilter("error", getpass.GetPassWarning)
    key = getpass.getpass("Enter DeepSeek API key (hidden): ")
    if not key or not key.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in key):
        raise ValueError("Empty or invalid credential; no provider request sent")
    auth_result = authenticate(key, authorization.model)
    write_json(SESSION / "authentication.json", auth_result)
    if not auth_result["authenticated"]:
        write_json(SESSION / "summary.json", {"status": "AUTHENTICATION_FAILED",
                   "generation_requests": 0, "reserved_cny": "0", "actual_api_cost_cny": "0"})
        print("Authentication failed; no paid generation requested. Inspect sanitized authentication.json.")
        return 3
    print("Authentication succeeded. Sending the single bounded diagnostic...")
    config = DeepSeekConfig(authorization.model, authorization, key, **plan["limits"])
    tick = time.perf_counter()
    try:
        result = DeepSeekBackend(config, ledger=ledger).diagnose(request)
        action, audit = result["action"], result["audit"]
    except BackendError as exc:
        audit = exc.audit
        audit["elapsed_seconds"] = time.perf_counter() - tick
        if audit.get("usage"):
            try: audit["estimated_cost_cny_peak_cache_miss"] = str(ledger.estimated_cny(audit["usage"]))
            except ValueError: pass
        write_json(SESSION / "provider.audit.json", _redact(audit, key))
        write_json(SESSION / "summary.json", {"status": "DIAGNOSTIC_STOPPED",
                   "provider_status": audit["status"], "actual_llm_calls": audit["actual_llm_calls"],
                   "budget": ledger.snapshot(), "cost_is_provider_bill": False,
                   "note": "Failed/unknown dispatch retains its full reservation; no retry"})
        print("Diagnostic stopped. Full reservation retained; no retry. No candidate changed.")
        return 3
    audit["elapsed_seconds"] = time.perf_counter() - tick
    audit["estimated_cost_cny_peak_cache_miss"] = str(ledger.estimated_cny(audit["usage"]))
    audit["cny_approval"] = plan["cny_approval"]
    write_json(SESSION / "provider.audit.json", _redact(audit, key))
    write_json(SESSION / "response.action.json", _redact(action, key))
    provenance = {"mode": "deepseek_api", "model_identity": audit["provider_model"],
                  "requested_model": authorization.model, "api_calls": 1,
                  "runtime_api_calls": 1, "request_payload_sha256": digest(request),
                  "provider_audit": audit}
    try:
        patch = action_to_patch(evidence, request, action, provenance)
    except ValueError as exc:
        write_json(SESSION / "summary.json", {"status": "ACTION_REJECTED", "reason": str(exc),
                   "actual_llm_calls": 1, "budget": ledger.snapshot(),
                   "estimated_cost_cny_peak_cache_miss": audit["estimated_cost_cny_peak_cache_miss"],
                   "cost_is_provider_bill": False})
        print("Model action rejected. No change or retry; sanitized evidence saved.")
        return 3
    save_exchange(SESSION / "exchange", request, action, provenance, patch)
    if patch is not None:
        write_json(SESSION / "proposal.json", patch)
    summary = {"status": "PROPOSAL_READY" if patch else "NO_PATCH", "actual_llm_calls": 1,
               "provider_model": audit["provider_model"],
               "provider_completion_id": audit.get("response_json", {}).get("id"),
               "usage": audit["usage"], "budget": ledger.snapshot(),
               "estimated_cost_cny_peak_cache_miss": audit["estimated_cost_cny_peak_cache_miss"],
               "cost_is_provider_bill": False, "candidate_modified": False}
    write_json(SESSION / "summary.json", _redact(summary, key))
    print("Diagnostic saved. Model proposal requires review before any patch or solver run.")
    print("Estimated peak/cache-miss CNY cost:", audit["estimated_cost_cny_peak_cache_miss"])
    key = None
    return 0


def main():
    # Serialize the whole interactive session; no second prompt or parallel call.
    fd = os.open(SESSION / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            return run()
        except (ValueError, OSError, getpass.GetPassWarning):
            print("Preflight stopped. No automatic retry. Check terminal, prepared files and budget state.")
            return 3
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
