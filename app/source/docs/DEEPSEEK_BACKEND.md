# DeepSeek runtime adapter: opt-in; one live local integration recorded

## Offline safety correction, 2026-10-06

The `safety-intent-20261006` branch fixes credential-bearing property names,
escaped inner JSON and non-string action decisions. `_redact` quarantines an
entire affected mapping instead of renaming and colliding keys, parses embedded
JSON before scrubbing, and bounds recursion. Unicode-escaped strings and keys
are covered, including nested containers; invalid Unicode scalars reject.

New audits **omit raw provider bodies**, including HTTP errors, invalid JSON,
redirects, truncated and oversized bodies. `response` is always null. Raw byte
hash/count and prefix-vs-full hash scope remain available. `response_json` is a
reconstruction containing typed whitelist metadata and, only after parsing,
the same sanitized action used at persistence exits. It is not the original
envelope. Unknown metadata, unparsed content and arbitrary exception messages
are not retained. Old recorded audits/ZIPs are frozen and remain unchanged.

`decision` must be a string before enum membership; objects, arrays, null,
booleans and numbers follow the existing ValueError rejection path. Both CLI
surfaces retain controlled rejection records and the full used reservation.
Unknown action fields are still rejected; no automatic removal of `type` or
automatic candidate repair was added. This correction makes zero new API calls.

Coverage does not establish scrubbing of arbitrary encryption/base64/custom
encodings, hostile filesystem protection, or successful recording after process
termination, out-of-memory or a disk that cannot be written. References in
intake proposals still require semantic human review.

## Live outcome, 2026-10-06

Authenticated `/models` returned 200 and exposed `deepseek-flash`. Exactly one
live completion returned 200 in 2.181 seconds: completion ID
`b9a1c177-6100-415b-b1fc-e0648fc7833c`, 2,155 prompt tokens, 216 completion tokens,
no reported cache hits. The peak/cache-miss CNY estimate is **0.006038**, not an
account invoice. The ledger retains its full 0.278528000001 CNY reservation and
one used attempt. No retries, fallback, additional model calls or credential
storage occurred. Starting the same launcher again stops before credential input.

The provider action was **rejected by the unchanged strict validator** because
it contained the extra top-level field `type: "json_object"`. Raw response,
rejection summary and ledger remain unchanged. A separate, explicit offline
Codex review removed only that field, retaining all four action fields verbatim.
Its rationale's opening claim that only `task_parameters` failed is inaccurate:
four TMM checks also failed, which the rationale later acknowledges and cites.
The one proposed epsilon 2 to 4 repair matches the independently locked n=2 task.

The reviewed action passed the original schema/evidence/bounded-patch validators
and was explicitly applied only to the bundled synthetic candidate. Eight fresh
Meep runs produced PASS (`20261006T020605Z-d87c87a0`), with maximum TMM error
0.0008715755569460581 below the unchanged 0.01 tolerance. Both original and new
evidence verify; task, policy, original candidate, input bytes and live audit
hashes remain unchanged. This is **integration with an offline format review**,
not an unassisted end-to-end model success, a human trial or incremental AI benefit.

Evidence: `local-validation/deepseek-live-20261006/provider.audit.json`,
`summary.json` (raw rejection), `offline-review/review.json`,
`offline-review/result.json`, and the new artifact. The review script has no
provider transport and performs zero additional API calls.

## Local single-call integration entry, 2026-10-06

The verified WSL project now includes `tools/run_deepseek_once.py` and the
Windows launcher `START_DEEPSEEK_ONCE.ps1`. The prepared session lives under
`local-validation/deepseek-live-20261006`; it uses the already verified synthetic
FAIL evidence. The user approved starting the proposed one-call diagnostic,
with a **CNY 0.28** application budget. This is a narrower approval than the
historical handoff's CNY 20 record, not an additional CNY 20 authorization.

The launcher requests a hidden credential with Python `getpass` in an interactive
Ubuntu terminal. It refuses piped/noninteractive input and does not persist the
key, put it in command arguments or environment variables, or pass it to solver
processes. The key is used for one authenticated, non-generation `GET /models`
and, only on successful authentication and model availability, one diagnostic.
The live backend's certificate verification, redirect refusal and direct
transport remain in force; no provider fallback or automatic retry is added.

`PersistentCnyLedger` extends the existing locked/atomic persistent ledger with
both USD and CNY reservations in **one file with one attempt counter**:
`local-validation/deepseek-budget.ledger.json`. It binds the original USD
authorization plus the dated official CNY tariffs and CNY cap. Official peak,
cache-miss rates checked on 2026-10-06 are USD 0.30 / 1.20 and CNY 2 / 8 per
million input/output tokens. The ledger translates the backend's USD
reservation using an upward-rounded maximum ratio of the paired tariffs;
this is a tariff ratio, not a foreign-exchange quote. CNY usage estimates are
calculated directly from CNY token rates, assuming peak and cache misses.
With 131,072 reserved input and 2,048 maximum output tokens, the USD reserve is
0.0417792 and the conservative CNY reserve is 0.278528000001. Failed attempts
and timeouts retain that reserve and the single attempt; no refunds or reset.
These estimates are not a provider invoice or account-wide spending guarantee.

The script saves sanitized authentication, request/response, provider identity,
completion ID, full usage and elapsed time. Validated proposals remain proposals:
the script never applies a patch or runs Meep automatically. Review must precede
an explicitly approved bounded patch and complete independent numerical rerun.
This one synthetic integration does not establish AI incremental benefit.

The prior sections below describe the original adapter and its historical
2026-10-05 state; current live outcomes are recorded in the local session audit.

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
- The audit preserves the transmitted safe payload and its hash, raw response byte hash/count, typed whitelist metadata, sanitized parsed action, model identifiers, token usage, finish reason, reservation, rates, estimated cost, transport kind, and final status. Raw response text is omitted
- Secret fields, known key echoes, bearer tokens, property names and escaped embedded JSON are handled by the shared bounded scrubber. Authorization headers and the key are not included in audit or exception messages. Hashes refer to received bytes, not the reconstructed safe response. An oversized response retains only a labeled prefix hash/count, never prefix content
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
