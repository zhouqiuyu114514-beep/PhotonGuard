"""Fixed-command, single-thread worker. No uploaded Python or client commands."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
from .runner import run_case


def main():
    root, candidate, job_id, receipt_name = sys.argv[1:]
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Worker root must not contain symlinks")
    root = root.resolve()
    if not re.fullmatch(r"candidate-[a-f0-9]{32}\.json", candidate) or not re.fullmatch(r"[a-f0-9]{32}", job_id) or receipt_name != "job-" + job_id + ".json":
        raise ValueError("Invalid server-owned worker arguments")
    for name in ("task.json", "task.lock.json", candidate, "artifacts", receipt_name, "." + receipt_name + ".tmp"):
        if (root / name).is_symlink():
            raise ValueError("Worker paths must not be symlinks")
    if (root / receipt_name).exists():
        raise FileExistsError("A job receipt already exists; refusing overwrite")
    started = root / ("started-" + job_id + ".json")
    with started.open("x", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "pid": os.getpid()}, f)
        f.flush()
        os.fsync(f.fileno())
    result = {"job_id": job_id}
    try:
        from .experiments.executor import solver_mutex
        with solver_mutex():
            report, out = run_case(root / "task.json", root / candidate, root / "task.lock.json", root / "artifacts")
        result.update(status="completed", run_id=out.name, verification_status=report["status"])
    except Exception as exc:
        result.update(status="failed", error="受限工作进程未完成验收：" + type(exc).__name__)
    target = root / receipt_name
    temp = root / ("." + receipt_name + ".tmp")
    with temp.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    # Hard-link publication is atomic and refuses an existing receipt.
    os.link(temp, target)
    temp.unlink()


if __name__ == "__main__":
    main()
