"""Coordinator-only, local development recorder. No provider client or solver.

Real observations are deliberately disabled until a separately authorized runner
and isolation have been reviewed. All outputs, including rejected ones, count.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

PILOT = Path(__file__).resolve().parents[1] / 'intent-pilot'
sys.path.insert(0, str(PILOT))
sys.path.insert(0, str(PILOT.parents[1]))
import semantic_intake as adapter
from photonguard.backend import _redact, _scrub_text

ARMS = ('R0', 'A0', 'A1')
STAGES = ('raw_initial', 'raw_clarified', 'human_corrected')
PROVENANCE = ('CONSTRUCTED_TEST', 'HANDWRITTEN_TEST')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_new(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def sensitive(data):
    """Conservative credential-shape gate, not proof against custom encodings.

    Only assistant candidate content belongs here, never a provider HTTP body,
    headers, key, or auth envelope. The caller must attest this separately.
    Malformed credential-free candidate content remains archivable/scorable.
    """
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        return True
    decoded = text
    for _ in range(32):
        if _scrub_text(decoded, None) != decoded:
            return True
        expanded = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), decoded)
        if expanded == decoded:
            break
        decoded = expanded
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        return False
    return _redact(obj, None) != obj


def record_attempt(root, *, attempt_id, arm, stage, view, trusted_hash,
                   raw, evaluator, evaluator_root, delivered=(),
                   provenance='CONSTRUCTED_TEST', candidate_content_attested=False,
                   stop_reason=None):
    """Archive first, then score original bytes and independently run adapter.

    A reserved attempt directory is the denominator, even if processing crashes.
    A missing result is reported as INCOMPLETE instead of being filtered out.
    This development entry point cannot accept OBSERVED_MODEL/HUMAN records.
    """
    if arm not in ARMS or stage not in STAGES or provenance not in PROVENANCE:
        raise ValueError('unapproved arm, stage or real observation')
    if not candidate_content_attested:
        raise ValueError('credential-free candidate-content attestation required')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', attempt_id):
        raise ValueError('invalid attempt identifier')
    if raw is not None and not isinstance(raw, bytes):
        raise TypeError('raw bytes required')
    directory = Path(root) / attempt_id
    directory.mkdir(parents=True, exist_ok=False)
    meta = {'attempt_id': attempt_id, 'arm': arm, 'stage': stage,
            'case_id': view['packet']['case_id'], 'provenance': provenance,
            'recorded_utc': datetime.now(timezone.utc).isoformat(),
            'trusted_input_sha256': trusted_hash, 'delivered': list(delivered),
            'candidate_sha256': sha(raw) if raw is not None else None,
            'candidate_bytes': len(raw) if raw is not None else 0,
            'candidate_content_attested': True, 'provider_body_retained': False,
            'counts_in_attempt_denominator': stage != 'human_corrected',
            'model_calls': 0, 'solver_calls': 0, 'human_active_seconds': None}
    write_new(directory / 'attempt.json', meta)
    write_new(directory / 'visible-view.json', view)
    if raw is None:
        if stop_reason not in ('BUDGET_STOP', 'NO_RETURN', 'TRANSPORT_FAILURE'):
            raise ValueError('missing return needs a controlled reason')
        score = {'evaluation_validity': 'SCORABLE', 'outcome': stop_reason,
                 'critical_contract_failure': True}
        tool = {'status': 'NOT_RUN', 'reason': stop_reason}
    elif len(raw) > 4 * 1024 * 1024 or sensitive(raw):
        # Safety stop still counts; do not reintroduce unsafe raw-provider storage.
        score = {'evaluation_validity': 'SCORABLE', 'outcome': 'SAFETY_STOP',
                 'critical_contract_failure': True,
                 'raw_storage': 'OMITTED_UNTRUSTED_CONTENT_HASH_RETAINED'}
        tool = {'status': 'NOT_RUN', 'reason': 'SAFETY_STOP'}
    else:
        candidate = directory / 'raw-candidate.bin'
        with candidate.open('xb') as stream:
            stream.write(raw)
        try:
            adapter.validate_view(view, trusted_hash)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            score = {'evaluation_validity': 'UNSCORABLE',
                     'outcome': 'COORDINATOR_VIEW_FAILURE'}
            tool = {'status': 'NOT_RUN', 'reason': 'COORDINATOR_VIEW_FAILURE'}
        else:
            try:
                original = evaluator.read(candidate)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                score = {'evaluation_validity': 'SCORABLE',
                         'outcome': 'OUTPUT_CONTRACT_FAILURE',
                         'critical_contract_failure': True,
                         'contract_errors': ['invalid original candidate JSON']}
            else:
                try:
                    score = evaluator.evaluate(original, meta['case_id'],
                                               delivered, root=Path(evaluator_root))
                except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError):
                    score = {'evaluation_validity': 'UNSCORABLE',
                             'outcome': 'EVALUATOR_CONTEXT_FAILURE'}
            # Import cannot decide whether original candidate is counted/scored.
            try:
                tool = adapter.receipt(view, adapter.read(candidate, decimal_numbers=True), trusted_hash)
            except (ValueError, TypeError, OSError, UnicodeError, RecursionError):
                tool = {'status': 'REJECTED', 'reason': 'INVALID_CANDIDATE',
                        'task_approved': False, 'task_lock_created': False}
            if 'normalized_response' in tool:
                write_new(directory / 'tool-normalized.json', tool['normalized_response'])
    write_new(directory / 'raw-score.json', score)
    write_new(directory / 'tool-receipt.json', tool)
    write_new(directory / 'result.json', {'raw_outcome': score['outcome'],
        'evaluation_validity': score['evaluation_validity'],
        'tool_status': tool['status'], 'raw_candidate_replaced': False})
    return directory


def summarize(root, planned_cases):
    """Show all planned cases and all attempts, including crash reservations.

    Stage counts are separate; human revisions never replace initial performance.
    No acceptance-conditioned accuracy or automatic human cost estimate exists.
    """
    summary = {}
    rows = []
    for path in sorted(Path(root).glob('*/attempt.json')):
        meta = json.loads(path.read_text(encoding='utf-8'))
        result = path.parent / 'result.json'
        meta['result'] = json.loads(result.read_text(encoding='utf-8')) if result.exists() else {
            'raw_outcome': 'INCOMPLETE', 'tool_status': 'NOT_FINISHED'}
        rows.append(meta)
    for arm in ARMS:
        current = [r for r in rows if r['arm'] == arm and r['counts_in_attempt_denominator']]
        case_rows = {case: [r for r in current if r['case_id'] == case] for case in planned_cases}
        summary[arm] = {'planned_case_denominator': len(planned_cases),
            'cases_with_attempts': sum(bool(r) for r in case_rows.values()),
            'pending_cases': [case for case, r in case_rows.items() if not r],
            'attempt_denominator': len(current),
            'raw_outcomes': dict(Counter(r['result']['raw_outcome'] for r in current)),
            'tool_outcomes': dict(Counter(r['result']['tool_status'] for r in current)),
            'stages': {stage: sum(r['arm'] == arm and r['stage'] == stage for r in rows) for stage in STAGES},
            'attempts': current, 'human_active_seconds': None,
            'rule_extracted_field_count': None}
    return {'scope': 'PUBLIC_SEMANTIC_INTAKE_ONLY',
            'provenance': 'OFFLINE_DEVELOPMENT_ONLY', 'arms': summary,
            'model_calls': 0, 'solver_calls': 0, 'ai_gain': 'NOT_MEASURED'}
