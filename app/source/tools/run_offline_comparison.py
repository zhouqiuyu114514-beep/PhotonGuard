"""Offline mock smoke test or immutable receipt accounting; no live mode."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photonguard import workflow_intake as intake, workflow_model as model
from photonguard.comparison_report import summarize
from photonguard.workflow import write_once

PLAN = [{'slot': i + 1, 'case': case, 'arm': arm}
        for i, (case, arm) in enumerate((('complete', 'A0'), ('complete', 'A1'),
                                         ('conflict', 'A0'), ('conflict', 'A1')))]


def simulate():
    # Public synthetic inputs only; the same view and dispatcher for both arms.
    texts = {'complete': intake.DEMO,
             'conflict': intake.DEMO.replace('膜厚为300 nm。\n', '') + '\n膜层折射率为3。'}
    views = {name: intake.prepare('PG-OFFLINE-V3-' + name, text)['view']
             for name, text in texts.items()}
    for view in views.values():
        view['packet']['synthetic'] = True
        view.pop('input_sha256')
        view['input_sha256'] = intake.semantic.digest(view)
    records = []
    for item in PLAN:
        view = views[item['case']]
        response = model.DeepSeekSemanticAdapter(mock_transport=model.RuleMockTransport()).run(view, mode='adapter_mock', arm=item['arm'])
        reviewed = intake.model_result({'view': view, 'result': None, 'confirmation': None}, response)
        records.append(dict(item, input_sha256=view['input_sha256'],
            status=response['status'], review_status=reviewed['status'],
            result=reviewed.get('result'), error=reviewed.get('error'),
            rejection_code=reviewed.get('rejection_code'),
            response_evidence=reviewed.get('response_evidence'),
            adapter_audit=reviewed['adapter_audit'], solver_calls=0))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--simulate', action='store_true')
    mode.add_argument('--receipts', type=Path, help='Read-only original session directory')
    parser.add_argument('--output', type=Path, required=True, help='A new, nonexistent directory')
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Output already exists; never overwrite prior observations')
    if args.simulate:
        records = simulate()
    else:
        # This schema is the previously approved, fixed four-slot batch only.
        old_plan = json.loads((args.receipts / 'plan.json').read_text(encoding='utf-8'))
        if old_plan.get('reference') != 'semantic-small-gui-20261006-approved-8req-3cny':
            parser.error('Unsupported receipt plan; do not infer slot identities')
        records = [json.loads(p.read_text(encoding='utf-8'))
                   for p in sorted(args.receipts.glob('slot-*-result.json'))]
    summary = summarize(PLAN, records)
    summary['mode'] = 'MOCK_RULES_NOT_AI' if args.simulate else 'READ_ONLY_HISTORICAL_RECEIPTS'
    args.output.mkdir(parents=True, mode=0o700)
    write_once(args.output / 'plan.json', {'tasks': PLAN, 'mode': summary['mode']})
    if args.simulate:
        for item in records:
            write_once(args.output / ('slot-%02d-result.json' % item['slot']), item)
    write_once(args.output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
