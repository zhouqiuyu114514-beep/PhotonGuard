"""Read-only loopback evidence viewer. No uploads, shell, or code execution."""

from __future__ import annotations

import csv
import io
import ipaddress
import json
import re
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .report import STATUSES, STATUS_LABELS, badge, escape, page, render_fragment, render_report, status_name


_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z")
_TEXT_SUFFIXES = {".json", ".csv", ".txt", ".log", ".yaml", ".yml", ".patch", ".diff", ".py", ".html", ".md"}
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024
_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"


class EvidenceError(Exception):
    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


def _safe_segment(value: str) -> bool:
    return bool(_SEGMENT.fullmatch(value)) and ".." not in value


class EvidenceStore:
    """Read a project or artifacts directory, containing access within that root."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.artifacts = self.root if self.root.name == "artifacts" else self.root / "artifacts"
        self.project = self.root.parent if self.root.name == "artifacts" else self.root
        if self.artifacts.is_symlink():
            raise ValueError("The artifacts directory must not be a symlink")

    def _run_path(self, run_id: str) -> Path:
        if not _safe_segment(run_id):
            raise EvidenceError("Invalid run ID", 400)
        target = self.artifacts / run_id
        if self.artifacts.is_symlink() or target.is_symlink():
            raise EvidenceError("Symlink evidence is not served", 403)
        if not target.is_dir():
            raise EvidenceError("Run not found")
        try:
            target.resolve().relative_to(self.artifacts.resolve())
        except ValueError:
            raise EvidenceError("Evidence path is outside artifacts", 403) from None
        return target

    def _file_path(self, run_id: str, relative: str) -> Path:
        parts = relative.split("/")
        if not parts or any(not _safe_segment(part) for part in parts):
            raise EvidenceError("Invalid evidence path", 400)
        current = self._run_path(run_id)
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise EvidenceError("Symlink evidence is not served", 403)
        if current.suffix.lower() not in _TEXT_SUFFIXES or not current.is_file():
            raise EvidenceError("Evidence file not found")
        try:
            current.resolve().relative_to(self._run_path(run_id).resolve())
        except ValueError:
            raise EvidenceError("Evidence path is outside this run", 403) from None
        return current

    @staticmethod
    def _read(path: Path, limit: int = _MAX_FILE_BYTES) -> bytes:
        try:
            with path.open("rb") as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise EvidenceError("Evidence file exceeds viewer size limit", 413)
            return data
        except (OSError, UnicodeError):
            raise EvidenceError("Evidence file is unreadable", 422) from None

    def report(self, run_id: str) -> dict:
        raw = self._read(self._file_path(run_id, "report.json"), _MAX_JSON_BYTES)
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise EvidenceError("Report is not valid JSON", 422) from None
        if not isinstance(result, dict):
            raise EvidenceError("Report must be a JSON object", 422)
        return result

    def spectrum(self, run_id: str) -> list[dict]:
        # Missing spectra are expected for rejected or unsupported cases.
        try:
            path = self._file_path(run_id, "spectrum.csv")
        except EvidenceError as error:
            if error.status == 404:
                self._run_path(run_id)
                return []
            raise
        try:
            data = self._read(path).decode("utf-8-sig")
            rows = []
            for row in csv.DictReader(io.StringIO(data)):
                if len(rows) >= 50000:
                    raise EvidenceError("Spectrum exceeds viewer row limit", 413)
                rows.append(row)
            return rows
        except (UnicodeError, csv.Error):
            raise EvidenceError("Spectrum is not readable CSV", 422) from None

    def files(self, run_id: str) -> list[dict]:
        run_path = self._run_path(run_id)
        result = []
        # Traversal depth is deliberately bounded; rglob can follow symlinked dirs
        # on some Python versions and would unnecessarily scan unrelated trees.
        for directory in (run_path, run_path / "raw"):
            if directory.is_symlink() or not directory.is_dir():
                continue
            for file in sorted(directory.iterdir()):
                relative = file.relative_to(run_path).as_posix()
                try:
                    safe = self._file_path(run_id, relative)
                    result.append({"name": relative, "bytes": safe.stat().st_size})
                except (EvidenceError, OSError):
                    continue
                if len(result) >= 200:
                    return result
        return result

    def download(self, run_id: str, relative: str) -> bytes:
        return self._read(self._file_path(run_id, relative))

    def runs(self) -> list[dict]:
        if not self.artifacts.exists():
            return []
        if self.artifacts.is_symlink() or not self.artifacts.is_dir():
            raise EvidenceError("Artifacts directory is not readable", 403)
        results = []
        for entry in sorted(self.artifacts.iterdir(), reverse=True):
            if not _safe_segment(entry.name) or entry.is_symlink() or not entry.is_dir():
                continue
            try:
                report = self.report(entry.name)
                results.append({"run_id": entry.name,
                                "reported_run_id": report.get("run_id"),
                                "case_id": report.get("case_id", "未命名案例"),
                                "status": status_name(report.get("status")),
                                "created_at": report.get("created_at", ""),
                                "candidate_hash": report.get("candidate_hash", ""),
                                "has_patch": report.get("patch") is not None,
                                "readable": True})
            except EvidenceError as error:
                results.append({"run_id": entry.name, "case_id": "不可读取的证据", "status": "INCONCLUSIVE",
                                "created_at": "", "readable": False, "error": str(error)})
        return results

    def cases(self) -> list[dict]:
        """List cases represented in saved evidence, without executing manifests."""
        grouped: dict[str, dict[str, Any]] = {}
        for run in self.runs():
            name = str(run["case_id"])
            item = grouped.setdefault(name, {"case_id": name, "run_ids": [], "statuses": []})
            item["run_ids"].append(run["run_id"])
            if run["status"] not in item["statuses"]:
                item["statuses"].append(run["status"])
        return sorted(grouped.values(), key=lambda item: item["case_id"])


def _home(store: EvidenceStore) -> str:
    runs = store.runs()
    counts = {status: sum(run["status"] == status for run in runs) for status in STATUSES}
    body = ('<div class="hero"><p class="eyebrow">Local verification workspace</p>'
            '<h1>让每个光学结论，都有证据</h1>'
            '<p class="muted">查看验证记录、数值检查和修复前后差异。仅在本机读取证据，模型来源以每次报告记录为准。</p></div>'
            '<div class="grid">')
    for status in STATUSES:
        body += f'<div class="card">{badge(status)}<div class="metric">{counts[status]}</div><small>{STATUS_LABELS[status]}</small></div>'
    body += ('</div><section class="card"><h2>支持范围</h2><p class="note">1D · 无损 · 无色散 · 正入射 · 空气–薄膜–空气</p>'
             '<p class="muted">PASS：当前检查通过 · FAIL：明确发现问题 · INCONCLUSIVE：证据不足 · UNSUPPORTED：超出范围</p></section>'
             '<section class="card"><h2>证据记录 / Runs</h2>')
    if runs:
        body += '<div class="table-wrap"><table><thead><tr><th>案例 / Run</th><th>状态</th><th>时间</th><th>详情</th></tr></thead><tbody>'
        for run in runs:
            run_id = escape(run["run_id"])
            body += (f'<tr><td><span class="run-link">{escape(run["case_id"])}</span><br><code>{run_id}</code></td>'
                     f'<td>{badge(run["status"])}</td><td>{escape(run["created_at"] or "未记录")}</td><td>')
            if run["readable"]:
                body += f'<a href="/reports/{run_id}">查看证据 →</a>'
            else:
                body += escape(run["error"])
            body += '</td></tr>'
        body += '</tbody></table></div>'
    else:
        body += '<div class="empty"><h3>尚无验证记录</h3><p>先用 PhotonGuard CLI 运行案例，再刷新此页。缺少 artifacts 目录不会触发任何仿真。</p></div>'
    body += '</section>'
    readable = [run for run in runs if run["readable"]]
    if readable:
        options = ''.join(f'<option value="{escape(run["run_id"])}">{escape(run["case_id"])} · {escape(run["run_id"])}</option>' for run in readable)
        body += ('<section class="card"><h2>原始 / 修复后比较</h2><p class="muted">选择两条独立运行记录。此操作只比较已有证据，不修改输入或启动求解器。</p>'
                 '<form action="/compare" method="get" class="form-grid">'
                 f'<label>原始记录<select name="original" required>{options}</select></label>'
                 f'<label>修复后记录<select name="repaired" required>{options}</select></label>'
                 '<button type="submit">比较证据</button></form></section>')
    return page("本地验证工作台", body)


def _loopback_host(host: str) -> bool:
    # Bind to literal addresses only: do not rely on mutable DNS resolution.
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


class EvidenceHandler(BaseHTTPRequestHandler):
    server_version = "PhotonGuardLocal/1"
    sys_version = ""

    def __init__(self, *args: Any, store: EvidenceStore, **kwargs: Any):
        self.store = store
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        # Never echo untrusted request paths or evidence into terminal escapes.
        return

    def _host_allowed(self) -> bool:
        try:
            authority = self.headers.get("Host", "")
            if any(character in authority for character in "/\\@?#"):
                return False
            parsed = urlsplit("//" + authority)
            return bool(parsed.hostname and _loopback_host(parsed.hostname)
                        and parsed.port == self.server.server_port)
        except ValueError:
            return False

    def _send(self, payload: bytes, content_type: str, status: int = 200, *, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if filename is not None:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, value: Any, status: int = 200) -> None:
        self._send(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._json({"error": "Only the local viewer host is allowed"}, 403)
            return
        try:
            self._get()
        except EvidenceError as error:
            self._json({"error": str(error)}, error.status)
        except (OSError, ValueError, TypeError, RecursionError):
            self._json({"error": "Evidence could not be displayed"}, 422)

    def _get(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc:
            raise EvidenceError("Only relative local request paths are allowed", 400)
        path = unquote(parsed.path, errors="strict")
        if any(character in path for character in ("\\", "\x00")) or any(part in (".", "..") for part in path.split("/")):
            raise EvidenceError("Invalid path", 400)
        parts = path.strip("/").split("/")
        if path == "/":
            self._send(_home(self.store).encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/runs":
            self._json({"runs": self.store.runs(), "read_only": True, "ai_connected": False})
        elif path == "/api/cases":
            self._json({"cases": self.store.cases()})
        elif path == "/api/health":
            self._json({"status": "ok", "read_only": True, "ai_connected": False})
        elif len(parts) >= 3 and parts[:2] == ["api", "runs"]:
            run_id = parts[2]
            if len(parts) == 3:
                self._json(self.store.report(run_id))
            elif len(parts) == 4 and parts[3] == "spectrum":
                self._json({"spectrum": self.store.spectrum(run_id)})
            elif len(parts) == 4 and parts[3] == "files":
                self._json({"files": self.store.files(run_id)})
            elif len(parts) >= 5 and parts[3] == "files":
                relative = "/".join(parts[4:])
                self._send(self.store.download(run_id, relative), "application/octet-stream", filename=parts[-1])
            else:
                raise EvidenceError("Endpoint not found")
        elif len(parts) == 2 and parts[0] == "reports":
            run_id = parts[1]
            report = self.store.report(run_id)
            spectra = self.store.spectrum(run_id)
            links = '<p><a href="/">← 返回全部运行</a></p><section class="card"><h2>下载原始证据</h2><ul>'
            for file in self.store.files(run_id):
                links += f'<li><a href="/api/runs/{escape(run_id)}/files/{escape(file["name"])}">{escape(file["name"])}</a> <small>{file["bytes"]} bytes</small></li>'
            links += '</ul></section>'
            self._send(page(str(report.get("case_id", "Evidence report")), render_fragment(report, spectra), navigation=links).encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/compare":
            query = parse_qs(parsed.query, max_num_fields=8)
            original = query.get("original", [""])[0]
            repaired = query.get("repaired", [""])[0]
            first, second = self.store.report(original), self.store.report(repaired)
            warning = ('<p class="note">当前选择了同一条记录；这不代表已完成修复。</p>' if original == repaired else '')
            body = ('<h1>原始 / 修复后证据</h1><p class="muted">并排比较独立证据；请核对任务哈希、物理前提和候选哈希是否可比。</p>' + warning + '<div class="compare">'
                    '<section><h2>原始记录</h2>' + render_fragment(first, self.store.spectrum(original)) + '</section>'
                    '<section><h2>修复后记录</h2>' + render_fragment(second, self.store.spectrum(repaired)) + '</section></div>')
            self._send(page("证据比较", body, navigation='<p><a href="/">← 返回全部运行</a></p>').encode("utf-8"), "text/html; charset=utf-8")
        else:
            raise EvidenceError("Endpoint not found")

    def _unsupported(self) -> None:
        self._json({"error": "The evidence viewer is read-only; use GET or HEAD"}, 405)

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _unsupported


def make_server(root: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Create an unstarted server, useful for CLI integration and ephemeral tests."""
    if not _loopback_host(host):
        raise ValueError("PhotonGuard UI may only bind to a loopback address")
    if host == "localhost":
        host = "127.0.0.1"
    handler = partial(EvidenceHandler, store=EvidenceStore(root))
    if ":" in host:
        import socket
        class IPv6Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        server = IPv6Server((host, port), handler)
    else:
        server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve saved evidence on loopback until Ctrl-C. Does not run simulations."""
    with make_server(root, host, port) as server:
        bound = server.server_address[0]
        address = f"[{bound}]" if ":" in bound else bound
        print(f"PhotonGuard read-only UI: http://{address}:{server.server_port}/", flush=True)
        try:
            server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            pass
