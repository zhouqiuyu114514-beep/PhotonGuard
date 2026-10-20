# 独立规格录入的离线 proof

2026-10-06 新增 `requirements_intake.py`，面向未经facts手工标注的独立需求原文，
提供离线请求导出和提案导入校验。它不包含模型传输，不能批准任务或写锁。
新接口6项测试通过，连同原24项共30项；开发材料和公平对照边界见 `INTAKE_EVALUATION_ZH.txt`。
下文原bundle/mock接口的“没有自然语言提取”描述仍适用；新接口也未实测模型提取能力。

本目录是两份**手写合成开发样例**及小型可运行接口。仅依赖 Python 标准库，在 Linux x86_64、Python 3.12.14 实测。未做真人试用、模型调用或求解；不能据此声称节省人工时间或证明 AI 增量。源码按研究包中的 GPL-2.0-or-later 许可提供。

## 运行

在此目录运行，结果打印到标准输出：

```sh
python3 -B intent_pilot.py fixtures/complete.bundle.json fixtures/complete.mock.json
python3 -B intent_pilot.py fixtures/needs-clarification.bundle.json fixtures/needs-clarification.mock.json
python3 -B -m unittest -v test_intent_pilot
```

需要生成自己的操作记录时使用**尚不存在**的输出目录：

```sh
python3 -B run_local_proof.py my-local-run
```

`results/` 保存本次云环境的真实执行结果。运行器记录实际命令、环境、返回码、输入/输出哈希和机器耗时；`human_edit_count`、`human_review_seconds` 为 `null`，没有把自动运行时间写成人工操作时间。测试中的子进程仅执行此 Python 接口和单元测试。

## 固定边界与数据格式

只处理一个膜层的14个语义路径：8项物理假设、物理单位尺度、膜层折射率/厚度、两个波长端点和频点数。没有自然语言提取、任意路径、额外膜层或材料转换规则。

`bundle` 的键严格为 `schema_version/kind/documents/facts`。`kind` 必须是 `synthetic_development`。文档包含 `id/kind/lines`，类型为 `independent_spec` 或 `ast_observation`；事实包含 `id/path/value/unit/source`。来源严格为 `document_id/line/quote`，行号从1开始，quote必须与整行一致。当前事实的路径/数值/单位由样例作者手工标注，**程序没有证明标注与自然语言含义相符，也没有验证作者身份**。这两项应由人工核对。

`mock` 的键严格为 `schema_version/kind/bundle_sha256/fields`。`kind` 必须是 `handwritten_mock`；每个字段严格包含 `path/state/evidence_ids`，必须恰好覆盖全部14个路径，不接受数值或批准标志。字段状态为 `proposed/unknown/conflict/unsupported`。同路径所有独立来源事实都必须被引用，不能隐藏冲突、使用其他路径证据或用AST观察填补意图。bundle哈希绑定整包，包括来源文本与类型。

`nm/um/mm` 通过十进制乘法换为微米；无量纲为 `1`、布尔为 `bool`、计数为 `count`、角度为 `deg`。单位或值未知时保留空值；不根据数量级或源码猜测单位。规范化后的物理数值用十进制字符串输出，避免再舍入。重复ID/路径/引用、额外键、无效来源、错误量纲、非有限数、假批准和过期哈希会被拒绝。等价单位不会形成假冲突，波长顺序错误会清空两个端点。

范围筛查采用当前单层演示的窄范围：一维、法向、无损、无色散、各向同性、相对磁导率与两侧折射率为1、每Meep单位为1微米；膜层n在[1,5]、厚度在[0.02,5]微米、递增波长在[0.5,5]微米、频点数在[3,201]。这只是研究副本中的输入筛查，**不是物理验收器**；未导入或改写稳定项目的阈值、参考模型或CLI。以后接入真实项目前仍需复核接口和稳定验收器的契合情况。

## 两个开发样例

| 样例 | 手写输入 | 实际预期结果 |
| --- | --- | --- |
| `complete` | 14项独立事实，包含1000 nm/Meep单位、0.0002 mm厚度和500 nm波长下限；另有故意不同的合成脚本折射率观察 | 14项待审建议，单位转换为1/0.2/0.5微米；状态 `REVIEW_REQUIRED`，未批准 |
| `needs-clarification` | 未提供独立折射率、厚度缺单位、波长上限有0.9 um与1100 nm冲突 | 11项待审建议、3项留空、3条追问；状态 `CLARIFICATION_REQUIRED`，脚本值不回填 |

两个mock的状态由开发样例作者明确写定；`make_development_fixtures.py`只是可复查的样例构造记录。没有调用模型，也没有把验证器输出重新充作独立答案。正式盲测需另由独立作者准备新任务。

## 审核与安全边界

所有结果恒为待人工审核，`task_approved=false`、`task_lock_created=false`。接口只读两个JSON输入并打印结果；没有批准/写锁/执行脚本/模型/求解器功能，结果也不是稳定项目的 `task.json`。建议值、来源行、原单位和未知/冲突路径可逐项核对。真人操作日志应另记阅读、修改、确认等实际行为，不用这里的机器计数代替。

## 本地任务草稿导出接口

本地续开发新增独立入口 `export_task_draft.py`，重新读取并校验原 bundle 和 proposal，
将待审字段映射到稳定项目的 `task.draft.json`，并调用稳定 `task_problem` 检查格式与范围。
原 `intent_pilot.py` 的只读行为保持不变。导出入口会写入指定的新目录，拒绝已有目录：

```sh
python3 -B export_task_draft.py fixtures/complete.bundle.json fixtures/complete.mock.json --out ../../local-validation/draft-complete-NEW
python3 -B export_task_draft.py fixtures/needs-clarification.bundle.json fixtures/needs-clarification.mock.json --out ../../local-validation/draft-clarification-NEW
python3 -B -m unittest -v test_intent_pilot test_export_task_draft
```

每次导出保留原 bundle/proposal 的 JSON 内容、字段审阅回执和中文审核说明，不写任务锁。
精确十进制值仍在回执中，草稿按稳定 schema 转换为 JSON 数值，并记录转换对应关系。
未知、冲突和不支持的字段留 null；完整草稿通过格式检查也仍未批准，引用匹配仍不证明语义。
当前导出仅接收原 proof 的手写合成开发包，没有扩展成真实用户规格或自然语言提取接口。
审核后必须另存为 `task.json`、准确记录来源，再明确调用稳定 CLI `confirm --approve`；
导入任务应同时传入 `--candidate` 校验来源和谱段。后续真实 run 才进行物理验收。

新增6项测试覆盖稳定 schema 契合、缺项无法确认、过期/伪造来源与假批准拒绝、
输入与既有目录不覆写，以及转换过程没有网络或子进程。

18项测试覆盖这些边界，包括禁止网络、文件写入及子进程的纯函数测试，以及在来源文字放入可执行Python后运行CLI，核验文字未执行、输入未变。它们不是操作系统隔离保证，也不能验证来源文字语义。全体稳定项目的原325项测试没有因本研究重复运行；已交付结果保留。
