# PhotonGuard · 光子仿真智检助手

一个已经运行真实 Meep FDTD 的本地研究原型：把确认的薄膜任务、待检参数、独立 tmm 参考、数值敏感性检查和原始证据分开。

**当前是 rules-only 开发版。没有调用运行时 LLM，没有完成 AI 增益实验，也不是任意 Meep 脚本的正确性认证工具。** 代码开发过程中使用 GPT，不等同于产品运行时的 AI 实验。

## 已支持

- 一维 z 方向、Ex 正入射；空气入射/出射
- 线性、无损、非色散、各向同性、非磁性薄膜，最多 8 层
- 受约束 JSON 参数适配器；新增窄范围只读 Meep AST 导入预览，不执行输入 Python、shell 或模型生成代码
- 独立确认与哈希锁定任务；参考只从任务生成，不跟随待检材料错误
- 四组真实 Meep 参考/目标配对：原设置、网格 ×1.5、运行时间 ×2、PML ×1.5
- 全请求频点的 tmm 对照、能量/物理边界、信号覆盖、敏感性检查
- 明确区分 PASS / FAIL / INCONCLUSIVE / UNSUPPORTED
- 每次最多一个受限修改、最多两轮；原证据不覆写，修改后全量重验
- HTML / JSON / CSV、原始通量/日志与 SHA-256 清单；只读本地浏览器界面

## 一分钟开始

已安装环境：Linux x86_64，Meep 1.34.0 / Python 3.12.14 / tmm 0.2.0。

新机器先运行：

```sh
bash runtime/bootstrap.sh
```

真实薄膜基线：

```sh
.runtime/run-python -m photonguard confirm examples/film_n2/task.json --lock examples/film_n2/task.lock.json --approve
.runtime/run-python -m photonguard run examples/film_n2/task.json examples/film_n2/candidate.json --lock examples/film_n2/task.lock.json
.runtime/run-python -m photonguard ui --root . --port 8765
```

在运行机器的浏览器打开 http://127.0.0.1:8765 。界面仅绑定本机回环地址；不部署公网，不接收代码上传。使用自己的机器时需先复制项目并安装环境。

任务确认表示操作者确认该 JSON 正确描述其意图；这不是数字签名或身份认证。示例中的确认是开发案例确认，不是假造真实用户试用。

## Meep 脚本只读导入（后续开发检查点）

```sh
.runtime/run-python -m photonguard import-script examples/script_import/film_n2.py --out imports/film_n2
```

这会保存原脚本字节、SHA-256、源码位置和提取预览。仅明确支持的顺序式参考/目标通量采集模板会生成 candidate.json；未知分支、调用、导入、动态数据或超范围布局直接停止。仍需独立填写并确认任务、物理单位与波段，再用现有 run 命令验证提取的规范化配方。

**EXTRACTED 不等于 PASS。原始 Python 从未执行；后续 PASS 只属于记录的规范化配方，修复后的 PASS 不表示原脚本通过。** 这是确定性解析器，不是 AI 意图理解或 AI 增益实验。完整支持语法、拒绝条件与来源规则见 `docs/IMPORT_LIMITATIONS.md`。既有 JSON-only v0.1 交付包及证据保持冻结。

## 故障 → 建议 → 确认 → 重验收

```sh
.runtime/run-python -m photonguard confirm examples/epsilon_mismatch/task.json --lock examples/epsilon_mismatch/task.lock.json --approve
.runtime/run-python -m photonguard run examples/epsilon_mismatch/task.json examples/epsilon_mismatch/candidate.json --lock examples/epsilon_mismatch/task.lock.json
# 将 RUN_ID 替换为刚才输出的实际运行编号
.runtime/run-python -m photonguard propose artifacts/RUN_ID --out patch.json
# 先阅读 patch.json，确认修改只恢复你要求的物理任务或数值流程
.runtime/run-python -m photonguard apply examples/epsilon_mismatch/task.json examples/epsilon_mismatch/candidate.json patch.json --lock examples/epsilon_mismatch/task.lock.json --out repaired.json --approve
.runtime/run-python -m photonguard run examples/epsilon_mismatch/task.json repaired.json --lock examples/epsilon_mismatch/task.lock.json
.runtime/run-python -m photonguard verify-evidence artifacts/RUN_ID
.runtime/run-python -m photonguard export artifacts/RUN_ID --out evidence.zip
```

