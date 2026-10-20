# PhotonGuard 需求录入 V2 交付复核

本说明取代首轮交付结论。首轮确实只有规则 mock / 已有响应导入，没有模型适配器；不得把首轮说成真实 AI 接入完成。V2 已实现可由服务端注入新授权绑定的 DeepSeek 语义适配接口，并通过 mock transport 跑通工具续接。**当前服务真实调用审批门关闭，未配置 live 启动入口、未读取真实密钥、未发出模型请求。**

## 交付和现有演示

隔离开发根目录：`C:\Users\zhou\Documents\Codex\2026-10-06\task\PhotonGuard-intake-review`。

独立预览：<http://127.0.0.1:8776/>。重启用本目录 `START_INTAKE_REVIEW.ps1`，只用现有 Python、独立 `intake-preview-data` 和 `--offline-review`，不安装软件、不启动求解器。8776 的 PID 写于 `validation/preview.pid`，不要按端口盲目停止其他进程。

原 8765 / 8766 服务未被重启或写入。原演示仍为版本 13、COMPLETED，保留真实 Meep FAIL `20261006T085539Z-86e56a15`、PASS `20261006T085619Z-3df64391`。没有复制、清零或创建付费账本，没有沿用旧 20 元授权。此次实际模型 / 求解调用均为 0，新增模型费用为 0。

## 实际调用路径与完成范围

```text
intake.js action('intake-save', 原文)
  → POST /api/cases/{id}/action（同源 + CSRF + expected_revision）
  → WorkflowStore.action → workflow_intake.prepare（脱敏、材料 hash）

intake.js action('intake-review', mode, arm)
  → WorkflowStore.action
  → 先持久化 MODEL_RUNNING / 新版本，防止崩溃后旧请求重派
  → DeepSeekSemanticAdapter.run → _session（新授权/材料/费用/日期门禁）
  → research/evaluation-coordinator/live_transport.complete（原有有界 transport）
  → assistant tool_calls → PublicTools.invoke（仅公共材料/校验）
  → role=tool 反馈 → 同一 complete 第二回合
  → 原有 candidate_contents / raw_member（保留原始数值词法）
  → workflow_intake.model_result → semantic_intake.receipt
  → 来源/缺项/冲突/范围待审 → 明确人工语义确认
```

四种模式分别为：

| 模式 | 当前行为 |
|---|---|
| `mock` | 逐行受限规则；不是 AI |
| `adapter_mock` | 实际适配器和既有 transport 协议，注入 `RuleMockTransport` 的合成响应；两回合加一次公共校验；不是 AI |
| `offline` | 导入已有 JSON；绑定当前材料 hash，不验证其生成来源，不请求模型 |
| `live` | 适配代码已实现，但当前未安装新授权绑定，服务端返回 403；不是只靠前端禁用 |

`DeepSeekSemanticAdapter(binding, ledger, key_supplier)` 是待授权的服务端接口，通过 `make_server(..., model_adapter=...)` 注入。它要求新的 `semantic-small-gui-...` 引用、精确 case / 材料 hash / A0 或 A1、官方目的地、最多两回合、最多八请求且人民币不超过三元的独立持久账本、24 小时内核验价格。所有检查先于内存凭据 supplier。默认实例没有 binding / ledger / supplier；不读取环境变量或密钥文件，浏览器不能设置这些对象，也没有 live CLI 开关。

原来的 `TOOLS` 和 `candidate_contents` 无改写地提取到 `semantic_protocol.py`，历史 CLI 从该模块导入；`live_transport.py`、`batch_ledger.py`、`cny_budget.py` 均未改变。新 GUI 不调用绑定旧计划/私有评分器/已耗尽账本的历史 `execute()` / `execute_remaining()`。这是复用协议与安全 transport 的新 UI 会话，不是历史实验续跑；新 UI A0/A1 prompt 也不能冒充原冻结实验 prompt。单次允许最多八次公共工具请求，不接受任意路径、命令、秘密、评分器或未来材料。

