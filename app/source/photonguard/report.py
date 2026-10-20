"""Dependency-free, escaped HTML rendering for immutable PhotonGuard evidence."""

from __future__ import annotations

import html
import json
import math
from typing import Any


STATUSES = ("PASS", "FAIL", "INCONCLUSIVE", "UNSUPPORTED")
STATUS_LABELS = {
    "PASS": "通过检查",
    "FAIL": "发现问题",
    "INCONCLUSIVE": "证据不足",
    "UNSUPPORTED": "超出支持范围",
}
STYLE = """
:root{color-scheme:light;--ink:#15283a;--muted:#526a7b;--line:#dbe4e8;
--paper:#f3f6f5;--green:#127c60;--blue:#2563ad;--red:#a8303c;--amber:#8a5b0b}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans CJK SC',sans-serif}
a{color:var(--blue);text-underline-offset:3px}a:hover{color:var(--green)}
main{max-width:1180px;margin:auto;padding:32px 24px 60px}h1,h2,h3,p{margin-top:0}
h1{font-size:36px;line-height:1.2;letter-spacing:-1px;margin-bottom:14px}
h2{font-size:20px;letter-spacing:-.35px}h3{font-size:15px}.muted,small{color:var(--muted)}
.brand{font-weight:800;font-size:17px;letter-spacing:-.4px}.brand span{color:var(--green)}
header{display:flex;justify-content:space-between;align-items:center;gap:20px;
padding:20px 0 30px}.eyebrow{font-size:12px;letter-spacing:1.7px;text-transform:uppercase;
color:var(--green);font-weight:700}.hero{padding:28px 0 22px}.hero p{max-width:820px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:24px;
margin:18px 0;box-shadow:0 3px 12px #132b3b04}.grid{display:grid;
grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}.grid>.card{margin:0}
.metric{font-size:28px;font-weight:750;line-height:1.3}.label{font-size:12px;
font-weight:700;color:var(--muted);letter-spacing:.4px}.badge{display:inline-block;
font-size:12px;line-height:1.4;font-weight:800;letter-spacing:.5px;padding:7px 11px;
border:1px solid;border-radius:999px;white-space:nowrap}.PASS{color:#11644e;background:#e7f7f0;
border-color:#b7e4d1}.FAIL{color:#9b2335;background:#fff0f1;border-color:#f2c8cd}
.INCONCLUSIVE{color:#835a10;background:#fff7e5;border-color:#ecd9a7}
.UNSUPPORTED{color:#586676;background:#f1f3f6;border-color:#d9dfe8}
.statuses{display:flex;flex-wrap:wrap;gap:12px}.statuses small{margin-left:5px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;
padding:13px 12px;vertical-align:top;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--muted);font-weight:700;background:#f8faf9}
td:first-child,th:first-child{padding-left:0}.table-wrap{overflow:auto}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;
overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f5f7f8;border:1px solid var(--line);
padding:16px;border-radius:8px}details{margin:12px 0}summary{cursor:pointer;font-weight:600}
ul{padding-left:22px}li{margin:5px 0}.meta{display:grid;grid-template-columns:145px 1fr;
gap:10px 20px}.meta dt{color:var(--muted)}.meta dd{margin:0;overflow-wrap:anywhere}
.note{border-left:3px solid var(--green);padding:10px 16px;background:#eff8f4}
.empty{padding:34px;text-align:center;color:var(--muted)}.chart{width:100%;height:auto;
display:block}.legend{display:flex;flex-wrap:wrap;gap:18px;font-size:12px}.legend i{
display:inline-block;width:23px;height:3px;vertical-align:middle;margin-right:5px}
footer{font-size:12px;color:var(--muted);margin-top:24px}.run-link{font-weight:700}
select,button{font:inherit;border:1px solid #cdd9df;border-radius:8px;padding:10px;
background:white;color:var(--ink);max-width:100%}button{background:var(--ink);color:#fff;
cursor:pointer;padding:10px 20px}.form-grid{display:flex;flex-wrap:wrap;gap:16px;align-items:end}
.form-grid label{display:grid;gap:5px;flex:1;min-width:180px}.compare{display:grid;
grid-template-columns:1fr 1fr;gap:20px}.compare>section{min-width:0}.compare .meta{
grid-template-columns:100px 1fr}.compare h1{font-size:26px}.compare .grid{grid-template-columns:1fr}
@media(max-width:750px){main{padding:14px 16px 40px}h1{font-size:29px}.card{padding:17px}
header{align-items:flex-start}.compare{grid-template-columns:1fr}.meta{grid-template-columns:1fr;
gap:3px}.meta dd{margin-bottom:10px}.statuses small{display:none}}
"""


