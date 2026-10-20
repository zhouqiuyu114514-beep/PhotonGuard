# PhotonGuard 离线需求录入首轮交付记录（已被 V2 复核替代）

**当前交付以 [INTAKE_REVIEW_V2_ZH.md](INTAKE_REVIEW_V2_ZH.md) 为准。** 下文保留首轮范围和测试记录；首轮仅 mock / 离线导入，没有真实模型适配器。V2 已补上默认关闭的适配接口和 mock transport 续接验证，不能再用下文描述当前完成范围。

本次接入沿用 2026-10-06 GUI 的页面、工作记录、同源接口与版本锁。新增自然语言材料 → 待审语义字段 → 原文出处 / 缺项 / 冲突 / 范围检查 → 人工语义确认。**真实模型入口关闭，native bridge 仍阻塞。**

## 位置与隔离

- 隔离源码：`C:\Users\zhou\Documents\Codex\2026-10-06\task\PhotonGuard-intake-review`
- 基线：`..\..\j-ji\outputs\PhotonGuard-graphical-workflow-20261006\PhotonGuard`，149 项历史源码哈希核验通过。
- 正在使用的安装：`/home/zhou/projects/PhotonGuard-workflow-review-20261006`（依据安装回执）。本次沙箱对 WSL 命令和 UNC 路径返回拒绝访问，未提权，未检查到其 Git 未提交状态。因此不能声称实际 checkout 没有用户更改；没有合并或覆盖它。
- 发现原服务端口 8765 / 8766、两个 Codex 进程。未停止它们，未发送原服务变更请求，也未假定不存在其他并行工作。
- 原 8766 服务的 app.js / style.css 哈希与交付基线一致。原任务 `5182040a9d264134abc3162f129ea1a2` 保持版本 13、COMPLETED；真实证据 FAIL `20261006T085539Z-86e56a15`、PASS `20261006T085619Z-3df64391` 均由原服务报告 verified。详细只读快照见 `validation/original-services-readonly.json`。
- 原始源码、演示数据、真实响应和账本未改动；没有读取或配置真实 API 密钥。没有 Git 提交、推送、发布或安装软件。

## 打开本次预览

当前独立地址：<http://127.0.0.1:8776/>。选择「新建需求录入」。原来的演示继续使用 8766。

如果预览已停止，在此目录 PowerShell 中执行：

```powershell
.\START_INTAKE_REVIEW.ps1
```

启动器复用本机已有 Python，固定 `--offline-review`，数据写到本目录 `intake-preview-data`。窗口前台启动时 Ctrl+C 只停止此服务。端口占用时不要停止不明进程；可用 `-Port 8777` 另起隔离端口。Windows 强制禁止求解工作进程；Linux 的 `--offline-review` 同样禁止求解。原 Linux 数值限制仍保留；仅将 `resource` 导入移到真正使用它的 Linux 子进程限制函数。

操作：粘贴独立原文 → 保存脱敏材料 → 选择规则 mock 或已有离线响应 → 查看全部 14 项与原文行号 → 补充缺项 / 冲突 → 勾选审阅声明并确认。更改原文需重新保存、校验，旧确认失效。撤回会清除当前草稿和确认，恢复只恢复材料，必须重新生成。

## 模式与边界

1. `MOCK_RULES_NOT_AI`：受限、逐行全匹配的规则演示；不是 AI，不声称理解任意自然语言。支持示例中的显式句式，识别不了的字段保留 null。不同值保留双方完整来源，不猜版本优先级；单位等价用原有精确十进制算法判断。
2. `OFFLINE_RESPONSE_UNVERIFIED_ORIGIN`：粘贴已有 JSON，只在本地校验。UI 导出的当前 view 是绑定依据；历史响应如 case_id / hash 不匹配会拒绝，禁止偷偷重绑。不能由此声称响应确实来自某个模型。浏览器验证使用合成响应，没有把 mock 冒充真实历史响应。
3. 真实模型：前端禁用，后端拒绝所有非 mock / offline 模式。此接口不提供 endpoint、密钥、模型选择、付费账本创建或 transport 调用。失败不自动重试。既有 A0/A1 续接和账本代码保留原样，没有接入 live dispatch。

复用 `research/intent-pilot/semantic_intake.py` 的结构校验、哈希、逐字引用、精确单位换算及只读投影；复用 `photonguard.backend._redact` 的脱敏。为真实用户材料显式增加 `allow_user_material=True` 参数，**既有研究接口默认仍只接受 synthetic packet**。公共合同文件及 14 字段完全不变；用户材料 packet 标记为 false，不把它说成合成材料。

语义确认只记录 `semantic_review_only` 回执；不修改 `state.task`、不生成 `task.json` / `task.lock.json`、不批准任务、不执行 AST 或启动求解。输入中的命令和脚本作为纯文本。引用存在不证明语义蕴含、版本权威或所有冲突已被发现。脱敏覆盖已知凭据形式和转义，不声称识别任意编码秘密；不要粘贴密钥。