**尚未验证：** 有真实新授权与真实凭据时的成功分支、实际模型响应质量、Linux 持久账本并发与 bwrap。当前公共工具 dispatcher 只运行固定纯解析/校验函数，未声称经过旧 bwrap 进程隔离验收。真实模式启用前必须在有权访问的隔离 Linux checkout 中完成这项复核；当前没有授权启用。

## 原生桥接仍阻断，但给出具体下一步

人工确认后会出现「导出人工处理单（含未决映射）」和「前往原生资料表单（人工填写）」。处理单由 `/api/cases/{id}/mapping-handoff` 生成，带当前材料/结果 hash、已审语义字段及未决项，所有 native 决策初值保持 null。

1. **仍要求等波长采样：** 下载处理单，保存任务并等待新增适配器；当前原生等频率适配器不能执行这份要求。
2. **需求提出者明确允许改为等频率：** 先记录新的独立出处、Meep 尺度、线性/Ex 假设和精确数值到浮点的审核，再用导航按钮进入下方原生背景/任务表单人工填写。没有自动抄入 native task。
3. 原生流程仍需独立任务确认、AST 只读导入、任务锁及明确运行许可。语义确认没有批准任务、创建锁或启动求解。

`layer_count` 保持 sidecar；`units_um` 不默认设为 1；等波长不偷换成等频率；数值精度、单位和范围均保持门禁。只支持本轮 1D 正入射、线性无损非色散非磁各向同性单膜、空气外侧。模拟对象仍是 AST 提取后的规范化配方，不是任意原脚本。

## 安全与测试证据

V2 兼容集合：**417 passed、123 subtests passed、18 deselected**，见 `validation/regression-windows-offline-v2.log`。新增模型适配测试 14 项，见 `validation/model-adapter-tests.log`。新增录入集成 23 项仍通过。18 个未运行项沿用首轮 Windows 限制：12 项符号链接、1 项实际 Meep、4 项超长 pytest ID、1 项 CRLF 下载断言；不能算作通过。

| 风险 | 实现和证据 |
|---|---|
| 同源 / CSRF | 新 POST 复用 `WorkflowHandler.headers_ok`；Host / Origin / CSRF / 重复头 / 路径检查沿用既有测试；GET handoff 同样校验 Host / Origin，不开 CORS |
| 双击 / 并发 / 费用 | store 修订锁、适配器锁、发送前持久状态；mock 共享额度四线程只容许一组两回合完成；人民币/次数不足在 transport 前停止；live 使用原持久账本预约 |
| 过期 / 重启 | 绑定材料 hash、期望版本与结果 hash；MODEL_RUNNING 中断记录不自动重派；失败清除当前草稿与确认；撤回恢复后必须重算 |
| 注入 / 来源 | 固定工具名称和静态公共文件白名单；拒绝任意路径和 run/approve 操作；全字段/逐字原文校验，工具不能授权或执行脚本 |
| 秘密 / 草稿泄漏 | 先脱敏材料，再保存；复用 transport 凭据检测，原始 HTTP envelope/异常/headers 不落盘；失败输出无原始返回正文；工具只能看到绑定的 view，不能按 case_id 读取另一份草稿 |
| 浏览器 | 用户本地 Microsoft Edge 独立 headless profile；11 组实际浏览器检查，页面错误 0、外部请求 0；`validation/browser-results.json`、三张 PNG、`manual-mapping-example.json` |

已确认新接口的二回合工具续接不是离线导入伪装：浏览器选择 `adapter_mock` 后审计包含两个 `injected_mock` transport 回合、一次工具调用与零实际模型派发。没有将合成结果称为真人/AI能力评测。

## WSL 拒绝的确切位置与最小下一步