CLI 返回码：PASS=0，FAIL=2，INCONCLUSIVE/输入错误=3，UNSUPPORTED=4。故障示例的非零退出是预期结果。

## 复现全部开发案例

```sh
.runtime/run-python -m pytest -q
.runtime/run-python -m pytest -q runtime/test_runtime.py
.runtime/run-python benchmark/run_development.py
```

开发矩阵包含正常真空/单层/多层、合法不同停止时间、n/epsilon 错配、参考幅度错配、缺失入射场扣除、真实欠采样数值问题、意图缺失和超范围角度。全部是**公开开发案例**，不是冻结盲测集，不把频点或重复运行计作独立案例。

## DeepSeek 接入状态

`diagnose-api` 支持 DeepSeek 的 OpenAI 格式 JSON 输出，要求明确模型、数据/费用批准、最坏价格与预算、持久化调用账本和安全注入的密钥。默认配置 `examples/deepseek.config.template.json` 明确未批准、预算0，所以不能调用。

接口及失败处理使用模拟传输测试，不是 DeepSeek 实际效果验证。目前真实 API 调用数仍为0。不要在聊天、配置文件或命令行参数里粘贴密钥。见 `docs/DEEPSEEK_BACKEND.md`。

另有 `export-model` / `import-model` 辅助式模型交换接口。它保留真实请求/回答与来源，和程序 API 调用分别记账；输入不含案例名称、故障标签或标准答案。模型建议仍需批准并经过真实 Meep 重验收。

## 当前仓库快照

这是用于私有仓库继续开发的源码快照，包含当前只读 AST 导入器、模型适配接口、公开开发案例与必要测试。已安装运行时、历史原始日志、运行结果、模型交换记录和已有交付 ZIP 不在仓库内。依赖安装锁保持原样；在新环境中运行 `bash runtime/bootstrap.sh` 后再执行上面的测试与基线命令。

此前同云主机全新目录的重装结果仅说明同主机复现，不等同于独立机器验证。历史交付包保持冻结；此仓库不把那些历史记录当作新环境已通过的证据。当前快照及检查范围见 `docs/SOURCE_SNAPSHOT.md`。

## 文件与证据

- `photonguard/`：任务边界、固定验收器、真实 Meep 子进程、受限修改与 CLI/UI
- `examples/`：人工注入/正常开发案例及明确标签
- `artifacts/<run_id>/`：每次运行单独保留原任务/候选、原始 Meep 数据、日志、报告及哈希
- `benchmark/`：可复跑的公开开发矩阵脚本；运行后本地产生冻结清单和结果
- `runtime/`：安装脚本、124 个包的精确 Linux 锁和运行时测试
- `docs/`：范围、安全、第三方来源、模型接口和源码快照说明

证据由应用只追加，结束后设置只读权限，清单可检测意外改动。拥有文件系统管理权限的人仍可修改文件和清单；这不是外部签名、不可篡改存储或第三方审计。

## 重要限制

- PASS 仅覆盖记录的离散频点、假设和容差；不保证连续整个波段或真实器件预测
- 两档数值设置相近只说明本次敏感性较小，不证明渐近收敛
- 当前 R/T 最大绝对误差 0.01，敏感性 0.005，是公开开发阈值，未在独立盲测集标定
- 无吸收、色散、各向异性、斜入射、基底、二维波导或任意 Python 导入
- 不自动寻找现有凭证；只有明确批准 API 调用后才读取专用安全环境变量，求解器子进程环境不传递凭证。DeepSeek 的 JSON API 适配、限额账本和结构化动作验收已实现；当前只做离线传输测试，尚无真实 API 调用
- 实际 AI 调用、同模型 A0/A1 对照、真实用户试用、另一独立机器重装仍未完成
- 提供的参考 ZIP 因下载服务 HTTP 502 未取得字节，没有检查或复用其中代码；本实现根据已完整读到的方案独立编写

## 许可证与来源

本项目源代码选择 GPL-2.0-or-later。Meep 是 GPL-2.0-or-later，tmm 是 MIT；项目不宣称求解器、数值方法或上游包为原创。源代码包不包含已安装运行时二进制。见 `LICENSE`、`docs/THIRD_PARTY.md` 与 `runtime/conda-linux-64.lock`。
