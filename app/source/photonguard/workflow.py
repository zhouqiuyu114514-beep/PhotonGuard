"""Local, explicit-approval workflow for one existing canonical film scenario.

An optional source-bound model adapter supports explicit review requests.
Uploaded-code execution, shell commands, public hosting and automatic semantic
14-field conversion remain unavailable. The numerical policy is reused.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import io
import zipfile
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from urllib.parse import unquote, urlsplit
import uuid

from .agent import apply_patch, propose_patch
from .core import POLICY_HASH, candidate_problem, digest, finite, load, task_problem, verify_lock
from .report import page, render_fragment
from .runner import clean_environment, verify_evidence
from .script_import import MAX_BYTES, preview_bytes, validate_provenance
from .task_review import PHYSICS_FIELDS, missing_fields
from .ui import EvidenceStore, EvidenceError
from . import workflow_intake as intake_api
from .workflow_model import DeepSeekSemanticAdapter, RuleMockTransport, ModelGateError

ASSETS = Path(__file__).with_name("workflow_assets")
PROJECT = Path(__file__).resolve().parent.parent
ID = re.compile(r"[a-f0-9]{32}\Z")
RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
MAX_BODY = 900 * 1024
CONTEXT_KEYS = {"background", "goal", "role", "materials", "unknowns", "parameter_source"}
SCOPE = "仅支持 1D、正入射 Ex、线性无损无色散薄膜，空气入射与出射；等频率或显式等波长DFT采样配方。不是一般 Meep、二维波导或 LNOI 非线性工具。"
AI = {"mode": "NO_AI", "enabled": False, "actual_llm_calls": 0,
      "reason": "当前没有有效的服务端模型绑定，可先保存需求或使用离线整理；密钥不在网页输入。"}


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkflowError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def unique_json(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise WorkflowError("JSON 字段重复，未执行操作")
        out[key] = value
    return out


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=unique_json,
                      parse_constant=lambda _: (_ for _ in ()).throw(WorkflowError("不接受非有限数值")))


def write_once(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def atomic_json(path, value):
    temp = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    write_once(temp, value)
    os.replace(temp, path)


def empty_task():
    return {"schema_version": 1, "case_id": "user-task", "physics": {k: None for k in PHYSICS_FIELDS},
            "units_um": None, "layers": [{"n": None, "thickness_um": None}],
            "wavelength_um": [None, None], "nfreq": None, "sources": [],
            "intent_note": "待审草稿。根据独立资料填写；未知保留 null，不从脚本反推。"}


def demo_material():
    task = load(PROJECT / "examples/epsilon_mismatch/task.json")
    task["case_id"] = "guided-synthetic-film-demo"
    task["sources"] = [{"kind": "synthetic-guided-demo", "reference": "随本原型提供的完整合成任务卡 v1",
                        "note": "设计要求：1D 正入射 Ex、无损无色散各向同性非磁、空气两侧；1 Meep 单位=1微米；单层 n=2、厚0.3微米；波长端点1.3–1.7微米，41个等频率采样点。教学演示，不是真实用户需求或盲测。"}]
    task["intent_note"] = "按完整合成任务卡核对薄膜 R/T。原始脚本可能写错材料，不能用它替代任务来源。"
    source = (PROJECT / "examples/script_import/film_n2.py").read_text().replace("mp.Medium(index=n)", "mp.Medium(epsilon=n)")
    context = {"background": "合成教学场景：课堂提供了薄膜设计要求和一份待检查的 Meep 通量采集脚本。",
               "goal": "确认脚本描述的材料是否符合任务卡，并检查该配方在指定离散点的反射率 R、透射率 T。",
               "role": "学习者：整理已有要求，核对来源并决定是否批准任务和修复；不用猜测未知量。",
               "materials": task["sources"][0]["note"], "unknowns": "本演示的任务卡完整；尚不知道原脚本是否满足要求，这由检查来判断。",
               "parameter_source": "独立的合成任务卡 v1；材料和目标参数不从待检脚本或曲线反推。"}
    return task, source, context


class WorkflowStore:
    def __init__(self, root, *, allow_workers=True, model_adapter=None):
        raw = Path(root).absolute()
        if any(p.is_symlink() for p in [raw, *raw.parents]):
            raise WorkflowError("工作区路径不能包含符号链接")
        raw.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = raw.resolve()
        self.lock = threading.RLock()
        self.project_root = PROJECT
        self.allow_workers = allow_workers and os.name == 'posix'
        self.model_adapter = model_adapter or DeepSeekSemanticAdapter(mock_transport=RuleMockTransport())
        self.csrf = secrets.token_urlsafe(32)
        self.processes = {}
        self.closed = False
        if (self.root / ".server.lock").is_symlink():
            raise WorkflowError("工作区锁不能是符号链接", 403)
        self._lock_file = (self.root / ".server.lock").open("a")
        try:
            if os.name == 'nt':
                import msvcrt
                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_file.close()
            raise WorkflowError("此工作区已有一个服务运行，请勿重复启动", 409) from None
        self.meep_available = importlib.util.find_spec("meep") is not None
        from .experiments.ai_binding import BindingManager
        try:
            self.ai_binding = BindingManager(self)
        except Exception:
            self._lock_file.close()
            raise

    def close(self):
        self.closed = True
        if hasattr(self, 'ai_binding'):
            self.ai_binding.close()
        # Active bounded workers retain their own durable receipts. Stopping the UI
        # is not presented as cancelling an already started solver.
        self._lock_file.close()

    def safe(self, *parts):
        p = self.root
        for part in parts:
            if not isinstance(part, str) or not RUN.fullmatch(part) or ".." in part:
                raise WorkflowError("非法工作区路径")
            p = p / part
            if p.is_symlink():
                raise WorkflowError("不读取或覆盖符号链接", 403)
        if not p.resolve().is_relative_to(self.root):
            raise WorkflowError("路径超出工作区", 403)
        return p

    def case_dir(self, ident):
        if not ID.fullmatch(ident):
            raise WorkflowError("任务编号无效")
        p = self.safe(ident)
        if not p.is_dir():
            raise WorkflowError("任务不存在", 404)
        return p

    def _load(self, ident):
        self.case_dir(ident)
        return load(self.safe(ident, "state.json"))

    def _save(self, state):
        state["revision"] += 1
        state["updated_at"] = now()
        atomic_json(self.safe(state["id"], "state.json"), state)

    def workspaces(self):
        """Case collections share the existing disk, worker and model budgets."""
        with self.lock:
            path = self.safe('workspaces.json')
            entries = load(path) if path.exists() else []
            return [{'id': 'default', 'label': '原有工作区', 'created_at': None}, *entries]

    def workspace_status(self):
        with self.lock:
            entries = self.workspaces()
            counts = {e['id']: 0 for e in entries}
            for p in self.root.iterdir():
                if ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink():
                    state = self._load(p.name)
                    counts[state.get('workspace_id', 'default')] += 1
            return {'items': [{**e, 'case_count': counts[e['id']], 'case_limit': 32} for e in entries],
                    'maximum_workspaces': 8, 'shared_storage_limit_bytes': 1024 ** 3,
                    'shared_worker_and_model_limits': True}

    def create_workspace(self, label):
        with self.lock:
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
                raise WorkflowError('请填写1–80字的工作区名称', 422)
            entries = self.workspaces()
            if len(entries) >= 8:
                raise WorkflowError('已达8个工作区上限；现有案例与证据保留', 409)
            self.storage_guard(1024 * 1024)
            from .backend import _redact
            item = {'id': uuid.uuid4().hex, 'label': _redact(label.strip(), None), 'created_at': now()}
            atomic_json(self.safe('workspaces.json'), [*entries[1:], item])
            return item

    def list_cases(self):
        with self.lock:
            result = []
            for p in sorted(self.root.iterdir()):
                if ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink():
                    state = self.get(p.name)
                    result.append({**{k: state[k] for k in ("id", "label", "stage", "demo", "updated_at", "created_at")},
                                   'workspace_id': state.get('workspace_id', 'default'),
                                   'record_type': state.get('record_type', 'UNCLASSIFIED')})
            return sorted(result, key=lambda x: x["updated_at"], reverse=True)

    def create(self, mode, workspace_id="default"):
        with self.lock:
            if mode not in {"demo", "own", "novice-teaching", "novice-specified"}:
                raise WorkflowError("请选择 demo 或 own")
            spaces = self.workspace_status()['items']
            space = next((w for w in spaces if w['id'] == workspace_id), None)
            if space is None:
                raise WorkflowError('工作区不存在；请重新选择', 404)
            if space['case_count'] >= 32:
                raise WorkflowError('此工作区已达32个任务上限；请在侧栏新建或切换工作区，旧证据保留', 409)
            self.storage_guard(1024 * 1024)
            ident = uuid.uuid4().hex
            self.safe(ident).mkdir(mode=0o700)
            task, source, context = demo_material() if mode == "demo" else (empty_task(), "", {k: "" for k in CONTEXT_KEYS})
            state = {"id": ident, "revision": 0, "label": "完整合成教学演示" if mode == "demo" else "我的资料核对",
                     "workspace_id": workspace_id, "record_type": "SYNTHETIC_DEMO" if mode == "demo" else "UNCLASSIFIED",
                     "demo": mode == "demo", "context": context, "context_unknown_fields": [], "context_reviewed": False,
                     "task": task, "task_reviewed": False, "source_text": source,
                     "import_preview": None, "candidate": None, "candidate_file": None,
                     "approval": None, "proposal": None, "job": None, "job_attempts": 0, "diagnosis_blocker": None, "runs": [],
                     "paused_reason": None, "created_at": now(), "updated_at": now(), "history_count": 0}
            if mode.startswith('novice-'):
                from .novice import draft
                kind=mode.removeprefix('novice-')
                state['novice']=draft(ident,kind,'我想检查薄膜，但还没有整理参数。')
                state.update(intake=state['novice']['intake'],three_step=True,
                    label='无脚本 · '+('合成薄膜练习' if kind=='teaching' else '我的指定模型'),
                    record_type='SYNTHETIC_DEMO' if kind=='teaching' else 'UNCLASSIFIED')
                if getattr(self,'simulation_context',None):
                    state.update(actor_type='SIMULATED',simulation_context=self.simulation_context,record_type='SIMULATED_AI_USER')
            if getattr(self,'simulation_context',None):
                state.update(actor_type='SIMULATED',simulation_context=self.simulation_context,record_type='SIMULATED_AI_USER')
            if mode=='own' and hasattr(self,'pipeline_controller'):state['three_step']=True
            self._save(state)
            return self.present(state)

    def _reconcile(self, state):
        if state.get('adapter_flow') and hasattr(self,'mode_controller'):
            self.mode_controller.reconcile(state)
            return
        job = state.get("job")
        if not job or job["status"] != "running":
            return
        receipt_path = self.safe(state["id"], job["receipt"])
        if receipt_path.exists():
            receipt = load(receipt_path)
            if receipt.get("job_id") != job["id"]:
                raise WorkflowError("运行回执身份不匹配", 409)
            if receipt.get("status") == "completed":
                run_id = receipt["run_id"]
                evidence = self.evidence(state["id"], run_id)
                if not verify_evidence(evidence._run_path(run_id)):
                    job.update(status="failed", error="证据哈希校验失败；不能展示为完成")
                else:
                    report = evidence.report(run_id)
                    actual = report.get("resource_usage", {}).get("fdtd_runs", 0)
                    solver = "REAL_MEEP" if actual > 0 and report.get("environment", {}).get("meep_actual_version") else "NO_SOLVER_EVIDENCE"
                    state["runs"].append({"run_id": run_id, "status": report["status"], "solver_kind": solver,
                                           "report_url": f'/reports/{state["id"]}/{run_id}',
                                           "spectrum_url": f'/api/cases/{state["id"]}/runs/{run_id}/spectrum',
                                           "fdtd_runs": actual, "candidate_hash": report["candidate_hash"],
                                           "task_hash": report["task_hash"], "evidence_verified": True,
                                           "checks": report.get("checks", []), "created_at": report.get("created_at")})
                    job.update(status="completed", run_id=run_id)
            else:
                job.update(status="failed", error=receipt.get("error", "工作进程异常退出，未建立验收结论"))
            job["finished_at"] = now()
            self._save(state)
        else:
            proc = self.processes.get(job["id"])
            if proc is not None and proc.poll() is not None:
                job.update(status="failed", error="工作进程退出但没有完成回执；保留日志，不能视为通过", finished_at=now())
                self._save(state)
            elif proc is None:
                # Restart recovery: the previous worker can finish its receipt.
                # No new worker is admitted while that PID may still be alive.
                if not job.get("pid"):
                    started = self.safe(state["id"], "started-" + job["id"] + ".json")
                    if started.exists():
                        marker = load(started)
                        if marker.get("job_id") == job["id"] and type(marker.get("pid")) is int:
                            job["pid"] = marker["pid"]
                    if not job.get("pid"):
                        job["recovery_note"] = "启动预约已保存但尚未取得工作进程回执；保持阻塞，避免重复运行。请检查本机服务日志。"
                        return
                try:
                    os.kill(job["pid"], 0)
                except ProcessLookupError:
                    job.update(status="failed", error="服务曾中断，旧工作进程已不存在且无完成回执；可明确重试", finished_at=now())
                    self._save(state)
                except (PermissionError, KeyError):
                    job["recovery_note"] = "无法确认旧工作进程状态；保持阻塞，不自动启动另一轮"

    def get(self, ident):
        with self.lock:
            state = self._load(ident)
            self._reconcile(state)
            return self.present(state)

    def _missing(self, state):
        context = state["context"]
        unknown = {"", "不知道", "我不知道", "暂不知道", "暂时不知道", "不清楚", "我不清楚", "不确定", "待确认", "unknown", "资料没有", "资料里没有", "资料中没有", "没有"}
        out = ["context." + k for k in ("background", "goal", "role", "materials", "parameter_source") if k in state.get("context_unknown_fields", []) or context.get(k, "").strip().rstrip("。.!！ ").lower() in unknown]
        sources = state["task"].get("sources", [])
        if isinstance(sources, list):
            for i, source in enumerate(sources):
                if not isinstance(source, dict) or not isinstance(source.get("reference"), str) or source["reference"].strip().rstrip("。.!！ ").lower() in unknown:
                    out.append(f"sources.{i}.reference")
        return out + missing_fields(state["task"])

    def readiness(self, state):
        task = state["task"]
        problem = task_problem(task)
        explicit_scope = None
        supported = {"dimensions": 1, "angle_deg": 0, "lossless": True, "dispersive": False, "isotropic": True, "mu": 1, "n_incident": 1, "n_exit": 1}
        for key, expected in supported.items():
            value = task.get("physics", {}).get(key)
            if value is not None and (value != expected or isinstance(expected, bool) != isinstance(value, bool)):
                explicit_scope = f"已有资料中的 {key}={value} 超出当前支持范围；不会用默认值替代它。"
                break
        if task.get("units_um") is not None and task.get("units_um") != 1:
            explicit_scope = "已有资料的物理单位超出原生适配器（1 Meep单位=1微米），不会自动换算或改写。"
        if isinstance(task.get('layers'), list) and len(task['layers']) != 1:
            mapping = state.get('mapping_review') or {}
            if mapping.get('mapping_adapter') != 'film_stack_task_v2':
                explicit_scope = '多层需要独立有序层列表与新版映射确认；旧单膜入口不自动合并或丢弃层。'
            else:
                try:
                    from .task_mapping import project
                    expected_task, _, _ = project(state.get('intake'), mapping.get('options'))
                    if expected_task != task: raise ValueError('多层任务或独立出处改变。')
                except (ValueError, TypeError, KeyError):
                    explicit_scope = '多层独立资料与任务绑定未通过；请重新审阅。'
        provenance = None
        mapping = state.get('mapping_review')
        if mapping:
            intake = state.get('intake') or {}
            if (mapping.get('native_task_sha256') != digest(task)
                    or not intake.get('confirmation')
                    or mapping.get('semantic_result_sha256') != intake.get('result_sha256')
                    or mapping.get('semantic_input_sha256') != intake.get('view',{}).get('input_sha256')):
                provenance = '映射依据或任务已变化；请重新审阅映射，旧确认不能锁定新任务。'
        if state.get("candidate") and problem is None and provenance is None:
            try:
                validate_provenance(state["candidate"], state["task"])
            except (ValueError, KeyError, TypeError) as exc:
                provenance = str(exc)
        return {"task_problem": problem, "provenance_problem": provenance, "explicit_scope_problem": explicit_scope}

    def present(self, state):
        state = copy.deepcopy(state)
        if state.get('adapter_flow'):
            flow=state['adapter_flow']
            if flow.get('repair_card'):flow['repair_card_sha256']=digest(flow['repair_card'])
            flow['ai_service']=self.mode_controller.status() if hasattr(self,'mode_controller') else {'ai':{'live_enabled':False}}
            state.update(stage=flow['stage'],next_action={'kind':'mode','title':'实验模态/QPM','detail':'独立任务、实际模态与归一化相位因子'},
                runtime={'meep_available':self.meep_available},cancel_supported=False)
            return state
        if state.get('repair_card'):
            state['repair_card_sha256'] = digest(state['repair_card'])
        state["missing"] = self._missing(state)
        state["readiness"] = self.readiness(state)
        state["comparison"] = self.comparison(state)
        state["scope"] = SCOPE
        state["ai"] = self.ai_status(state)
        state["runtime"] = {"meep_available": self.meep_available}
        state["cancel_supported"] = False
        diagnosis=state.get('diagnosis') or {}
        if diagnosis and state.get('diagnostic_mode')=='live' and not diagnosis.get('explanation_audit_status') and state.get('runs'):
            from .claims import audit_legacy_text
            from .evidence_facts import collect_facts
            try:
                evidence=self.case_dir(state['id'])/'artifacts'/state['runs'][0]['run_id']
                text=str(diagnosis.get('reason',''))+'\n'+'\n'.join(str(i.get('reason','')) for i in diagnosis.get('issues',[]))
                table=collect_facts(evidence)
                if table['task_sha256']!=digest(state['task']):raise ValueError('Historical explanation task changed')
                state['historical_explanation_audit']=audit_legacy_text(text,table)
                state['historical_explanation_audit']['derived_read_only']=True
            except (ValueError,KeyError,TypeError,OSError):
                state['historical_explanation_audit']={'status':'UNVERIFIED_LEGACY_TEXT','derived_read_only':True,'reason':'Historical evidence could not be rebuilt; no false explanation PASS'}
        if state.get("paused_reason"):
            stage, kind, title, detail = "PAUSED", "paused", "资料暂缺，已保存到这里", "不用猜或计算。以后带上已有任务说明或参数出处再继续；程序没有联系任何人，也没有自动补值。"
        elif state.get("job") and state["job"]["status"] == "running":
            stage, kind, title, detail = "RUNNING", "wait", "真实 Meep 正在运行", "按固定预算顺序运行四组参考/目标配对。这里只显示实际状态，没有估算进度条；本版不提供中途取消。"
        elif state["readiness"]["explicit_scope_problem"]:
            stage, kind, title, detail = "UNSUPPORTED", "unsupported", "已知要求超出当前支持范围", state["readiness"]["explicit_scope_problem"]
        elif not state["context_reviewed"] or any(x.startswith("context.") for x in state["missing"]):
            stage, kind, title, detail = "CONTEXT_NEEDED", "context", "先确认这件事要解决什么", "提供你已有的背景、目标、承担的角色和资料来源。角色或目标不清楚就保留缺项，不从参数猜目的。"
        elif not state["task_reviewed"] or missing_fields(state["task"]) or any(key.startswith("sources.") for key in state["missing"]):
            stage, kind, title, detail = "TASK_REVIEW", "task", "根据独立资料核对任务", "只整理已有设计说明或材料记录，不需要计算或猜测缺失参数。脚本的写法不能替代需求。"
        elif state["readiness"]["task_problem"]:
            stage, kind, title, detail = "UNSUPPORTED", "unsupported", "任务尚不能进入当前求解器", state["readiness"]["task_problem"]["reason"]
        elif state.get("import_preview") and state["import_preview"]["status"] == "UNSUPPORTED":
            stage, kind, title, detail = "UNSUPPORTED", "unsupported", "脚本不在当前只读导入范围内", "解析器已停止，没有执行此脚本，也没有可运行的部分配方。请查看拒绝位置；可以换成文档支持的写法，或保留资料暂停。"
        elif not state["candidate"]:
            stage, kind, title, detail = "SCRIPT_IMPORT", "import", "只读导入待检脚本", "仅识别文档列出的顺序式 Meep 通量模板；不执行上传 Python，不检查原脚本的后处理代码。"
        elif state["readiness"]["provenance_problem"]:
            stage, kind, title, detail = "UNSUPPORTED", "unsupported", "脚本与任务无法直接对接", state["readiness"]["provenance_problem"]
        elif not state["approval"]:
            stage, kind, title, detail = "CONFIRM_TASK", "confirm", "请明确确认独立任务", "锁定的是需求和固定验收规则，不是脚本正确性。确认后不覆盖旧锁；需求变更要新建任务。"
        elif state["proposal"]:
            stage, kind, title, detail = "REPAIR_REVIEW", "apply", "审阅并批准这一项修复", "只修改提取后的规范化配方，保留原始脚本。批准后仍要重新执行全部验收；批准不等于 PASS。"
        elif state.get("job") and state["job"]["status"] == "failed" and state.get("job_attempts", 0) >= 6:
            stage, kind, title, detail = "REVIEW_NEEDED", "report", "已到本任务的运行预算上限", "六次显式尝试均已记账，不能再启动求解。请保留错误记录并人工检查环境；没有结果不等于通过。"
        elif state.get("job") and state["job"]["status"] == "failed":
            stage, kind, title, detail = "READY_TO_RUN", "run", "上一轮未形成完整结果", "失败日志已保留。确认原因后可显式重试，不会自动重跑或报告通过。"
        elif not state["runs"] or state["runs"][-1]["candidate_hash"] != digest(state["candidate"]):
            stage, kind, title, detail = "READY_TO_RUN", "run", "执行真实 Meep 检查", "复用固定验收器：原设置、网格、运行时间、PML 四组，每组参考与目标，共最多8次 FDTD；不调用 AI。"
        elif state["runs"][-1]["status"] == "FAIL" and state["candidate"].get("origin", {}).get("patch_round", 0) < 2 and not state.get("diagnosis_blocker"):
            stage, kind, title, detail = "DIAGNOSIS", "propose", "查看原因与受限修复建议", "规则建议只依据已确认任务和这一轮可校验证据，不改需求或容差。"
        else:
            result = state["runs"][-1]["status"] if state["runs"] else "INCONCLUSIVE"
            if result == "PASS":
                stage, kind, title, detail = "COMPLETED", "report", "查看曲线和验收边界", "PASS 只覆盖记录的离散频点、物理假设与开发容差，不证明连续波段正确，也不证明任意原始脚本通过。"
            else:
                stage, kind, title, detail = "REVIEW_NEEDED", "report", "已有检查结果，问题仍需审阅", state.get("diagnosis_blocker") or {"FAIL": "仍存在失败检查；已到受限修复边界，不能把它显示为问题已解决。", "INCONCLUSIVE": "证据不足，无法形成通过结论。请查看缺失检查与日志。", "UNSUPPORTED": "当前配方超出支持范围；没有一般脚本正确性结论。"}.get(result, "请审阅原始证据。")
        state["stage"] = stage
        state["next_action"] = {"kind": kind, "title": title, "detail": detail}
        # Internal filesystem controls are never accepted back from clients.
        for key in ("candidate_file",):
            state.pop(key, None)
        return state

    def ai_status(self, state=None):
        enabled = self.model_adapter.status()['live_enabled']
        return {**AI, 'enabled': enabled, 'mode': 'LIVE_APPROVAL_BOUND' if enabled else 'NO_AI',
                'actual_llm_calls': ((state or {}).get('intake') or {}).get('model_calls', 0),
                'reason': ('新服务端授权已绑定；每次请求仍需材料、费用和期限校验。' if enabled else AI['reason'])}

    def comparison(self, state):
        c, task = state.get("candidate"), state["task"]
        if not c:
            return []
        rows = []
        mapping = (state.get("import_preview") or {}).get("source_locations", {})
        task_layers = task.get("layers") or []
        rows.append({"field": "层数", "required": len(task_layers), "actual": len(c["layers"]), "locations": [],
                     "match": len(task_layers) == len(c["layers"]), "consequence": "层数不同会改变整个结构；不自动增删薄膜。"})
        for i, layer in enumerate(c["layers"]):
            req = task_layers[i] if i < len(task_layers) else {}
            actual_n = layer["material_value"] if layer["material_kind"] == "index" else layer["material_value"] ** .5
            for field, desired, actual, why in (("material_value", req.get("n"), actual_n, "在当前非磁无损模型中 ε=n²。把 n 直接填进 epsilon 会改变实际折射率，进而改变反射和透射。"),
                                                 ("thickness_um", req.get("thickness_um"), layer["thickness_um"], "厚度改变光在膜中的相位积累，因此会移动干涉峰谷。")):
                key = f"layers.{i}.{field}"
                rows.append({"field": f"第{i+1}层 " + ("折射率 n" if field == "material_value" else "厚度 μm"),
                             "required": desired, "actual": actual, "script_value": layer["material_value"] if field == "material_value" else actual,
                             "script_kind": layer["material_kind"] if field == "material_value" else "thickness_um",
                             "locations": mapping.get(key, []), "match": finite(desired) and abs(desired - actual) < 1e-12,
                             "consequence": why, "source_note": "源码位置指向原始脚本；批准后的配方改动由独立修复记录说明。"})
        rows.extend([{"field": "入射场扣除", "required": True, "actual": c["workflow"]["subtract_incident"],
                      "locations": mapping.get("workflow.subtract_incident", []), "match": c["workflow"]["subtract_incident"],
                      "consequence": "反射监视器会同时看到入射波；不扣除入射场会把入射信号混入反射。"},
                     {"field": "采样约定", "required": "显式等波长DFT采样" if task.get("sampling") else "原生等频率采样", "actual": f'{task.get("nfreq")} 个实际DFT点；没有插值',
                      "locations": mapping.get("spectrum.nfreq", []) + mapping.get("spectrum.fcen", []) + mapping.get("spectrum.df", []), "match": self.readiness(state)["provenance_problem"] is None and task_problem(task) is None,
                      "consequence": "不能把实验公共接口的等波长要求隐式替换为等频率扫描。"}])
        return rows

    def storage_guard(self, reserve=0):
        total = 0
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            for name in files:
                p = Path(directory) / name
                if not p.is_symlink():
                    total += p.stat().st_size
        if total + reserve > 1024 ** 3 or shutil.disk_usage(self.root).free < max(reserve, 16 * 1024 ** 2):
            raise WorkflowError("工作区达到1GiB预算或磁盘空间不足；保留现有记录，不再启动新写入", 507)

    def _snapshot(self, state, prefix, value):
        self.storage_guard(1024 * 1024)
        state["history_count"] += 1
        if state["history_count"] > 64:
            raise WorkflowError("本任务编辑历史达到64次上限；旧记录保留，请另建任务", 409)
        name = prefix + "-" + uuid.uuid4().hex + ".json"
        write_once(self.safe(state["id"], name), value)
        return name

    def action(self, ident, data):
        with self.lock:
            state = self._load(ident)
            self._reconcile(state)
            if type(data.get("expected_revision")) is not int or data["expected_revision"] != state["revision"]:
                raise WorkflowError("页面版本已过期，请刷新任务后再操作；没有重复应用", 409)
            action = data.get("type")
            allowed = {"context": {"context", "unknown_fields"}, "pause": {"reason"}, "resume": set(), "task": {"task"},
                       "import": {"name", "source"}, "confirm": {"approve"}, "run": set(), "propose": set(), "apply": {"approve"},
                       "intake-save": {"text"}, "intake-review": {"mode", "response_text", "arm"},
                       "map-task": {"options"}, "derive-version": {"reason"}, "pause-mapping": {"notes"}, "reset-mapping": set(),
                       "start-review": {"approve","accept_initial_checks","diagnostic_mode","approve_diagnostic_data","result_sha256","options","source"},
                       "approve-repair": {"approve","card_sha256","acknowledge_explanation_warning"}, "retry-check": {"approve"}, "resume-rule-review": set(),
                       "intake-confirm": {"approve", "result_sha256"}, "intake-cancel": set(), "intake-resume": set()}
            if action == 'case-metadata':
                if set(data) != {'type','expected_revision','label','record_type'}:
                    raise WorkflowError('名称与记录类型字段无效', 422)
                label, kind = data['label'], data['record_type']
                if not isinstance(label,str) or not 1 <= len(label.strip()) <= 120 or kind not in {'UNCLASSIFIED','SIMULATED_AI_USER','SYNTHETIC_DEMO'}:
                    raise WorkflowError('请填写1–120字名称并选择记录类型；此标签不构成人类参与证据', 422)
                if (state.get('job') or {}).get('status') == 'running' or (state.get('pipeline') or {}).get('status') in {'CHECKING','DIAGNOSING','REVERIFYING'}:
                    raise WorkflowError('运行完成后再修改显示名称', 409)
                from .backend import _redact
                self._snapshot(state,'display-metadata',{'previous':{'label':state['label'],'record_type':state.get('record_type','UNCLASSIFIED')},'label':_redact(label.strip(),None),'record_type':kind,'at':now(),'task_and_evidence_unchanged':True})
                state.update(label=_redact(label.strip(),None),record_type=kind)
                self._save(state)
                return self.present(state)
            if action in ('novice-material','novice-pause','novice-start','novice-ai-review'):
                if state.get('paused_reason'):raise WorkflowError('任务已暂停，请先恢复编辑',409)
                from .novice import action as novice_action
                return novice_action(self,state,data)
            if state.get('adapter_flow'):
                from .mode_pipeline import ACTIONS
                if action not in ACTIONS or set(data)-(ACTIONS[action]|{'type','expected_revision'}) or not hasattr(self,'mode_controller'):
                    raise WorkflowError('模态任务只能使用明确的实验操作；旧薄膜按钮不能启动或覆盖它。')
                return self.mode_controller.action(state,data)
            if action not in allowed or set(data) - (allowed[action] | {"type", "expected_revision"}):
                raise WorkflowError("操作或字段不受支持")
            if state.get("job") and state["job"]["status"] == "running":
                raise WorkflowError("当前真实求解仍在运行；不接受重复操作或不安全取消", 409)
            if state["paused_reason"] and action != "resume":
                raise WorkflowError("任务已暂停，请先明确恢复", 409)
            if action in ('start-review','approve-repair','retry-check','resume-rule-review'):
                if not hasattr(self,'pipeline_controller'):
                    raise WorkflowError('当前入口未启用三步诊断服务。',409)
                return self.pipeline_controller.action(state,data)
            if state.get('pipeline') and hasattr(self,'pipeline_controller') and not self.pipeline_controller.internal() and (state['pipeline'].get('status') in {'CHECKING','DIAGNOSING','REVERIFYING'} or action not in ('pause','resume','derive-version')):
                raise WorkflowError('本任务由三步流程管理；不能另行覆盖诊断、批准或重复执行。',409)
            if action == 'derive-version':
                reason = data.get('reason')
                if not isinstance(reason,str) or not 3 <= len(reason.strip()) <= 1000:
                    raise WorkflowError('请写明为什么修改需求，旧任务和证据保留。',422)
                child = self._load(self.create('own', state.get('workspace_id','default'))['id'])
                child.update(record_type=state.get('record_type','UNCLASSIFIED'),context=copy.deepcopy(state['context']),context_reviewed=state['context_reviewed'],
                    task=copy.deepcopy(state['task']), task_reviewed=False,
                    intake=copy.deepcopy(state.get('intake')),
                    parent_version={'case_id':ident,'revision':state['revision'],
                        'task_sha256':digest(state['task']),'reason':reason,'at':now()},
                    label=state['label'] + ' · 新需求版本')
                if state.get('three_step'):
                    child['three_step']=True
                    child['repair_trial']=copy.deepcopy(state.get('repair_trial'))
                if state.get('novice'):
                    from .novice import draft
                    # A new editable draft has its own case identity and no inherited approval/model claim.
                    child['novice']=draft(child['id'],'specified',state['novice']['original_text'])
                    child['novice']['derived_from']={'case_id':ident,'context_type':state['novice']['context_type'],
                        'template_source':state['novice']['template_source']}
                    child['intake']=child['novice']['intake']
                    child['three_step']=True
                if state.get('actor_type'):
                    child['actor_type']=state['actor_type']
                if state.get('simulation_context'):
                    child['simulation_context']=copy.deepcopy(state['simulation_context'])
                if child.get('intake'):
                    child['intake']['confirmation'] = None
                    if child['intake'].get('result'): child['intake']['status'] = 'REVIEW'
                self._snapshot(child,'version-parent',child['parent_version'])
                self._save(child)
                return self.present(child)
            if action == 'reset-mapping':
                if state['approval'] or not state.get('mapping_review'):
                    raise WorkflowError('只能在锁定前重新审阅映射；锁定后请建立新版本。',409)
                record=state.pop('mapping_review')
                state['mapping_draft']={k:record['options'][k] for k in ('mapping_source','background','goal','role')}
                state['task_reviewed']=False
                self._snapshot(state,'mapping-reset',{'previous':record,'task_approved':False})
                self._save(state)
                return self.present(state)
            if action == 'pause-mapping':
                notes = data.get('notes')
                if not isinstance(notes,dict) or set(notes) != {'mapping_source','background','goal','role'} or any(not isinstance(v,str) or len(v)>4000 for v in notes.values()):
                    raise WorkflowError('暂停资料必须为映射页面的有限文本字段。',422)
                from .backend import _redact
                state['mapping_draft'] = {k:_redact(v,None) for k,v in notes.items()}
                state['paused_reason'] = '执行映射资料暂缺；已有文字保存，未知不猜。'
                self._snapshot(state,'mapping-paused',{'notes':state['mapping_draft'],'at':now()})
                self._save(state)
                return self.present(state)
            if action == 'map-task':
                if state['approval']:
                    raise WorkflowError('任务已锁定；请建立新需求版本。',409)
                from .task_mapping import project
                try: task, mapping, context = project(state.get('intake'),data.get('options'))
                except ValueError as exc: raise WorkflowError(str(exc),422) from None
                mapping['at'] = now()
                mapping['previous_task_sha256'] = digest(state['task'])
                self._snapshot(state,'human-mapping',mapping)
                state.update(task=task, task_reviewed=True, context=context,context_reviewed=True,
                    context_unknown_fields=[], mapping_review=mapping)
                self._save(state)
                return self.present(state)
            if action.startswith('intake-'):
                if state['approval'] or state['demo']:
                    raise WorkflowError('语义录入请使用新建的自有材料任务；已有锁与演示记录保留。', 409)
                if action == 'intake-review' and data.get('mode') in ('live', 'adapter_mock'):
                    if data.get('response_text') not in (None, ''):
                        raise WorkflowError('模型适配器不接受客户端代填的模型响应。', 422)
                    if data['mode'] == 'live' and not self.model_adapter.status()['live_enabled']:
                        raise WorkflowError('真实模型当前不可派发；请核对本轮累计次数、费用或服务端绑定。', 403)
                    current = state.get('intake')
                    if not current or current['status'] in ('CANCELLED', 'MODEL_RUNNING'):
                        raise WorkflowError('请先保存或恢复材料；处理中断的记录须先撤回，不会自动重派。', 409)
                    bound_arm = state.get('approved_comparison_arm')
                    if data['mode'] == 'live' and bound_arm and data.get('arm', 'A1') != bound_arm:
                        raise WorkflowError('该对照任务已绑定协议 ' + bound_arm + '；未派发。', 422)
                    if hasattr(self.model_adapter, 'preflight'):
                        try:
                            self.model_adapter.preflight(current['view'], mode=data['mode'], arm=data.get('arm', 'A1'))
                        except (ModelGateError, ValueError):
                            raise WorkflowError('本项授权、源码或重复请求检查未通过；现有草稿与证据保留，没有派发。', 409) from None
                    current.update(status='MODEL_RUNNING', result=None, confirmation=None)
                    current.pop('result_sha256', None)
                    self._snapshot(state, 'model-start', {'input_sha256': current['view']['input_sha256'], 'mode': data['mode']})
                    self._save(state)
                    try:
                        response = self.model_adapter.run(current['view'], mode=data['mode'], arm=data.get('arm', 'A1'))
                        value = intake_api.model_result(current, response)
                    except Exception:
                        # A credential supplier or model adapter may raise an
                        # unexpected error containing private details. Persist a
                        # generic failure and never log the exception text.
                        value = copy.deepcopy(current)
                        value.update(status='FAILED', result=None, confirmation=None, error='适配器或授权检查失败；未自动重试。请保留此记录并核对服务端授权与材料。')
                    self._snapshot(state, 'model-review', value)
                    state['intake'] = value
                    self._save(state)
                    return self.present(state)
                try:
                    value = (intake_api.prepare(ident, data.get('text')) if action == 'intake-save'
                             else intake_api.apply(state.get('intake'), data))
                except ValueError as exc:
                    raise WorkflowError(str(exc), 422) from None
                self._snapshot(state, 'semantic-intake', value)
                state['intake'] = value
                if state.get('mapping_review') and action in ('intake-save','intake-review','intake-cancel','intake-resume'):
                    state['task_reviewed'] = False
                self._save(state)
                return self.present(state)
            if action == "pause":
                reason = data.get("reason", "资料没有/暂不知道")
                if not isinstance(reason, str) or len(reason) > 2000:
                    raise WorkflowError("暂停原因过长")
                state["paused_reason"] = reason or "资料没有/暂不知道"
                self._snapshot(state, "pause", {"reason": state["paused_reason"], "at": now(), "no_automatic_fill": True})
            elif action == "resume":
                state["paused_reason"] = None
            elif action in {"context", "task", "import"}:
                if state["approval"]:
                    raise WorkflowError("任务已锁定；修改需求或输入请另建任务，旧锁与证据保留", 409)
                if action == "context":
                    context = data.get("context")
                    if not isinstance(context, dict) or set(context) - CONTEXT_KEYS or any(not isinstance(v, str) or len(v) > 8000 for v in context.values()):
                        raise WorkflowError("背景字段应为不超过8000字的文本")
                    unknown_fields = data.get("unknown_fields", [])
                    if not isinstance(unknown_fields, list) or any(not isinstance(k, str) or k not in CONTEXT_KEYS for k in unknown_fields):
                        raise WorkflowError("未知项必须是背景表单中的字段名")
                    state["context_unknown_fields"] = sorted(set(unknown_fields))
                    state["context"] = {k: context.get(k, "").strip() for k in CONTEXT_KEYS}
                    state["context_reviewed"] = True
                    self._snapshot(state, "context", {"values": state["context"], "unknown_fields": state["context_unknown_fields"]})
                elif action == "task":
                    task = data.get("task")
                    if not isinstance(task, dict) or len(json.dumps(task, ensure_ascii=False).encode()) > 65536:
                        raise WorkflowError("任务必须是最多64KiB的 JSON 对象")
                    if not isinstance(task.get("case_id"), str) or not 1 <= len(task["case_id"]) <= 100 or "\x00" in task["case_id"]:
                        raise WorkflowError("case_id 需要1至100字的非空任务名称")
                    # Structure must be reviewable even when incomplete.
                    if not isinstance(task.get("physics"), dict) or not isinstance(task.get("layers"), list) or any(not isinstance(x, dict) for x in task["layers"]):
                        raise WorkflowError("任务的 physics 和 layers 结构无效；可保留 null 值")
                    if not isinstance(task.get("sources"), list) or any(not isinstance(x, dict) or (x.get("reference") is not None and not isinstance(x.get("reference"), str)) for x in task["sources"]):
                        raise WorkflowError("sources 应为资料条目数组；未知 reference 可保留 null 或空字符串，不会因此批准任务")
                    state["task"] = task
                    state["task_reviewed"] = True
                    self._snapshot(state, "task-draft", task)
                else:
                    source, name = data.get("source"), data.get("name", "input.py")
                    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_BYTES:
                        raise WorkflowError("脚本必须是最多128KiB的 UTF-8文本", 413)
                    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff][A-Za-z0-9_.\-\u4e00-\u9fff]{0,100}\.py", name) or ".." in name:
                        raise WorkflowError("文件名须为不带路径的 .py 名称")
                    preview = preview_bytes(source.encode("utf-8"), name)
                    state["source_text"], state["import_preview"] = source, preview
                    state["candidate"] = preview["candidate"]
                    self._snapshot(state, "import-preview", preview)
                    source_name = "source-" + uuid.uuid4().hex + ".py"
                    with self.safe(ident, source_name).open("xb") as f:
                        f.write(source.encode("utf-8"))
                    state["source_file"] = source_name
                    state["candidate_file"] = self._snapshot(state, "candidate", preview["candidate"]) if preview["candidate"] else None
            elif action == "confirm":
                if data.get("approve") is not True:
                    raise WorkflowError("需要明确勾选并确认任务")
                if state["approval"]:
                    raise WorkflowError("已有确认锁，拒绝覆盖", 409)
                ready = self.readiness(state)
                if not state["context_reviewed"] or not state["task_reviewed"] or self._missing(state) or not state["candidate"] or ready["task_problem"] or ready["provenance_problem"] or ready['explicit_scope_problem']:
                    raise WorkflowError("背景、独立任务或脚本来源尚未完整通过核对；没有创建锁", 409)
                validate_provenance(state["candidate"], state["task"])
                self._snapshot(state, "confirmation-review", {"context": state["context"], "task_hash": digest(state["task"]), "candidate_hash": digest(state["candidate"]), "at": now()})
                record = {"schema_version": 1, "task_sha256": digest(state["task"]), "policy_sha256": POLICY_HASH,
                          "case_id": state["task"]["case_id"], "confirmation": "Explicit local graphical workflow task confirmation", "confirmed_at": now(), "actor_type": state.get("actor_type", "USER_ACTION")}
                write_once(self.safe(ident, "task.json"), state["task"])
                write_once(self.safe(ident, "task.lock.json"), record)
                state["approval"] = record
            elif action == "run":
                if self.readiness(state)['explicit_scope_problem']:
                    raise WorkflowError(self.readiness(state)['explicit_scope_problem'], 409)
                if not state["approval"] or not verify_lock(state["task"], load(self.safe(ident, "task.lock.json"))):
                    raise WorkflowError("请先明确确认完整任务", 409)
                if state["proposal"]:
                    raise WorkflowError("先处理待审修复建议，不能混淆版本", 409)
                if not self.meep_available or not self.allow_workers:
                    raise WorkflowError("当前解释器未启用真实 Meep。请使用已安装的官方运行时启动本服务；不会生成模拟结果", 503)
                for item in self.list_cases():
                    other = self._load(item["id"])
                    if other.get("job") and other["job"]["status"] == "running":
                        raise WorkflowError("本服务最多运行一个求解任务，请等待当前工作完成", 409)
                if state.get("job_attempts", 0) >= 6:
                    raise WorkflowError("此任务已达6轮显式运行上限，请保留证据并另开审阅", 409)
                if state["runs"] and state["runs"][-1]["candidate_hash"] == digest(state["candidate"]) and state.get("job", {}).get("status") != "failed":
                    raise WorkflowError("此版本已有完整运行证据；重复点击不会重跑", 409)
                self.storage_guard(192 * 1024 ** 2)
                job_id = uuid.uuid4().hex
                job = {"id": job_id, "status": "running", "kind": "real_meep", "started_at": now(),
                       "receipt": "job-" + job_id + ".json", "pid": None,
                       "cancel_note": "本版没有经过验证的子进程组安全取消；固定预算运行结束后保留全部证据。"}
                state["job"] = job
                state["job_attempts"] = state.get("job_attempts", 0) + 1
                self._save(state)
                log = self.safe(ident, "worker-" + job_id + ".log")
                env = clean_environment()
                try:
                    with log.open("xb") as stream:
                        proc = subprocess.Popen([sys.executable, "-m", "photonguard.workflow_worker", str(self.case_dir(ident)),
                                                 state["candidate_file"], job_id, job["receipt"]],
                                                cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                                start_new_session=True, close_fds=True)
                    job["pid"] = proc.pid
                    self.processes[job_id] = proc
                except OSError:
                    job.update(status="failed", error="无法启动受限求解工作进程")
            elif action == "propose":
                if not state["runs"]:
                    raise WorkflowError("先取得真实检查证据", 409)
                run_id = state["runs"][-1]["run_id"]
                evidence = self.evidence(ident, run_id)
                if not verify_evidence(evidence._run_path(run_id)):
                    raise WorkflowError("原证据完整性校验失败，停止建议", 409)
                patch = propose_patch(state["task"], state["candidate"], evidence.report(run_id))
                if patch is None:
                    state["diagnosis_blocker"] = "没有可安全自动建议的单项修复。原结果仍然有效；保留报告，需要进一步资料或人工审阅。"
                state["proposal"] = patch
                self._snapshot(state, "proposal", {"patch": patch, "blocker": state.get("diagnosis_blocker")})
            elif action == "apply":
                if data.get("approve") is not True or not state["proposal"]:
                    raise WorkflowError("需要明确批准已展示的单项修复", 409)
                if not state["approval"] or not verify_lock(state["task"], load(self.safe(ident, "task.lock.json"))):
                    raise WorkflowError("任务锁无效", 409)
                new = apply_patch(state["task"], state["candidate"], state["proposal"])
                validate_provenance(new, state["task"])
                self._snapshot(state, "repair-approval", {"approved": True, "patch": state["proposal"], "at": now(), "original_script_modified": False})
                state["candidate_file"] = self._snapshot(state, "candidate", new)
                state["candidate"] = new
                state["proposal"] = None
            self._save(state)
            return self.present(state)

    def evidence(self, ident, run_id):
        if not RUN.fullmatch(run_id) or ".." in run_id:
            raise WorkflowError("运行编号无效")
        self.safe(ident, "artifacts", run_id)
        return EvidenceStore(self.case_dir(ident))


class WorkflowHandler(BaseHTTPRequestHandler):
    server_version = "PhotonGuardWorkflow/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        return

    @property
    def store(self):
        return self.server.store

    def headers_ok(self, mutate=False):
        for header in ("Host", "Origin", "X-CSRF-Token", "Content-Type", "Sec-Fetch-Site", "Content-Length", "Transfer-Encoding"):
            if len(self.headers.get_all(header, [])) > 1:
                raise WorkflowError("拒绝重复的安全相关请求头", 403)
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            raise WorkflowError("仅接受本机明确回环 Host", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise WorkflowError("拒绝跨站请求", 403)
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] != "http://" + hosts[0]):
            raise WorkflowError("Origin 不匹配", 403)
        if mutate:
            if not origins or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.store.csrf):
                raise WorkflowError("缺少同源确认令牌，请在本机页面操作", 403)
            if self.headers.get("Content-Type", "").lower() != "application/json":
                raise WorkflowError("只接受 application/json", 415)
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise WorkflowError("请求长度不明确")

    def send(self, body, content_type, status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        if content_type.startswith("text/html") and (self.path.startswith("/reports/") or re.fullmatch(r'/api/experiments/cases/[0-9a-f]{32}/summary',urlsplit(self.path).path)):
            csp = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        for k, v in {"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}.items():
            self.send_header(k, v)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, value, status=200):
        self.send(json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8", status)

    def parts(self):
        parsed = urlsplit(self.path)
        if parsed.netloc or parsed.scheme or parsed.query or parsed.fragment:
            raise WorkflowError("不支持此请求路径")
        path = unquote(parsed.path, errors="strict")
        if any(c in path for c in ("\\", "\x00", "%")) or any(p in {".", ".."} for p in path.split("/")):
            raise WorkflowError("不安全的请求路径")
        return path, path.strip("/").split("/")

    def do_GET(self):
        try:
            self.headers_ok()
            path, parts = self.parts()
            if path in {'/experiments','/experiments.js','/experiments.css','/assets/experiments.js','/assets/experiments.css'}:
                name='experiments.html' if path=='/experiments' else path.split('/')[-1]
                self.send((ASSETS/name).read_bytes(), {'html':'text/html','js':'text/javascript','css':'text/css'}[name.rsplit('.',1)[1]]+'; charset=utf-8')
                return
            if path.startswith('/api/experiments/'):
                from .experiments.service import route_get
                if route_get(self,path,parts):return
            if path in {"/", "/app.js", "/repair.js", "/style.css", "/assets/app.js", "/assets/style.css", "/assets/intake.js", "/assets/repair.js", "/assets/mode.js", "/assets/mode-report.css", "/assets/novice.js", "/assets/certificate-report.css"}:
                name = "index.html" if path == "/" else path.split("/")[-1]
                mime = {"certificate-report.css": "text/css", "novice.js": "text/javascript", "index.html": "text/html", "app.js": "text/javascript", "intake.js": "text/javascript", "repair.js": "text/javascript", "mode.js":"text/javascript", "style.css": "text/css", "mode-report.css": "text/css"}[name]
                self.send((ASSETS / name).read_bytes(), mime + "; charset=utf-8")
            elif path == "/research-certificate":
                from .certificate_archive import overview,render
                self.send(render(overview()).encode('utf-8'), "text/html; charset=utf-8")
            elif path == "/api/research-certificate":
                from .certificate_archive import overview
                self.json(overview())
            elif path == "/api/bootstrap":
                self.json({"service_identity":getattr(self.store,"service_identity",None),"simulation_context":getattr(self.store,"simulation_context",None),"csrf": self.store.csrf, "cases": self.store.list_cases(), "workspaces": self.store.workspace_status(), "runtime": {"meep_available": self.store.meep_available, "workers_enabled": self.store.allow_workers}, "scope": SCOPE, "ai": self.store.ai_status(),
                           "intake": {"modes": intake_api.MODES, "demo": intake_api.DEMO, "native_bridge_enabled": False,
                                      "adapter": self.store.model_adapter.status()},
                           "repair_service": (self.store.pipeline_controller.broker.status() if hasattr(self.store,'pipeline_controller') and self.store.pipeline_controller.broker else {'live_enabled':False,'mode':'RULES_ONLY'} if hasattr(self.store,'pipeline_controller') else None),
                           "mode_status":self.store.mode_controller.status() if hasattr(self.store,'mode_controller') else {'experimental_enabled':False,'runtime_model_calls':0}})
            elif path=='/api/mode-status':
                self.json(self.store.mode_controller.status() if hasattr(self.store,'mode_controller') else {'experimental_enabled':False,'runtime_model_calls':0,'mode':'NOT_ENABLED'})
            elif len(parts)==5 and parts[:2]==['api','cases'] and parts[3] in ('mode-files','mode-before-files'):
                state=self.store.get(parts[2]);result=state.get('adapter_flow',{}).get('initial_result' if parts[3]=='mode-before-files' else 'result') or {}
                if not result.get('derived_report'):raise WorkflowError('尚未形成模态/QPM报告。',409)
                root=self.store.case_dir(parts[2])/result['derived_report']
                if not verify_evidence(root):raise WorkflowError('派生报告证据哈希变化。',409)
                filename=parts[4]
                if filename not in load(root/'manifest.json')['files']:raise WorkflowError('该报告没有这个文件。',404)
                mime='text/html' if filename.endswith('.html') else 'image/svg+xml' if filename.endswith('.svg') else 'application/octet-stream'
                self.send((root/filename).read_bytes(),mime+'; charset=utf-8')
            elif len(parts)==4 and parts[:2]==['api','cases'] and parts[3]=='mode-repaired-candidate':
                state=self.store.get(parts[2]);flow=state.get('adapter_flow') or {};result=flow.get('repair_result') or {}
                if result.get('status')!='completed' or result.get('candidate_sha256')!=digest(flow.get('candidate')):
                    raise WorkflowError('没有完整复验数值配方；失败记录仍可查看。',409)
                from .adapters.mpb_modes import qpm_sources
                qpm_sources(self.store.case_dir(parts[2])/flow['result']['mode_bundle'])
                self.json({'scope':'NUMERICAL_CANDIDATE_ONLY','candidate':flow['candidate'],
                    'task_sha256':result['task_sha256'],'qpm_goal_sha256':result['qpm_goal_sha256'],
                    'mode_verification':result['mode_verification'],'qpm_verification':result['qpm_verification'],
                    'design_goal':result['design_goal'],'not_a_repaired_arbitrary_script':True})
            elif len(parts)==4 and parts[:2]==['api','cases'] and parts[3]=='repaired-recipe':
                state=self.store.get(parts[2])
                if not state.get('repair_result') or not state['repair_result'].get('download_ready'):
                    raise WorkflowError('尚未形成已复验的修正版。',409)
                result=state['repair_result']
                evidence=self.store.case_dir(state['id'])/'artifacts'/result['run_id']
                if (not verify_evidence(evidence) or digest(state['candidate'])!=result['candidate_sha256']
                        or not verify_lock(state['task'],state['approval'])):
                    raise WorkflowError('修正版或证据绑定已经变化；不能下载为已复验版本。',409)
                report=load(evidence/'report.json')
                if report['candidate_hash']!=digest(state['candidate']) or report['task_hash']!=digest(state['task']) or report['status']!=result['status']:
                    raise WorkflowError('修正版与实际运行不对应；停止导出。',409)
                value={'kind':'PHOTONGUARD_CANONICAL_RECIPE_ONLY','original_script_fixed':False,
                    'verification_status':result['status'],'run_id':result['run_id'],
                    'source_binding':state['repair_card']['source_binding']}
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                    for name,data in [('task.json',state['task']),('candidate.json',state['candidate']),('task.lock.json',state['approval']),('verification.json',value)]:
                        archive.writestr(name,json.dumps(data,ensure_ascii=False,indent=2))
                    archive.writestr('README_ZH.txt','这是已复验的规范化配方，不是修复后的原始Python脚本。\n保持三个JSON文件不变，使用对应PhotonGuard版本执行：\npython -m photonguard run task.json candidate.json --lock task.lock.json --out evidence\n这会显式开始最多8次FDTD复验，不调用模型。\n')
                self.send(buffer.getvalue(),'application/zip',filename='reverified-canonical-recipe.zip')
            elif path == '/api/closed-loop-example':
                self.json({'name':'wavelength35_index_mismatch.py',
                    'source':(PROJECT/'examples/script_import/wavelength35_index_mismatch.py').read_text(),
                    'synthetic':True,'script_executed':False})
            elif len(parts) == 4 and parts[:2] == ['api', 'cases'] and parts[3] == 'mapping-handoff':
                state = self.store.get(parts[2])
                self.json(intake_api.mapping_handoff(state.get('intake')))
            elif path == "/docs/import-limitations":
                self.send((PROJECT / "docs/IMPORT_LIMITATIONS.md").read_bytes(), "text/plain; charset=utf-8")
            elif len(parts) == 3 and parts[:2] == ["api", "cases"]:
                self.json(self.store.get(parts[2]))
            elif len(parts) >= 6 and parts[:2] == ["api", "cases"] and parts[3] == "runs":
                ident, run_id = parts[2], parts[4]
                state = self.store.get(ident)
                if run_id not in {r["run_id"] for r in state["runs"]}:
                    raise WorkflowError("当前任务没有此运行记录", 404)
                evidence = self.store.evidence(ident, run_id)
                if not verify_evidence(evidence._run_path(run_id)):
                    raise WorkflowError("运行证据哈希校验失败", 409)
                if len(parts)==6 and parts[5]=='bundle':
                    from .novice_export import bundle
                    self.send(bundle(self.store,state,run_id),'application/zip',filename='PhotonGuard-'+ident[:8]+'-'+run_id+'.zip')
                elif len(parts) == 6 and parts[5] == "spectrum":
                    rows = evidence.spectrum(run_id)
                    numeric = []
                    for row in rows:
                        converted = {key: float(row[key]) for key in ("frequency", "wavelength_um", "R", "T", "R_reference", "T_reference")}
                        if not all(finite(value) for value in converted.values()):
                            raise WorkflowError("光谱含非有限数值，停止绘图；请查看原始 CSV", 422)
                        numeric.append(converted)
                    self.json({"spectrum": numeric, "source": "spectrum.csv", "transformation": "finite CSV numeric parsing only"})
                elif len(parts) == 6 and parts[5] == "files":
                    self.json({"files": evidence.files(run_id)})
                elif len(parts) >= 7 and parts[5] == "files":
                    self.send(evidence.download(run_id, "/".join(parts[6:])), "application/octet-stream", filename=parts[-1])
                else:
                    raise WorkflowError("接口不存在", 404)
            elif len(parts) == 3 and parts[0] == "reports":
                ident, run_id = parts[1:]
                state = self.store.get(ident)
                if run_id not in {r["run_id"] for r in state["runs"]}:
                    raise WorkflowError("当前任务没有此运行记录", 404)
                evidence = self.store.evidence(ident, run_id)
                if not verify_evidence(evidence._run_path(run_id)):
                    raise WorkflowError("运行证据哈希校验失败", 409)
                self.send(page("真实 Meep 验收证据", render_fragment({**evidence.report(run_id), 'workspace_case_id': ident}, evidence.spectrum(run_id)), navigation=f'<p><a href="/#case={ident}">← 返回工作流</a> · <a href="/api/cases/{ident}/runs/{run_id}/files/report.json">下载原始报告 JSON</a></p>').encode(), "text/html; charset=utf-8")
            else:
                raise WorkflowError("接口不存在", 404)
        except (WorkflowError, EvidenceError) as e:
            self.json({"error": str(e)}, e.status)
        except (ValueError, TypeError, KeyError, OSError, RecursionError):
            self.json({"error": "无法读取此记录；未启动任何额外操作"}, 422)

    do_HEAD = do_GET

    def do_POST(self):
        self.connection.settimeout(5)
        try:
            self.headers_ok(mutate=True)
            path, parts = self.parts()
            length = int(self.headers["Content-Length"])
            limit = 3 * 1024 * 1024 if path in ('/api/experiments/observations','/api/experiments/inverse') else MAX_BODY
            if not 0 < length <= limit:
                raise WorkflowError("请求过大或为空", 413)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise WorkflowError("请求正文不完整")
            data = parse_json(raw)
            if not isinstance(data, dict):
                raise WorkflowError("请求必须是 JSON 对象")
            if path.startswith('/api/experiments/'):
                from .experiments.service import route_post
                if route_post(self,path,parts,data):return
            if path == "/api/cases":
                if 'mode' not in data or set(data) - {'mode', 'workspace_id'}:
                    raise WorkflowError('只接受 mode 和 workspace_id 字段')
                self.json(self.store.create(data['mode'], data.get('workspace_id','default')), 201)
            elif path == '/api/workspaces':
                if set(data) != {'label'}:
                    raise WorkflowError('只接受工作区名称')
                self.json(self.store.create_workspace(data['label']), 201)
            elif path=='/api/mode-demo':
                if set(data)-{'workspace_id'} or not hasattr(self.store,'mode_controller'):raise WorkflowError('当前入口没有启用模态实验。',409)
                self.json(self.store.mode_controller.create_demo(data.get('workspace_id','default')),201)
            elif len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "action":
                self.json(self.store.action(parts[2], data))
            else:
                raise WorkflowError("接口不存在", 404)
        except (WorkflowError, EvidenceError) as e:
            self.json({"error": str(e)}, e.status)
        except (ValueError, TypeError, KeyError, OSError, RecursionError):
            self.json({"error": "输入或存储无效，操作安全停止；请刷新核对当前状态"}, 422)

    def unsupported(self):
        self.json({"error": "不支持此方法"}, 405)

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = unsupported


def make_server(root, host="127.0.0.1", port=8766, *, allow_workers=True, model_adapter=None):
    if host != "127.0.0.1":
        raise WorkflowError("工作流仅绑定 127.0.0.1；不支持公网或全接口监听")
    store = WorkflowStore(root, allow_workers=allow_workers, model_adapter=model_adapter)
    try:
        server = ThreadingHTTPServer((host, port), WorkflowHandler)
    except Exception:
        store.close()
        raise
    server.daemon_threads = True
    server.store = store
    original_close = server.server_close
    def close():
        original_close()
        store.close()
    server.server_close = close
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="PhotonGuard 本机工作台；默认本地模式，可在实验页连接自己的 AI")
    parser.add_argument("--data", default="workflow-data", help="服务端拥有的工作区目录；浏览器不能指定写入路径")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--offline-review", action="store_true", help="禁用求解工作进程；仅本地材料审阅")
    args = parser.parse_args(argv)
    with make_server(args.data, port=args.port, allow_workers=not args.offline_review) as server:
        print(f"PhotonGuard local graphical workflow: http://127.0.0.1:{server.server_port}/", flush=True)
        print("AI starts disconnected; configure at /experiments · Real Meep available: " + str(server.store.meep_available), flush=True)
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            print("UI stopped. Already started bounded solver jobs may finish their durable receipts.", flush=True)


if __name__ == "__main__":
    main()