- `functions.exec → exec_command` 执行 `wsl --list --quiet`：返回 `Wsl/EnumerateDistros/Service/E_ACCESSDENIED`。
- 同工具中 PowerShell `Get-Item -LiteralPath '\\wsl.localhost\Ubuntu\home\zhou\projects\PhotonGuard-workflow-review-20261006' -ErrorAction Stop`：`System.UnauthorizedAccessException`，`ItemExistsUnauthorizedAccessError,Microsoft.PowerShell.Commands.GetItemCommand`，错误为 `Access to the path ... is denied.` 原始结构化记录：`validation/wsl-access-v2.json`。
- 先前对 `\\wsl.localhost\Ubuntu\home\zhou\projects\PhotonGuard` 的 `Get-ChildItem` 同样拒绝。

没有请求提升权限或改走另一身份绕过。最小下一步是在用户已有权限的 WSL 终端/本地 Codex 中只读检查实际目录、若有 Git 则运行 `git status --short` / `git worktree list`，并运行本包 `check_merge_baseline.py` 对照目标旧文件 hash；把结果交回即可。在拿到这些结果前，仅使用当前隔离副本，不合并到原运行安装。

## 当前模型名称与下一批建议（没有授权）

既有 `examples/deepseek.config.template.json` 和 `SemanticBatchLedger` 均使用 `deepseek-flash`，没有默认替换型号。2026-10-06 官方 [英文模型表](https://api-docs.deepseek.com/quick_start/pricing/) 与 [人民币价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 均核验到：`deepseek-flash` 当前映射到 DeepSeek-V4.1-Flash，支持工具调用。这里只查看公开网页，没有调用需要密钥的 `/models`。

建议仍为 2 份新材料 × A0/A1 × 每臂最多 2 次 HTTP 请求＝最多 8 请求，人民币硬上限 3 元。按当前高峰未命中输入 2 元/百万 tokens、输出 8 元/百万 tokens，加上现有每请求 131072 输入和 4096 输出预约，八次上界为 2.359296 元（仅预约计算，不是账单保证）。实际运行前仍须重新核价并获得新授权；失败和超时保留预约、不自动退款重试；旧 12/12 与旧 20 元授权都不可复用。

## 改动文件与合并

精确旧/新 SHA256 清单在 `delivery/changes.json`；统一补丁在 `delivery/intake-integration.patch`；增量包在 `delivery/intake-review-delta.zip`。

- 前后端：`photonguard/workflow.py`、`workflow_intake.py`、`workflow_model.py`、`workflow_assets/app.js`、`intake.js`、`index.html`、`style.css`。
- 兼容与语义：`photonguard/runner.py`（延迟 Linux resource 导入）、`research/intent-pilot/semantic_intake.py`（显式真实材料参数，原研究默认不变）。
- 共享协议：`research/evaluation-coordinator/semantic_protocol.py`、`run_live_small_batch.py`、`continue_live_small_batch.py`（后两者仅改共享声明导入）。
- 测试与交付：`tests/test_workflow_intake.py`、`test_workflow_model.py`、`START_INTAKE_REVIEW.ps1`、两份说明、浏览器脚本及只读合并检查器。

原 Windows 基线的 149 项源码哈希不变。补丁只对该交付基线核验，不能证明当前 WSL checkout 没有用户改动。合并必须在独立工作树/副本中进行，先检查旧文件 hash 和用户改动，不能复制旧账本、覆盖演示数据或替换 8766。后续仍先用 `--offline-review` 和新的独立数据目录验证。

## Library 交付状态

已按当前 Library 技能的批量流程尝试保存增量包与本说明；当前 Windows 执行环境在上传 helper 的服务发现阶段返回 `hosted apps tools/list request failed: network`，退出码 1，没有进入 prepare / finalize，也没有返回 Library ID。因此本交付暂时只有本地文件，不能当作已保存的原生聊天附件。

Library 写入工具在工具列表中存在；阻塞是当前规定批量保存流程的连接失败，不是文件不存在，也不是用户拒绝授权。没有修改 helper、扩展网络权限或伪造文件 ID。辅助记录位于工作区 `library-transfer-v2/upload-error.txt`。需要在能够正常连接 Library 批量上传流程的会话里保存这两份最终文件。