原生映射仍需人工处理：

- `layer_count` 是 sidecar；不可当作原生 task 字段。
- `units_um` 是实现尺度，不能从材料长度单位推成默认 1。
- 等波长采样与等频率采样不等价；必须明确重述需求或另行实现适配器。
- 精确小数不能未经审阅转成 native 浮点；保留原单位、数值和出处，另核精度 / 范围。
- 线性假设、Ex 场分量不由这 14 项表达，需要独立确认。
- 本轮范围为 1D 正入射、线性无损非色散非磁各向同性单膜、空气外侧。GUI 原有「最多 8 层」文字已收紧为单膜，同时在 readiness / 确认 / 运行入口加以阻断；核心通用策略哈希与验收阈值未改。
- AST 仿真仍只执行提取后的规范化配方，未改成执行任意原脚本。

## 测试与证据

- 新增集成测试 23 项（另含多个范围 subtest）：缺项、冲突双方出处、越界、单位等价、长小数精度、注入、合成秘密与 Unicode 脱敏、响应哈希和原文伪造、费用门禁、并发与重复点击、撤回恢复、失效结果、服务重启与工作区独占锁、模型失败提示。
- Windows 可运行的相关回归：**403 passed，123 subtests passed，18 deselected**。包括原 GUI 安全、AST 导入、任务审核、报告、研究语义录入。详见 `validation/regression-windows-offline.log`。
- 第一轮未经平台筛选的回归：403 passed / 16 failed / 2 errors。失败包括 Windows 不允许创建测试符号链接、Linux `preexec_fn`、GBK 默认解码、CRLF 断言、超长 pytest 测试 ID 超过 Windows 环境变量长度。设置 UTF-8 后重跑兼容集合；没有修改原断言来伪造通过。第一轮 Linux 实际 Meep 测试在子进程派发前被 Windows 拒绝，**没有启动求解器**。
- 18 项排除：12 项符号链接测试、1 项实际 Meep 测试、4 项超长参数 ID 测试、1 项 CRLF 下载断言。符号链接防护、Linux 进程限制和真实 Meep 全回归需在隔离的 WSL checkout 后续补跑；这次未验证 Linux 费用账本 / bwrap 续接执行，不放宽它们的锁和隔离措施。
- **用户本地 Microsoft Edge**（`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`），使用独立 headless profile，不触碰现有浏览器窗口和资料。9 组实际 DOM / HTTP 场景通过：完整审阅、来源、冲突、刷新、错误、处理中撤回、双标签页失效、秘密脱敏、手机布局。页面错误 0，外部网络请求 0。详见 `validation/browser-results.json`、三张 PNG。
- 本次模型 / 求解实际调用均为 0，新增费用 0。没有重置或沿用旧账本。不是一次新的真实 Meep 验收，也不是模型能力评测。

## 安全审阅与合并

交付目录 `delivery` 提供逐文件旧 / 新 SHA256、统一 diff 和增量 zip。`validation/check_merge_baseline.py TARGET` 只读检查目标文件是否还是旧基线；任何用户修改或未知文件冲突都必须先人工整合，不能强行覆盖。它不是全仓库清洁状态证明。

在后续能够读取 WSL checkout 时：先检查 Git status / worktree、后台工作、源码与旧文件哈希；从当前用户版本新建隔离工作树或副本，把本补丁逐项合入，在独立数据目录和端口重跑 Linux 安全 / 账本 mock 回归。不要复制旧账本、覆盖 workflow-data 或替换正在演示的安装。审阅合并后仍先使用：

```text
/home/zhou/projects/PhotonGuard/.runtime/run-python -B -m photonguard.workflow --data workflow-intake-isolated --port 8777 --offline-review
```

该命令不会启用真实模型，也不会解除 native bridge。需要真实求解时，沿用原有独立任务、AST 导入、任务锁和明确运行确认流程，另行验证。

## 下一批真实对照建议（仅方案，未授权 / 未执行）

沿用已有实现的 `deepseek-flash`，选 2 份新材料，每份 A0 / A1 两臂，每臂最多 2 次 HTTP 请求，共 **最多 8 请求、人民币硬上限 3 元**。A1 的工具续接也计入请求总数；失败、超时和无有效结果均耗用已预约额度，不退款重试。此规模只能检查连通与可用性，不足以证明统计收益。

旧 12/12 和旧 20 元授权均不可复用；如果另行批准，应建立独立、明确绑定此次批次的新授权与新会话账本，保留所有旧记录。执行前再次核验官方模型 ID、人民币价格、token 预约与总上限，并先通过 Linux 并发门禁测试。此次尝试打开官方价目页未成功，因此没有把历史费率当作现价，也没有据此启动调用。3 元是建议的停止上限，不是提供商价格或保证成本。