def escape(value: Any) -> str:
    """Escape *all* evidence-controlled text, including attribute quotes."""
    return html.escape(str(value if value is not None else "—"), quote=True)


def status_name(value: Any) -> str:
    candidate = str(value).upper()
    return candidate if candidate in STATUSES else "INCONCLUSIVE"


def badge(value: Any) -> str:
    status = status_name(value)
    return f'<span class="badge {status}">{status}</span>'


def _json(value: Any) -> str:
    return escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _items(value: Any, empty: str) -> str:
    if not isinstance(value, list) or not value:
        return f'<p class="muted">{escape(empty)}</p>'
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in value) + "</ul>"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def spectrum_chart(spectra: list[dict]) -> str:
    """Return a static SVG chart. Non-finite or malformed points are skipped."""
    fields = (("R", "#127c60", ""), ("T", "#2563ad", ""),
              ("R_reference", "#127c60", "6 4"), ("T_reference", "#2563ad", "6 4"))
    rows = []
    for row in spectra:
        if not isinstance(row, dict):
            continue
        wavelength = _number(row.get("wavelength_um"))
        if wavelength is not None:
            rows.append((wavelength, {key: _number(row.get(key)) for key, _, _ in fields}))
    rows.sort(key=lambda item: item[0])
    values = [value for _, row in rows for value in row.values() if value is not None]
    if not rows or not values:
        return '<p class="empty">暂无可绘制的光谱数据 / No spectrum data</p>'
    xmin, xmax = rows[0][0], rows[-1][0]
    if xmin == xmax:
        padding = max(abs(xmin) * 0.01, 0.01)
        xmin, xmax = xmin - padding, xmax + padding
    ymin, ymax = min(0.0, min(values)), max(1.0, max(values))
    if not math.isfinite(xmax - xmin) or not math.isfinite(ymax - ymin) or xmax <= xmin:
        return '<p class="empty">光谱数值范围过大，无法绘图 / Invalid plot range</p>'
    width, height = 900, 320
    left, top, pw, ph = 66, 18, 804, 244
    def point(x: float, y: float) -> str:
        return f"{left + (x-xmin)/(xmax-xmin)*pw:.2f},{top + (ymax-y)/(ymax-ymin)*ph:.2f}"
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             'aria-label="Reflectance and transmittance versus wavelength">',
             '<title>R / T spectrum, solid: simulation, dashed: analytic reference</title>']
    for i in range(5):
        y = top + ph * i / 4
        label = ymax - (ymax - ymin) * i / 4
        parts.append(f'<line x1="{left}" y1="{y}" x2="{left+pw}" y2="{y}" stroke="#e2e8ed"/>'
                     f'<text x="54" y="{y+4}" text-anchor="end" fill="#526a7b" font-size="12">{label:.3g}</text>')
    for i in range(5):
        x = left + pw * i / 4
        label = xmin + (xmax - xmin) * i / 4
        parts.append(f'<text x="{x}" y="284" text-anchor="middle" fill="#526a7b" font-size="12">{label:.4g}</text>')
    for key, color, dash in fields:
        if key in ("R", "T"):
            for x, row in rows:
                if row[key] is not None:
                    px, py = point(x, row[key]).split(",")
                    parts.append(f'<circle cx="{px}" cy="{py}" r="2.3" fill="{color}"/>')
        # Split at missing values instead of drawing across a gap in evidence.
        segments: list[list[str]] = [[]]
        for x, row in rows:
            value = row[key]
            if value is None:
                if segments[-1]:
                    segments.append([])
            else:
                segments[-1].append(point(x, value))
        for segment in segments:
            if len(segment) == 1:
                x, y = segment[0].split(",")
                parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>')
            elif segment:
                parts.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" '
                             f'stroke-width="2" stroke-dasharray="{dash}"/>')
    parts.append('<text x="468" y="312" text-anchor="middle" fill="#526a7b" font-size="12">Wavelength / 波长 (μm)</text></svg>')
    parts.append('<div class="legend"><span><i style="background:#127c60"></i>R 反射率</span>'
                 '<span><i style="background:#2563ad"></i>T 透射率</span>'
                 '<span>实线: 仿真 · 虚线: 解析参考</span></div>')
    return "".join(parts)


