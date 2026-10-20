"""Shared CLI for the three source-package examples; never imports an API client."""
import argparse
import json
from . import reuse


def main(model):
    p = argparse.ArgumentParser(description='Bounded offline inverse example; no API key or UI required')
    p.add_argument('--csv')
    p.add_argument('--plan')
    p.add_argument('--out', required=True)
    p.add_argument('--approve', action='store_true')
    p.add_argument('--strategy', choices=['default', 'fixed'], default='default')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--followup')
    p.add_argument('--inspect', action='store_true')
    args = p.parse_args()
    if args.inspect:
        if args.resume or args.followup or args.csv or args.plan or args.approve:
            p.error('--inspect only reads an existing --out directory')
        state = reuse.inspect(args.out)
        if state['spec']['settings']['model'] != model:
            p.error('Saved workflow model does not match this entry point')
    elif args.resume:
        if not args.followup or args.csv or args.plan or args.strategy != 'default':
            p.error('--resume requires only --followup, --out and --approve; the saved plan is immutable')
        if reuse.inspect(args.out)['spec']['settings']['model'] != model:
            p.error('Saved workflow model does not match this entry point')
        state = reuse.followup(args.out, args.followup, approve=args.approve)
    else:
        if not args.csv or not args.plan or args.followup:
            p.error('Initial run needs --csv, --plan, --out and --approve')
        state = reuse.run(args.csv, reuse.read_json(args.plan), args.out, approve=args.approve,
                          expected_model=model,
                          strategy=reuse.fixed_strategy if args.strategy == 'fixed' else None)
    print(json.dumps({'status': state['status'], 'reserved': state['reserved'],
                      'actual_residual_calls': state['actual_residual_calls'],
                      'model_requests': 0, 'saved': args.out,
                      'next_positions': state.get('approved_observation_positions')}, ensure_ascii=False))
