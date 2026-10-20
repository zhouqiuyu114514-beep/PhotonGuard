# 合成 A0/A1 小批次：可审核的一次性交接

本补丁仅针对 PhotonGuard 提交 `2835f6d864fc302503dd8c439a7348b153bd7272`，应在原有权限的 Linux 会话新建隔离 worktree 后应用。不要替换或重启正在演示的 8777，不复制或重置已耗尽的旧 12/12 账本，不接通 native bridge 或求解器。本次交付只做了离线/mock 验证；没有读取密钥或发送真实 DeepSeek 请求。

## 已实现的费用边界

[DeepSeek 官方模型与价格页](https://api-docs.deepseek.com/quick_start/pricing/)把 `deepseek-flash` 的上下文长度标为 **1M token**，说明按输入与输出 token 计费。软件用更保守的 **1,048,576（1 Mi）输入 token** 覆盖整次提供商计数的 prompt，包括系统和用户消息、工具定义、历史模型调用与工具反馈；不以 120000 字节 HTTP 体积推断 token。每次请求固定 `model=deepseek-flash`、`max_tokens=4096`、`thinking.type=disabled`、非流式；[官方 Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)规定 `max_tokens` 为生成 token 上限，[思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)支持显式关闭思考。

使用当前待现场复核的峰时价格：输入缓存未命中 ¥2／百万、输出 ¥8／百万，单次最坏费用为 `(1048576×2 + 4096×8)/1000000 = ¥2.12992`。同一账本的人民币保留值会再向上取整为 **¥2.129920000001**。对应美元峰价保留 $0.319488。单次最坏均低于批准的人民币 ¥3 与现有美元 $0.3538944 上限；不会预先假定八次最坏请求都能放行。若实际用量很少，结算释放差额后才可发送下一次。每次派发都在同一 POSIX 文件锁下检查“已结算费用＋未结预留＋下一次最坏费用”及 8 次总数；超过任一批准上限就停止并报告部分结果。

账本使用本批次专有的 schema 3 文件。一次派发先持久化单笔最坏预留和随机 ID，再发 HTTP；响应只有在状态、模型 ID、助手结构及 `prompt_tokens`／`completion_tokens`／`total_tokens` 完整一致、未超上下文／输出限制、没有思考 token、缓存分项不矛盾时，才凭该 ID 在同一文件锁下结算并释放差额。重复或过期 ID 不能再次释放。HTTP 失败、响应无效、异常 `usage`、进程中断都保留最坏预留并停止；遗留 pending 阻断再次派发。结算额按全部输入均未命中、峰时价格计算，缓存命中只会降低实际费用。供应商不遵守其公布的上下文／输出／价格承诺或事后异常计费，不属于软件可强制的保证；无需假定存在账户侧 ¥3 自动截断开关。

## 在原有权限 Linux 会话复核

1. 先确认原工作树与演示服务状态，在提交 `2835f6d864fc302503dd8c439a7348b153bd7272` 新建独立 worktree；核对 `live-batch-entry.patch` 的交接 SHA256，运行 `git apply --check <补丁路径>` 后才应用。若目标批次目录已有内容，停止，不重跑。
2. 运行 `python3 -B tools/run_gui_live_comparison.py --preflight`、`python3 -B -m unittest tests.test_gui_batch_ledger tests.test_gui_live_batch_entry tests.test_workflow_model -q`。Linux 专属的跨进程预留、并发结算和完整 one-shot mock 测试必须通过；任何失败都停止。若原环境已有 pytest，再运行 `python3 -B -m pytest -q tests/test_cny_budget.py tests/test_live_gate_posix.py` 检查旧护栏回归；不要为本批次安装软件。`--preflight` 不读密钥、不联网。
3. 在任何真实调用前，重新从官方页面核对模型 ID、**1M 上下文上限**、`max_tokens` 与关闭思考的语义、峰时美元价格（输入缓存未命中 $0.30、输出 $1.20／百万）和人民币价格（输入缓存未命中 ¥2、输出 ¥8／百万）。用户提供的中文表与预留数值一致，但本会话浏览官方[中文价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)超时，故人民币价格仍须现场独立核实。模型、上下文、输出或价格口径改变，或页面不可核实，均不启动。
4. 若上述均通过，把下列命令交给用户本人在其本地交互终端执行。UTC 时间戳填现场官方核对的实际时间；程序拒绝未来或超过 24 小时的时间。不由 Codex 工具、聊天、命令参数、环境变量或文件读取、传递、配置或保存凭据。

```bash
python3 -B tools/run_gui_live_comparison.py --run --official-rates-verified-at 'YYYY-MM-DDTHH:MM:SS+00:00'
```

入口只用进程内 `getpass` 隐藏输入。固定两个项目合成案例（完整单膜、缺项与冲突 fixture）各跑 A0/A1 四槽；每槽最多两轮，HTTP 续接与失败都占一次，整个批次最多 8 次，无自动重试。输出目录为 `local-validation/gui-live-approved-20261006/`，必须事先不存在；目录一旦建立，入口拒绝再运行。中断时只能查看已落盘计划、槽位收据与新账本，报告部分结果，不凭缺失的 summary 重发。所有模型结果只是人工审核草稿，不自动确认、锁定任务或求解。