def _display_origin(value):
    # Only the rendering is compacted. Hashed JSON and original script bytes stay intact.
    if isinstance(value, dict):
        return {k: ('原脚本字节保存在原始报告JSON；此处省略base64' if k == 'source_bytes_base64' else _display_origin(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_display_origin(v) for v in value]
    return value


def _check_label(ident):
    if ident == 'task_parameters':
        return '需求与候选的材料、厚度一致性；能量守恒不能替代此项'
    prefix = next((p for p in ('base_', 'grid_', 'time_', 'pml_') if ident.startswith(p)), '')
    setting = {'base_':'原设置','grid_':'加密网格','time_':'延长时间','pml_':'增厚吸收边界'}.get(prefix, '')
    name = ident[len(prefix):]
    meanings = {'independent_tmm':'与锁定需求的独立薄膜理论参考对比',
                'energy':'无损能量守恒', 'energy_balance':'无损能量守恒',
                'grid_sensitivity':'网格变化引起的光谱差异',
                'time_sensitivity':'时间变化引起的光谱差异',
                'pml_sensitivity':'吸收边界变化引起的光谱差异'}
    meaning = meanings.get(ident, meanings.get(name))
    if meaning is None:
        return None
    return (setting + '：' if setting and ident not in meanings else '') + meaning


def render_fragment(report: dict, spectra: list[dict]) -> str:
    """Render the report body; suitable for a read-only comparison page."""
    status = status_name(report.get("status"))
    backend = report.get("backend") if isinstance(report.get("backend"), dict) else {}
    usage = report.get("resource_usage") if isinstance(report.get("resource_usage"), dict) else {}
    wall = _number(usage.get("wall_seconds"))
    duration = f"{wall:.2f} s" if wall is not None else "未记录"
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    parts = [f'<div class="hero"><p class="eyebrow">Evidence report / 验证证据</p>'
             f'<h1>{escape(report.get("case_id", "未命名案例"))}</h1>'
             f'{badge(status)} <span class="muted">{STATUS_LABELS[status]}</span></div>',
             f'<p class="muted">工作区案例 ID：{escape(report.get("workspace_case_id", "独立报告未绑定工作区"))} · 物理任务 ID：{escape(report.get("case_id"))}</p>',
             '<div class="grid">',
             f'<div class="card"><div class="label">物理求解 / FDTD RUNS</div><div class="metric">{escape(usage.get("fdtd_runs", "未记录"))}</div></div>',
             f'<div class="card"><div class="label">耗时 / WALL TIME</div><div class="metric">{escape(duration)}</div></div>',
             f'<div class="card"><div class="label">运行时 API 调用</div><div class="metric">{escape(backend.get("runtime_api_calls", backend.get("actual_llm_calls", "未记录")))}</div></div>',
             '</div>',
             '<section class="card"><h2>验证范围</h2><p class="note">1D · 无损 · 无色散 · 正入射 · 空气–薄膜–空气</p>'
             '<p class="muted">本页面仅呈现已保存证据，不运行候选代码。PASS 仅表示当前模型、频段、容差和检查项通过，不构成普适正确性证明。</p></section>',
             '<section class="card"><h2>检查项 / Checks</h2>']
    scope = report.get("execution_scope")
    if isinstance(scope, dict):
        parts.insert(-1, '<section class="card"><h2>脚本导入范围 / Script import scope</h2><p class="note">' + escape(scope.get("claim")) + '</p><p>未执行原始 Python；状态仅针对提取的规范化配方。修复后的通过不表示原始脚本通过。</p><pre>' + _json(scope) + '</pre></section>')
    if not checks:
        parts.append('<p class="muted">未记录检查项</p>')
    for check in checks:
        if not isinstance(check, dict):
            continue
        parts.append(f'<article><h3>{badge(check.get("status"))} {escape(check.get("id", "check"))}</h3>'
                     f'<p>{escape(check.get("summary", "未提供说明"))}</p>')
        label = _check_label(str(check.get('id','')))
        if label:
            parts.append('<p class="note">' + escape(label) + '</p>')
        metrics = check.get("metrics")
        if isinstance(metrics,dict):
            measured = metrics.get('max_absolute_error', metrics.get('max_absolute_change'))
            if measured is not None and 'tolerance' in metrics:
                parts.append('<p>本次最大差异：' + escape(measured) + '；固定阈值：' + escape(metrics['tolerance']) + '。只适用于记录的离散采样和设置。</p>')
        if metrics is not None:
            parts.append(f'<details open><summary>数值证据 / Metrics</summary><pre>{_json(metrics)}</pre></details>')
        parts.append('</article>')
    parts.append('</section><section class="card"><h2>光谱 / Spectrum</h2>')
    sampling = report.get('sampling')
    if sampling:
        parts.append('<p class="note">采样依据：保留原始等波长要求。每个圆点是实际DFT通量求解点；插值点数为0。连接线仅帮助阅读，不代表额外仿真。实际点数：' + escape(sampling.get('actual_solver_point_count')) + '。</p>')
        parts.append('<details><summary>实际求解频率与波长清单</summary><pre>' + _json(sampling) + '</pre></details>')
    parts.append(spectrum_chart(spectra))
    parts.append('</section><section class="card"><h2>运行记录 / Provenance</h2><dl class="meta">')
    for key, label in (("run_id", "运行 ID"), ("created_at", "创建时间"),
                       ("task_hash", "任务 SHA-256"), ("candidate_hash", "候选 SHA-256")):
        parts.append(f'<dt>{label}</dt><dd><code>{escape(report.get(key, "未记录"))}</code></dd>')
    parts.append(f'<dt>后端</dt><dd>{escape(backend.get("mode", "未记录"))}</dd></dl>')
    if backend.get("mode")=="rules_only":parts.append('<p>AI 未连接；本次是规则流程，没有模型调用。</p>')
    parts.append('<details><summary>模型来源记录</summary><pre>'+_json(backend)+'</pre></details>')
    for key, label in (("resource_usage", "完整资源记录"), ("environment", "执行环境与代码哈希"),
                       ("policy", "冻结检查策略"), ("origin", "候选来源 / 修复来源")):
        if report.get(key):
            parts.append(f'<details><summary>{label}</summary><pre>{_json(_display_origin(report[key]) if key == "origin" else report[key])}</pre></details>')
    parts.append('</section>')
    parts.append('<section class="card"><h2>前提 / Assumptions</h2>' +
                 _items(report.get("assumptions"), "未记录前提") + '</section>')
    parts.append('<section class="card"><h2>边界与限制 / Limitations</h2>' +
                 _items(report.get("limitations"), "未记录额外限制；仍受上方验证范围约束") + '</section>')
    if report.get("patch") is not None:
        parts.append('<section class="card"><h2>修复建议与记录 / Patch evidence</h2><pre>' +
                     _json(report["patch"]) + '</pre><p class="muted">修复是否成功必须以独立的修复后运行记录为准。</p></section>')
    if report.get("files"):
        # Do not trust evidence-supplied URLs or turn them into executable links.
        parts.append('<section class="card"><h2>证据清单 / Files</h2><pre>' + _json(report["files"]) + '</pre></section>')
    return "".join(parts)


def page(title: str, body: str, *, navigation: str = "") -> str:
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            "style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'self'\">"
            f'<title>{escape(title)} · PhotonGuard</title><style>{STYLE}</style></head><body><main>'
            '<header><div class="brand"><span>◈</span> PhotonGuard</div>'
            '<span class="muted">本地只读证据查看器</span></header>' + navigation + body +
            '<footer>PhotonGuard · Local prototype · 规则与物理证据 / Rules + physics evidence<br>'
            '模型来源以本次报告记录为准；没有伪装的实时 AI 输出。查看器不发起模型调用或外部网络请求。</footer></main></body></html>')


def render_report(report: dict, spectra: list[dict]) -> str:
    """Build a portable HTML evidence report with no external assets or scripts."""
    return page(str(report.get("case_id", "Evidence report")), render_fragment(report, spectra))
