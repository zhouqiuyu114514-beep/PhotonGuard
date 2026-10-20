"""Two hand-authored development fixtures, never model or human-study output.
SPDX-License-Identifier: GPL-2.0-or-later
Run only in a new fixture directory: python3 make_development_fixtures.py DIR
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

from intent_pilot import PATHS, digest


ROWS = [
    ("physics.dimensions", 1, "count", "独立规格：一维模型。"),
    ("physics.angle_deg", 0, "deg", "独立规格：入射角为0度。"),
    ("physics.lossless", True, "bool", "独立规格：材料无损。"),
    ("physics.dispersive", False, "bool", "独立规格：材料无色散。"),
    ("physics.isotropic", True, "bool", "独立规格：材料各向同性。"),
    ("physics.mu", 1, "1", "独立规格：相对磁导率为1。"),
    ("physics.n_incident", 1, "1", "独立规格：入射介质折射率为1。"),
    ("physics.n_exit", 1, "1", "独立规格：出射介质折射率为1。"),
    ("units_um", 1000, "nm", "独立规格：每Meep单位对应1000 nm。"),
    ("layers.0.n", 2, "1", "独立规格：唯一膜层的预期折射率n为2。"),
    ("layers.0.thickness_um", 0.0002, "mm", "独立规格：唯一膜层厚度0.0002 mm。"),
    ("wavelength_um.0", 500, "nm", "独立规格：波长下限500 nm。"),
    ("wavelength_um.1", 0.9, "um", "独立规格：波长上限0.9 um。"),
    ("nfreq", 21, "count", "独立规格：21个频点。"),
]


def base_bundle():
    return {"schema_version": 1, "kind": "synthetic_development",
            "documents": [{"id": "spec", "kind": "independent_spec",
                           "lines": [row[3] for row in ROWS]},
                          {"id": "script", "kind": "ast_observation",
                           "lines": ["手写的合成AST观察：脚本使用index=1.45；这不是独立意图。"]}],
            "facts": [{"id": f"spec-{i + 1:02}", "path": row[0], "value": row[1],
                       "unit": row[2], "source": {"document_id": "spec", "line": i + 1,
                                                   "quote": row[3]}}
                      for i, row in enumerate(ROWS)] + [
                          {"id": "script-n", "path": "layers.0.n", "value": 1.45,
                           "unit": "1", "source": {"document_id": "script", "line": 1,
                                                     "quote": "手写的合成AST观察：脚本使用index=1.45；这不是独立意图。"}}]}


def handwritten_proposal(bundle, states):
    # Author-specified expectations, not output from review() or a model.
    return {"schema_version": 1, "kind": "handwritten_mock", "bundle_sha256": digest(bundle),
            "fields": [{"path": path, "state": states.get(path, "proposed"),
                        "evidence_ids": [fact["id"] for fact in bundle["facts"]
                                         if fact["path"] == path and fact["id"] != "script-n"]}
                       for path in PATHS]}


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=False)
    complete = base_bundle()
    blocked = deepcopy(complete)
    blocked["facts"] = [f for f in blocked["facts"] if f["id"] != "spec-10"]
    blocked["documents"][0]["lines"][9] = "独立规格：尚未提供膜层折射率。"
    thickness = next(f for f in blocked["facts"] if f["id"] == "spec-11")
    thickness["value"], thickness["unit"] = 200, None
    text = "独立规格：膜层厚度写为200，单位尚未提供。"
    thickness["source"]["quote"] = text
    blocked["documents"][0]["lines"][10] = text
    text = "另一份独立规格写波长上限为1100 nm，与原规格冲突，尚未确认优先级。"
    blocked["documents"].append({"id": "spec-other", "kind": "independent_spec", "lines": [text]})
    blocked["facts"].append({"id": "spec-conflict", "path": "wavelength_um.1", "value": 1100,
                             "unit": "nm", "source": {"document_id": "spec-other", "line": 1,
                                                       "quote": text}})
    for name, bundle, states in (
        ("complete", complete, {}),
        ("needs-clarification", blocked, {"layers.0.n": "unknown",
                                         "layers.0.thickness_um": "unknown",
                                         "wavelength_um.1": "conflict"}),
    ):
        proposal = handwritten_proposal(bundle, states)
        for suffix, data in (("bundle", bundle), ("mock", proposal)):
            with (out / f"{name}.{suffix}.json").open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
