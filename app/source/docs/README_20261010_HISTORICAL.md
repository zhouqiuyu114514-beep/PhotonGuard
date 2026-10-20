# 光子仿真智检助手 PhotonGuard

面向光电仿真入门者，将自然语言需求转为可执行任务，通过开源求解器和独立检查，生成带依据的曲线、修复建议与结果报告。

当前路线与能力边界更新于 **2026-10-10**。历史文档中的状态只适用于其记录日期。当前参赛路线见 `docs/COMPETITION_ROUTE_ZH.md`，本轮效果和限制见 `docs/COMPETITION_RELEASE_ZH.md`。

## 能做什么

- 无需先写脚本：选择教学卡，或粘贴完整、独立的薄膜资料；缺项保留未知、冲突等待核对。
- 运行真实 Meep，对照独立 tmm，检查任务参数、参考归一化、反射场扣除、能量及设置敏感性。
- AI 可整理输入、提出限定的配方修改和解释。任务锁与独立检查决定能否执行；修改后重新运行。
- 查看离散采样曲线，下载报告、CSV、原始证据与复跑配置。
- 查看冻结 LN 周期模型的目标排除证书及独立积分复核。F 是相位因子，不是转换效率。

支持主线：1D、正入射 Ex、线性、无损、非磁、各向同性、无色散，空气两侧单膜。更广的历史实验分支不等于当前新手入口承诺。通过列明检查不等于对任意模型的连续真实性认证。修复作用于规范配方，不执行上传 Python，不承诺修复任意原脚本。

## 启动

已验证求解环境：Linux x86_64 / Ubuntu WSL、Python 3.12、conda-forge Meep 1.34.0。Windows 可以通过 WSL 启动并使用浏览器访问。

```sh
# 在解压的源码根目录；首次下载约 1 GB，使用官方 conda-forge 锁。
bash runtime/bootstrap.sh
bash START_PORTABLE.sh --data workflow-data --port 8766
```

打开 `http://127.0.0.1:8766`，选择薄膜教学示例，核对摘要后开始。初次验证最多 8 次 FDTD，保存数据与报告。默认规则模式不会产生付费模型请求。

若已有合适的环境，可指定解释器，避免重复安装：

```sh
PHOTONGUARD_PYTHON=/absolute/path/to/python bash START_PORTABLE.sh --data workflow-data --port 8766
# 只读模式禁用求解执行：
PHOTONGUARD_PYTHON=/absolute/path/to/python bash START_PORTABLE.sh --data review-data --port 8766 --offline-review
```

源码方式运行需要保持整个目录结构，包含 `research/intent-pilot`、`examples` 和资源文件。当前不承诺单独 pip wheel 即具备完整界面。不要使用无关的 `pip install meep`。

## 小型复跑

```sh
# 真实 Meep 正例；新建输出目录，最多 8 次 FDTD。
.runtime/run-python -B tools/run_core_example.py --out core-example
# 查看已运行证据的完整性（这一步不重新求解）：
.runtime/run-python -B -m photonguard verify-evidence core-example/evidence/RUN_DIRECTORY
# 完整离线回归，不混计真实求解：
.runtime/run-python -B -m pytest -q -k 'not actual_meep'
```

示例会打印实际证据目录；不能把占位的 `RUN_DIRECTORY` 原样使用。交付包另含真实运行记录和 `verify_delivery.py`，可核查包中文件哈希；全量 LN 数学复核见原冻结资料包中的 `verify_packet.py`。新包的 LN 页面摘要本身不是全量数学重算。

## 真实 AI 与对照

真实请求归档记录模型、输入、输出、用量、费用和失败。`research/competition-release/study.py` 保留本轮冻结协议的构造、执行与评分入口；重新付费运行须使用自己的密钥、授权账本和新输出目录。源码包不会携带本机密钥或借用作者的账户额度。

普通 AI 与 PhotonGuard 使用相同模型、公共事实、动作范围与调用预算。规则组不调用模型。最终报告分别列出输入理解与实际执行结果；合成测试与模拟浏览器操作不冒充真人试用。不主张普遍 AI 优势。

## 开放与贡献

项目源码按仓库 GPL-2.0-or-later 许可提供，保留 `LICENSE`。Meep、MPB、tmm 等各自保留上游许可。程序调用开源求解器，不主张自研 Maxwell 求解器。DeepSeek 为第三方 API 服务，不随包提供模型权重。

生成式 AI 参与了代码、文档、测试、自动实验和材料制作。用户提出需求、反馈和路线选择；具体参赛成员、人工审阅与权属声明需由实际参与者确认，不能把代理完成的工作写成真人独立完成。详见 `docs/THIRD_PARTY.md` 与 `docs/AI_ASSISTANCE_ZH.md`。

本轮提供本地交付包，未自动公开、上传或代填参赛身份。真人试用数为 0。作品适用范围和失败记录与成功结果一并保留。
