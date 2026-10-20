# 本地 Codex 接手：PhotonGuard 操作闭环与首次 DeepSeek 联调

将本文整段交给电脑上的 Codex。只在用户指定的本地工作目录继续；不要自动迁移环境、推送、公开发布、报名或产生其他费用。

## 交付与当前状态

- 精确 base commit：`1c070c05be7bdac7656a290a68a04f17eccd2fc1`，私有仓库 `https://github.com/zhouqiuyu114514-beep/aic`。
- 本 checkpoint 是在此 base 上的未推送工作区修改。补丁和完整源码快照由本次交付提供；使用前核对其 SHA-256 清单。不要覆盖已有本地修改。
- 新增 `prepare-task`：从重新校验的 AST 导入候选生成未知量留空的任务草稿、脚本观察清单和中文说明。
- CLI `confirm`：检查完整性/支持范围，`--candidate` 可同时核对导入来源/谱段；创建锁采用独占方式，拒绝覆盖已有锁。核心物理阈值、tmm、求解器、受限动作保持原样。
- 已有 Linux 云环境基础复现：311 tests、13 subtests 通过；一个案例 8 次真实 FDTD 为 PASS。本 checkpoint 的新增测试和闭环结果见配套 checkpoint 报告。
- 真实 DeepSeek 调用至今为 0，已知累计 API 费用 0 元。用户批准本轮首次小型合成诊断的累计人民币上限为 20 元；这不是追加预算。没有证明 AI 增量。
- 云端曾在 CONNECT 阶段返回 403；停止云端配置排查，不向用户索取新的云端设置。该结果不说明本地连通性或密钥有效性。

## 本地前置检查与安装

1. 先报告实际当前目录、Git HEAD/工作树状态、操作系统、CPU 架构、可用空间及是否已有项目运行时；不假定任何云端路径存在于用户电脑。
2. 当前锁文件只支持 **Linux x86_64 + glibc**。原生 Windows、macOS、ARM64 不受该锁支持。
   Windows 用户需要在自己已有或明确选定的 WSL2 Linux x86_64 中运行此流程；推荐源码放在 Linux 文件系统。
   **本次没有在用户 Windows/WSL 上执行或验证。** 不得把 Linux 云端结果描述成 Windows/WSL 已通过。
   如果没有可用 Linux 环境，先报告实际缺项，请用户选择/准备环境；不要自动安装 WSL、迁移环境或改系统安全设置。
3. 在选定 Linux 中可用以下非秘密检查：`pwd`、`git rev-parse HEAD`、`git status --short`、`uname -srm`、`getconf GNU_LIBC_VERSION`、`df -h .`、`command -v bash curl tar`。运行时及包缓存约 1 GB，应保留额外空间。
4. 若使用干净的 base checkout，先 `git apply --check <checkpoint.patch>`，再应用补丁；若使用完整 checkpoint 源码快照，**不要重复应用补丁**。
   历史 `SOURCE_MANIFEST.sha256` 属于 base；修改后与它的差异是预期的，勿重写旧清单以制造通过。交付另附 checkpoint 清单。
5. 阅读 `README.md`、`runtime/README.md`、`docs/SAFETY_AND_SCOPE.md` 和适用 AGENTS/skills，运行 `bash runtime/bootstrap.sh`。
   安装使用原样保留的 `runtime/conda-linux-64.lock` 及官方 conda-forge 包；不要用 PyPI 的同名 meep 替代 PyMeep。
   出现网络拒绝、架构或依赖冲突时保留实际错误，不换凭据、不绕过限制、不把 mock 当真实安装。
6. 运行 `PYTHONDONTWRITEBYTECODE=1 .runtime/run-python -m pytest -q -p no:cacheprovider tests runtime/test_runtime.py`，再按 `docs/DEMO_ZH.md` 完成开发示例闭环。
   保留新运行目录、日志、原始输入及 task lock，验证新旧证据清单；如结果不同则先诊断，不改容差凑 PASS。

## 首次本地 DeepSeek 调用：仍须通过的门槛

1. 先完成上述本地真实 Meep 检查。不要把账户配置和 API 调用放进自动演示脚本。
2. 密钥由用户在本机受支持的安全注入方式中录入，专用名称 `DEEPSEEK_API_KEY`。不得让用户贴进聊天、命令参数、仓库或报告；不得打印、保存、转移真实值。只检查是否可用，不搜索其他密钥或沿用聊天旧值。
3. 本地读 `docs/DEEPSEEK_BACKEND.md` 和 `photonguard/api_cli.py`/`backend.py`。目前默认 API transport 不继承环境代理；若本机必须经代理，该 transport 不能直接照用。先报告兼容性阻碍，不能为了连通而绕过代理、改安全设置或换凭据。
4. 仅在实际本地允许的网络机制上做无计费 `/models` 认证检查。缺失授权、403 或无法确认认证成功就暂停计费步骤；日志不含 Authorization 或凭据回显。
5. 认证成功后查看官方模型/价格文档，确定明确模型、当时最高适用输入/输出单价、缓存口径、货币与人民币换算。模板价格不得当作现价；价格或汇率不明时停止。
6. 沿用 **累计 20 元人民币** 的单一持久预算账本，先按输入保守 token 预留 + 最大输出 token 预留最坏成本。使用 Decimal，保留价格来源/日期/兑换口径，失败和超时也保留预留，不重置账本、换路径绕限、自动重试或追加预算。
   现有 `PersistentBudgetLedger` 以 USD 记账：必须从人民币剩余上限保守换算，或先实现并离线验证等价人民币硬上限。另存累计人民币口径和原账本绑定，不能仅声称 `$20`。
7. 首次只做 **1 个** 小型 PhotonGuard 合成故障诊断；数据只限相关代码、任务与脱敏仿真证据。
   通过 `export_request`/`diagnose-api` 使用受限结构化动作和精确 task/candidate/policy 哈希，不让模型改阈值、参考模型、任务或源码。
8. 保存真实调用 ID、实际返回模型、完整 usage、耗时、安全请求/响应、预留额和实际 usage 的费用估算；估算不等于账单。
   读取建议并按既有授权范围明确批准一次合法修复，真实 Meep 全量复验，报告 PASS/FAIL 或明确阻碍。
   API 超时且无 usable envelope 时应报告处理/计费未知，不能武断记成 0；不得伪造模型成功或第二次重试。
9. 保存源码修改、差异、原始证据和最终报告；不推送、不公开。若需要新的费用、发布或环境迁移，先交付具体结果再另行确认。

## 后续研究边界

`docs/AI_EVALUATION_PLAN_ZH.md` 是待执行计划。现有 API 只诊断已锁定任务/已有证据，尚无自然语言任务录入的模型接口。
规则演示修好了已知介电常数故障，不应包装成模型贡献。若模型集成成功，先报告单次可用性，再按公平协议研究人工录入/解释帮助。
