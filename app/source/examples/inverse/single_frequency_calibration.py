"""One small, explicitly approved calibration; no API key or nonlinear solver."""
import argparse
import json
from pathlib import Path
from photonguard.workflow import write_once
from photonguard.experiments import contrast_calibration as c


def main():
    parser=argparse.ArgumentParser(description='单频参照＋独立暗场；结果不是完整观测核')
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--input',type=Path);mode.add_argument('--teaching',action='store_true')
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--approve',action='store_true');args=parser.parse_args()
    if not args.approve:parser.error('运行一次小型线性计算需要 --approve')
    args.out.mkdir(parents=True,exist_ok=False)
    inputs,lesson=c.teaching() if args.teaching else (json.loads(args.input.read_text(encoding='utf-8')),None)
    write_once(args.out/'input.json',inputs)
    write_once(args.out/'resource-plan.json',{'scope':'STANDALONE_CALIBRATION_EXAMPLE_NOT_PRODUCTION_ROOT_RESET','max_linear_reference_fits':1,'nonlinear_fits':0,'model_calls':0})
    if lesson:write_once(args.out/'teaching-lesson.json',lesson)
    try:result=c.analyze(inputs)
    except ValueError as exc:
        write_once(args.out/'result.json',{'status':'REJECTED','reason':str(exc)});raise SystemExit(str(exc)) from None
    write_once(args.out/'result.json',result)
    print(json.dumps({'type':result['type'],'status':result['status'],'estimated_contrast_transfer':result['estimated_contrast_transfer'],'scope':result['scope']},ensure_ascii=False))


if __name__=='__main__':main()
