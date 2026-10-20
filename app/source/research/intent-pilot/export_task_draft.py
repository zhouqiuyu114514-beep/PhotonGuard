"""Bridge the synthetic intent proof to a native, unapproved task worksheet.

Revalidates original bundle/proposal inputs. No approval, lock, model or solver.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

import intent_pilot as pilot


def draft(bundle, proposal, case_id="intent-pilot"):
    pilot.require(type(case_id) is str and
                  re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", case_id), "invalid case ID")
    result = pilot.review(bundle, proposal)
    fields = {field["path"]: field for field in result["fields"]}
    conversions = []

    def value(path):
        field = fields[path]
        if field["state"] != "proposed":
            return None
        exact = field["suggested_value"]
        if field["unit"] == "bool":
            return exact
        number = int(Decimal(exact)) if field["unit"] == "count" else float(Decimal(exact))
        conversions.append({"path": path, "exact_decimal": exact,
                            "task_json_number": number})
        return number

    task = {
        "schema_version": 1, "case_id": case_id,
        "physics": {name: value("physics." + name) for name in pilot.PHYSICS},
        "units_um": value("units_um"),
        "layers": [{"n": value("layers.0.n"),
                    "thickness_um": value("layers.0.thickness_um")}],
        "wavelength_um": [value("wavelength_um.0"), value("wavelength_um.1")],
        "nfreq": value("nfreq"),
        "sources": [{"kind": "synthetic_development_independent_spec",
                     "reference": f"bundle:{result['bundle_sha256']}/document:{doc['id']}",
                     "note": "作者手写的开发规格，文本语义仍待人工核对，未获批准。"}
                    for doc in bundle["documents"] if doc["kind"] == "independent_spec"],
        "intent_note": "未批准的合成开发草稿；依据 intent-review.json 逐项审核后另存为 task.json。",
    }
    # Consult the stable project verifier rather than treating pilot screening as
    # a physical certificate. This core module has no solver or network imports.
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from photonguard.core import POLICY_HASH, digest, task_problem
    validation = task_problem(task)
    result.update(task_draft_sha256=digest(task), policy_sha256=POLICY_HASH,
                  stable_task_schema_check=validation,
                  json_numeric_conversions=conversions,
                  note="这是合成任务草稿导出回执，未经批准；完整性/范围检查不证明文本语义或物理PASS。精确值留存在fields中，任务按现有schema使用JSON数值。")
    return task, result


def export(bundle_path, proposal_path, output_dir, case_id="intent-pilot"):
    bundle = pilot.read_json(bundle_path)
    proposal = pilot.read_json(proposal_path)
    task, result = draft(bundle, proposal, case_id)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    data = {"bundle.original.json": bundle, "proposal.original.json": proposal,
            "task.draft.json": task, "intent-review.json": result}
    for name, item in data.items():
        with (out / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    with (out / "REVIEW.zh.md").open("x", encoding="utf-8") as stream:
        stream.write(REVIEW)
    return result


REVIEW = """# 独立规格任务草稿

本目录是手写合成开发规格的待审表单。没有批准、任务锁、模型调用或求解。
完整样例也必须逐项审核；引用与整行匹配不证明手写事实的文本语义正确。

1. 对照 bundle.original.json、proposal.original.json 和 intent-review.json 核对每项
   原文、来源行、原单位、精确换算值，以及所有未知项、冲突和澄清问题。
2. task.draft.json 对未知、冲突或不支持的量保留 null；脚本观察不会回填意图。
   当前只支持手写合成单层包，不能直接用于真实用户任务或自然语言提取。
3. 任务采用现有 JSON 数值 schema；导出回执保留精确十进制和转换后的数值供核对。
4. 需要补充或澄清时，在新 bundle/新 proposal 中记录独立依据，导出到新目录。
   不要把模型建议、示例参数或脚本观察当作已确认的规格。
5. 实际审核完成后，将草稿另存为 task.json，准确记录 sources 和 intent_note。
   再使用稳定 CLI 的 confirm --approve 创建新锁；导入任务同时传入 --candidate，
   校验来源与谱段。confirm 只是任务确认，只有后续真实 run 才进行物理验收。

本程序未记录真人操作；不能把机器运行时间当成人工审核时间或AI收益。
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("proposal")
    parser.add_argument("--out", required=True)
    parser.add_argument("--case-id", default="intent-pilot")
    args = parser.parse_args()
    try:
        result = export(args.bundle, args.proposal, args.out, args.case_id)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(2, "REJECTED: " + str(exc) + "\n")
    print(json.dumps({"directory": str(Path(args.out).resolve()), "status": result["status"],
                      "task_approved": False, "task_lock_created": False,
                      "stable_task_schema_check": result["stable_task_schema_check"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
