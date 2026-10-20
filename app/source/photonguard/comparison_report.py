"""Count every planned task, returned candidate and rejected submission."""


def summarize(plan, records):
    planned = {item['slot']: item for item in plan}
    if len(planned) != len(plan):
        raise ValueError('Duplicate planned slot')
    by_slot = {}
    for record in records:
        slot = record['slot']
        if slot not in planned or slot in by_slot:
            raise ValueError('Unknown or duplicate result slot')
        if any(record[k] != planned[slot][k] for k in ('case', 'arm')):
            raise ValueError('Result does not match planned input and arm')
        by_slot[slot] = record
    tasks = []
    submission_count = 0
    sanitized_submission_count = 0
    for slot, item in planned.items():
        record = by_slot.get(slot)
        if record is None:
            tasks.append(dict(item, outcome='NOT_RUN', final_returned=False,
                              provider_requests=0, original_response_available=False))
            continue
        audit = record.get('adapter_audit', {})
        submissions = audit.get('submissions', [])
        submission_count += len(submissions)
        sanitized_submission_count += sum(s.get('response_evidence', {}).get('body_storage') == 'SANITIZED_PARSED_JSON' for s in submissions)
        calls = sum(a.get('live_dispatch') is True for a in audit.get('audits', []))
        final = record.get('status') == 'FINAL_RETURNED'
        review = record.get('review_status')
        outcome = 'REVIEW_PENDING' if final and review == 'REVIEW' else 'REJECTED' if final and review == 'FAILED' else 'STOPPED'
        evidence = record.get('response_evidence') or (record.get('result') or {}).get('response_evidence') or {}
        tasks.append(dict(item, outcome=outcome, final_returned=final,
                          provider_requests=calls,
                          rejection_code=record.get('rejection_code') or ('LEGACY_UNSPECIFIED' if outcome == 'REJECTED' else None),
                          sanitized_response_available=evidence.get('body_storage') == 'SANITIZED_PARSED_JSON',
                          original_response_available=evidence.get('body_is_original_response') is True))
    return {'schema_version': 1, 'planned_tasks': len(tasks),
            'attempted_tasks': len(records),
            'returned_final_candidates': sum(t['final_returned'] for t in tasks),
            'review_pending_tasks': sum(t['outcome'] == 'REVIEW_PENDING' for t in tasks),
            'rejected_tasks': sum(t['outcome'] == 'REJECTED' for t in tasks),
            'stopped_tasks': sum(t['outcome'] == 'STOPPED' for t in tasks),
            'not_run_tasks': sum(t['outcome'] == 'NOT_RUN' for t in tasks),
            'provider_requests': sum(t['provider_requests'] for t in tasks),
            'candidate_submissions': submission_count,
            'sanitized_candidate_submissions': sanitized_submission_count,
            'tasks': tasks, 'semantic_correctness_scored': False,
            'r0_available': False, 'human_cost_available': False,
            'ai_advantage_established': False}
