"""Unapproved intent worksheet and explicit CLI confirmation; no model or solver."""
from __future__ import annotations

import json
from pathlib import Path

from .core import POLICY_HASH, candidate_problem, digest, load, task_problem, write_json
from .script_import import decode_source, preview_bytes, validate_provenance

PHYSICS_FIELDS = ("dimensions", "angle_deg", "lossless", "dispersive",
                  "isotropic", "mu", "n_incident", "n_exit")


def prepare_task(candidate_path, output_dir):
    """Prepare an empty task form from a freshly verified, unmodified import."""
    candidate = load(candidate_path)
    problem = candidate_problem(candidate)
    if problem:
        raise ValueError(problem["reason"])
    info = candidate.get("origin", {}).get("script_import")
    raw = decode_source(info)
    preview = preview_bytes(raw, info.get("source_name", "input.py"))
    if preview["status"] != "EXTRACTED" or candidate != preview["candidate"]:
        raise ValueError("任务准备需要未经修改且来源验证通过的导入候选；请重新 import-script")
    # Even the intended number of layers and physical scale remain unknown.
    task = {"schema_version": 1, "case_id": "user-task",
            "physics": {key: None for key in PHYSICS_FIELDS},
            "units_um": None, "layers": [{"n": None, "thickness_um": None}],
            "wavelength_um": [None, None], "nfreq": None, "sources": [],
            "intent_note": "未确认草稿。请依据独立物理任务填写；未知项保留 null。"}
    observations = {
        "status": "NEEDS_USER_INTENT", "actual_llm_calls": 0,
        "script_executed": False, "task_approved": False,
        "candidate_sha256": digest(candidate), "source_sha256": preview["source"]["sha256"],
        "note": "仅记录脚本写法，不代表物理意图；厚度和频率使用 Meep 单位。",
        "script_layers": [{"material_kind": layer["material_kind"],
                           "material_value": layer["material_value"],
                           "thickness_meep_units": layer["thickness_um"]}
                          for layer in candidate["layers"]],
        "script_spectrum": preview["spectrum"],
        "source_locations": preview["source_locations"],
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "task.draft.json", task)
    write_json(out / "script-observations.json", observations)
    (out / "REVIEW.zh.md").write_text(REVIEW, encoding="utf-8")
    return out


def missing_fields(task):
    """List unfilled form fields together, without supplying any physical values."""
    missing = []
    physics = task.get("physics")
    for key in PHYSICS_FIELDS:
        if not isinstance(physics, dict) or physics.get(key) is None:
            missing.append("physics." + key)
    for key in ("units_um", "nfreq"):
        if task.get(key) is None:
            missing.append(key)
    layers = task.get("layers")
    if not isinstance(layers, list) or not layers:
        missing.append("layers")
    else:
        for i, layer in enumerate(layers):
            for key in ("n", "thickness_um"):
                if not isinstance(layer, dict) or layer.get(key) is None:
                    missing.append(f"layers.{i}.{key}")
    wavelengths = task.get("wavelength_um")
    if not isinstance(wavelengths, list) or len(wavelengths) != 2 or None in wavelengths:
        missing.append("wavelength_um")
    if not task.get("sources"):
        missing.append("sources")
    return missing


def confirm_task(task_path, lock_path, candidate_path=None):
    """Called only after CLI --approve; refuses incomplete tasks and existing locks."""
    task = load(task_path)
    if not isinstance(task, dict):
        raise ValueError("Task must be an object")
    missing = missing_fields(task)
    if missing:
        raise ValueError("任务尚未完整，未写入锁；请明确填写：" + ", ".join(missing))
    problem = task_problem(task)
    if problem:
        raise ValueError(problem["status"] + ": " + problem["reason"])
    if candidate_path is not None:
        candidate = load(candidate_path)
        problem = candidate_problem(candidate)
        if problem:
            raise ValueError(problem["reason"])
        origin = candidate.get("origin", {})
        if ("script_import" in origin or "script_patch_history" in origin
                or origin.get("kind") == "meep-ast-canonical-import"):
            validate_provenance(candidate, task)
        # A material mismatch must remain available for independent diagnosis.
    record = {"schema_version": 1, "task_sha256": digest(task),
              "policy_sha256": POLICY_HASH, "case_id": task.get("case_id"),
              "confirmation": "Explicit CLI --approve confirmation"}
    # Exclusive creation also prevents aliases/symlinks from overwriting an input.
    with Path(lock_path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


REVIEW = """# 填写并确认物理任务

这是未批准草稿。程序没有调用模型、执行原脚本或启动 Meep；没有创建任务锁。

1. 阅读原导入目录的 import-report.json 和原始脚本，核对提取位置。
2. 阅读 script-observations.json；其中材料写法、层数、厚度、频率只描述脚本。
   脚本中的 epsilon=2 不证明任务要求 n=sqrt(2)，变量名或注释也不是意图来源。
3. 将 task.draft.json 另存为 task.json，依据独立任务填写。未知字段保留 null 并停止确认。
   layers 中的一行仅为表单占位；按真实任务添加或删除，不能把脚本层数当作任务层数。
4. 填写 sources（例如 [{"kind":"user-confirmed specification","reference":"你的实际任务来源"}]）。
   将 intent_note 改为真实说明。不要把程序示例或模型建议写成用户已经确认的来源。
5. 检查以下支持条件确实符合任务后再填写 physics：dimensions=1、angle_deg=0、
   lossless=true、dispersive=false、isotropic=true、mu=1、n_incident=1、n_exit=1。
   它们是当前适用范围，不是程序已替你确认的事实。
6. 明确 units_um=1.0（每 Meep 单位对应 1 微米）。此适配器不做其他单位缩放。
   layers 的 n 是预期折射率，thickness_um 是微米厚度；wavelength_um 为递增的两个
   微米端点，nfreq 为频点数。原脚本频率没有自行确立物理单位。
7. 在项目根目录明确执行（将路径替换为本次文件）：

   .runtime/run-python -m photonguard confirm 任务目录/task.json --candidate 导入目录/candidate.json --lock 任务目录/task.lock.json --approve

   确认会检查完整性、支持范围，以及导入来源和谱段；材料差异保留给诊断。
   只有确认成功后才能 run；确认不是 PASS。已有锁拒绝覆盖，需要另开任务目录。

后续：run → 查看 report.html / report.json → propose → 阅读 patch.json →
明确 apply --approve 并输出新的候选文件 → run 全量复验 → verify-evidence。
完整中文演示见 docs/DEMO_ZH.md。原始脚本始终不执行，也不由修复操作改写。
"""
