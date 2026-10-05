# DeepSeek runtime adapter: opt-in, unconfigured

## What has and has not been verified

As of 2026-10-05, this adapter has made **zero live DeepSeek calls**. No real credential has been read or inspected, and no API spending or secure credential handoff has been authorized. Its tests use synthetic responses and injected mock transport. They demonstrate local transport/guardrail compatibility only, not live API compatibility, model diagnostic accuracy, an autonomous repair loop, or a working autonomous AI product.

The product runtime can explicitly select DeepSeek. It does not change the assistant or developer's own model. The independent physics verifier and its acceptance policy are not modified by this adapter.

## Verified provider contract

The official [models and pricing page](https://api-docs.deepseek.com/quick_start/pricing/) was checked on 2026-10-05. It lists `deepseek-flash` (currently DeepSeek-V4.1-Flash) and `deepseek-v4-pro`, with the OpenAI-format base URL `https://api.deepseek.com`. An explicit model is required in both configuration and approval; there is no model default, obsolete alias fallback, or automatic provider fallback.

The official [JSON Output guide](https://api-docs.deepseek.com/zh-cn/guides/json_mode/) requires `response_format={"type":"json_object"}`, a prompt containing `json` and an output example, and a bounded `max_tokens`. It warns that content can be empty. This adapter supplies those fields and fails on empty or malformed content without retrying.

[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) and [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) document `thinking.type="disabled"`. This adapter explicitly selects that mode, disables streaming, and exposes no model tools.

## Interface and approval boundary

`DeepSeekBackend(DeepSeekConfig(...), ledger=...).diagnose(request)` returns `{"action": ..., "audit": ...}`. `BackendError` carries a sanitized `.audit` on blocked and failed attempts. The backend never reads credentials from environment variables, configuration files, keychains, or other locations. A caller must supply the key explicitly through an authorized secure setup.

The input is the sanitized export from `photonguard.exchange.export_request`. Only `prompt`, `task`, `candidate`, `observations`, and `allowed_actions` become the provider payload. Diagnostic metadata is retained by the surrounding exchange. The transport does not include arbitrary extra top-level fields, files, benchmark labels, or answer keys. The export layer, rather than this generic transport, is responsible for constructing scientifically appropriate evidence and excluding hidden labels.

Explicit configuration uses these dataclasses:

- `ApprovedRates(input_usd_per_million, output_usd_per_million, checked_at, source)`
- `BackendAuthorization(approved, reference, model, total_budget_usd, max_calls, rates)`
- `DeepSeekConfig(model, authorization, api_key, endpoint, timeout_seconds, max_request_bytes, max_response_bytes, max_tokens, input_token_reservation)`
- `PersistentBudgetLedger(authorization, ledger_path)` for live CLI use
- `BudgetLedger(authorization)` for an explicitly bounded in-process session, including tests

Authorization requires a nonempty approval reference, the exact requested model, an explicitly positive USD budget, explicit positive approved worst-case input and output rates with their dated official source, and one or two maximum attempts. Merely constructing an object does not obtain user approval. The application must first obtain approval for the specific provider, diagnostic data transmission, model, and spending limit. A hypothetical project budget is not API spending permission.

The CLI requires `--approve-data-and-cost`, a non-secret configuration, and a persistent ledger path. The credential environment is only consulted by that explicit approved CLI action, not by imports, tests, or the backend. Secure credential setup remains pending. Never paste or commit an API key into source, a JSON configuration, audit files, or a chat.

A deliberately non-authorizing configuration example is below. It is blocked as written; do not change approval or budget fields unless the user has actually authorized them.

```json
{
  "model": "deepseek-flash",
  "authorization": {
    "approved": false,
    "reference": "REQUIRES-EXPLICIT-APPROVAL",
    "model": "deepseek-flash",
    "total_budget_usd": "0",
    "max_calls": 1,
    "rates": {
      "input_usd_per_million": "0.30",
      "output_usd_per_million": "1.20",
      "checked_at": "2026-10-05",
      "source": "https://api-docs.deepseek.com/quick_start/pricing/"
    }
  },
  "limits": {
    "timeout_seconds": 30,
    "max_request_bytes": 65536,
    "max_response_bytes": 1048576,
    "max_tokens": 2048,
    "input_token_reservation": 131072
  }
}
```

The rates in this disabled example are the Flash peak, cache-miss input and peak output rates observed on the stated date. Recheck pricing before approval; rates are not hardcoded as an authorization or an assumption about the user's account.

## Conservative budget and persistent attempts

Each attempt first reserves:

`(input_token_reservation × approved_input_rate + max_tokens × approved_output_rate) / 1,000,000 USD`

The input reservation must cover the complete serialized request byte cap plus 1,024 framing tokens. ASCII-safe JSON encoding intentionally over-reserves non-ASCII text. The default input reservation is 131,072 tokens for a maximum 65,536-byte request. This conservative byte-based bound and framing allowance are assumptions for this text-only endpoint, not a provider billing guarantee.

At the disabled example rates and limits, one full reservation is **$0.0417792**, regardless of whether the actual request is smaller. A smaller approved remaining budget blocks the attempt before networking. Failed requests, timeouts, HTTP errors, empty responses, and successful lower-token responses all retain their full reservation and count toward the maximum of two attempts. There are no automatic retries. Actual token counts exceeding a reservation halt further attempts.

The persistent ledger reserves under a POSIX exclusive file lock, atomically writes and fsyncs before transport, and binds its state to the approval reference, model, total budget, call cap, rates, and rate-source timestamp. Repeated processes must reuse the **same path for the same approval**. Corrupt, mismatched, exhausted, or symlinked ledger files fail closed. Existing ledgers are never silently reset. The in-memory ledger is not sufficient to enforce a budget across separate CLI processes.

This is an application-level cap, not an account-wide or provider-side spending limit. A user deleting/changing the ledger or choosing another path can bypass continuity. Keep the ledger in a user-controlled project directory; the file lock is not a hostile-filesystem security boundary. Pricing changes or provider usage outside the stated bounds can exceed the estimate, so an appropriately configured provider-side spending limit remains a separate safeguard. No such setting has been changed here.

## Network, timeout, and audit behavior

- The only permitted URLs are the official HTTPS `/chat/completions` and `/v1/chat/completions` endpoints on `api.deepseek.com`
- Certificate and hostname verification remain enabled. Environment proxies are not inherited
- All redirects, including same-host redirects, are refused. Credentials are never forwarded to a redirect target
- No retries, streaming, tool execution, SDK dependencies, or automatic fallback are used
- Request bytes, response bytes, output tokens, and attempt count are bounded
- `timeout_seconds` is a socket-operation timeout, capped at 60 seconds, with an elapsed deadline checked between response chunks. It is **not a strict whole-process wall-clock limit**: a blocking operation started near that deadline, or operating-system DNS behavior, can extend overall elapsed time
- The audit preserves the transmitted safe payload and its hash, bounded actual response text and its hash, parsed provider envelope, requested and returned model identifiers, token usage, finish reason, reservation, rates, estimated cost, transport kind, and final status
- Secret fields, known key echoes, and bearer tokens are redacted. Authorization headers and the key are never included in audit or exception messages. A redacted JSON response may be reserialized; its hash still refers to received bytes. An oversized response keeps a labeled bounded prefix and prefix hash
- `estimated_cost_usd` uses approved worst-case rates and is not an actual provider invoice
- `actual_llm_calls` is zero for preflight blocks and injected mocks, one for a live provider envelope that identifies a model and completion, and null when a live attempt has no usable model response. A timeout is not evidence that zero calls were processed or billed. The ledger separately records all attempted dispatches

Injected transport is a trusted, offline-test extension point, labeled `injected_mock`. Arbitrary injected Python code is outside the default network transport's security boundary. The CLI refuses to present injected responses as live model evidence.

## Independent acceptance remains mandatory

A successful `diagnose` means only that a provider response was received and decoded. It does not approve the action, apply a patch, rerun a solver, or establish PASS. The audit explicitly records `action_validation="pending_independent_validator"`.

The exchange layer checks the strict action schema, cited evidence IDs, original task/candidate/policy hashes, allowed paths and values, and patch-round bounds. An accepted proposal still needs explicit patch approval and complete independent numerical reverification. It cannot modify the verifier, tolerance policy, reference calculation, original intent, or source code.

## Offline verification

Run the local compatibility tests with:

```sh
.runtime/run-python -m pytest tests/test_backend.py -q
```

The suite prohibits live socket connections and covers approval and credential gates, byte/token/timeout bounds, strict JSON parsing, empty and incomplete output, provider errors, redirect refusal, key redaction, conservative nonrefundable reservations, shared/persistent budgets, concurrent atomic reservation, corrupt/mismatched ledger handling, and the default TLS/proxy settings using synthetic transport objects.

These checks are not the still-pending authorized DeepSeek integration test or a controlled model evaluation. No claim about autonomous repair success follows from them.
