# 五分钟：脚本导入、任务确认、检查、受限修复和复验

前提：已在支持的 Linux x86_64 环境完成 `bash runtime/bootstrap.sh`，在项目根目录执行。
五分钟估计不含下载/安装或首次阅读；本轮实际耗时见交付 checkpoint 报告。
这是公开合成开发案例，演示规则流程；运行时模型调用为 0，不能作为 AI 增量实验。

## 1. 创建独立演示目录并准备合成故障

下面只复制示例，将介电常数故意设为 2；独立任务仍要求折射率 n=2、厚度 0.3 微米。
Python 块操作的是文本，不执行待导入脚本。项目原始示例保持原样。

```sh
DEMO_DIR="$(mktemp -d "$PWD/inputs-demo-XXXXXX")"
export DEMO_DIR
.runtime/run-python - <<'PY'
import os
from pathlib import Path
root = Path(os.environ['DEMO_DIR'])
source = Path('examples/script_import/film_n2.py').read_bytes()
assert source.count(b'mp.Medium(index=n)') == 1
(root / 'input.py').write_bytes(source.replace(b'mp.Medium(index=n)', b'mp.Medium(epsilon=n)'))
print(root)
PY
.runtime/run-python -m photonguard import-script "$DEMO_DIR/input.py" --out "$DEMO_DIR/import"
.runtime/run-python -m photonguard prepare-task "$DEMO_DIR/import/candidate.json" --out "$DEMO_DIR/intent"
cat "$DEMO_DIR/intent/REVIEW.zh.md"
```

预期 `EXTRACTED`、`NEEDS_USER_INTENT`。`task.draft.json` 的物理量全部待填写，尚无锁或 PASS。
对真实输入必须独立确认意图；不能从脚本 epsilon=2 推断想要 n=sqrt(2)。

## 2. 明确演示任务，然后确认

这里只使用已有且明确标注的开发任务作为独立来源；真实项目不得照抄演示参数。
先阅读任务：1D、正入射、线性无损无色散各向同性非磁性、两侧空气，每 Meep 单位 1 微米；
一层 n=2、0.3 微米；波长 1.3–1.7 微米、41 个点。

```sh
cp examples/film_n2/task.json "$DEMO_DIR/intent/task.json"
cat "$DEMO_DIR/intent/task.json"
# 阅读后明确批准这个开发任务；未知量没有填写清楚时应停止。
.runtime/run-python -m photonguard confirm "$DEMO_DIR/intent/task.json" --candidate "$DEMO_DIR/import/candidate.json" --lock "$DEMO_DIR/intent/task.lock.json" --approve
```

CLI 拒绝不完整任务、超范围物理量、不匹配的导入谱段及已有锁。材料差异保留给后续检查。

## 3. 检查并读取证据

```sh
.runtime/run-python -m photonguard run "$DEMO_DIR/intent/task.json" "$DEMO_DIR/import/candidate.json" --lock "$DEMO_DIR/intent/task.lock.json" --out "$DEMO_DIR/before"
BEFORE_RUN="$(find "$DEMO_DIR/before" -mindepth 1 -maxdepth 1 -type d)"
cat "$BEFORE_RUN/report.json"
.runtime/run-python -m photonguard verify-evidence "$BEFORE_RUN"
```

预期 `FAIL`、退出码 **2**，这是故障演示的预期结果；如在启用 `set -e` 的脚本中运行，需显式处理退出码 2。
本步启动真实 Meep，四组参考/目标配对共 8 次 FDTD，并与独立 tmm 参考比较。
`report.html` 可用本机浏览器打开；原始数据、源码字节、任务及锁在证据目录。

## 4. 阅读建议，再明确批准一次受限修改

```sh
.runtime/run-python -m photonguard propose "$BEFORE_RUN" --out "$DEMO_DIR/patch.json"
cat "$DEMO_DIR/patch.json"
# 检查 backend=rules_only、actual_llm_calls=0，唯一修改应是 epsilon: 2 → 4。
# 仅在你同意恢复已确认 n=2 的任务后执行：
.runtime/run-python -m photonguard apply "$DEMO_DIR/intent/task.json" "$DEMO_DIR/import/candidate.json" "$DEMO_DIR/patch.json" --lock "$DEMO_DIR/intent/task.lock.json" --out "$DEMO_DIR/repaired.json" --approve
```

建议来自已有规则。修复输出为新候选文件；原脚本、原候选、任务锁不变。
不要将 `--out` 指向原始候选或既有补丁；当前 `apply`/`propose` 仍要求操作者选择新输出路径。
若建议不是唯一的介电常数修改，或审批前的任务/候选哈希发生变化，停止排查。

## 5. 真 Meep 复验和前后对照

```sh
.runtime/run-python -m photonguard run "$DEMO_DIR/intent/task.json" "$DEMO_DIR/repaired.json" --lock "$DEMO_DIR/intent/task.lock.json" --out "$DEMO_DIR/after"
AFTER_RUN="$(find "$DEMO_DIR/after" -mindepth 1 -maxdepth 1 -type d)"
.runtime/run-python -m photonguard verify-evidence "$BEFORE_RUN"
.runtime/run-python -m photonguard verify-evidence "$AFTER_RUN"
cat "$AFTER_RUN/report.json"
```

预期 `PASS` 和两次 `VERIFIED`；复验新增 8 次真实 FDTD。原始脚本没有执行、也没有被修复；
PASS 只属于修复后的规范化配方、锁定任务、既定容差和离散频点。两档数值敏感性不是渐近收敛证明。
可分别打开前后 `report.html` 查看；CLI 流程不依赖浏览器。当前网页仅查看证据，不接受上传、审批或启动仿真。

DeepSeek API、本地密钥配置、自然语言意图理解和 AI 增量均不在此演示中。后续接手见 `LOCAL_CODEX_HANDOFF_ZH.md`。

## 本机可重复执行的开发演示

完成运行时安装后，也可以用以下入口重放上述固定合成案例：

```sh
.runtime/run-python benchmark/run_local_checkpoint.py --out local-validation/cli-demo-NEW --approve-synthetic-demo
```

输出目录必须尚不存在。批准仅适用于仓库中 `film_n2` 开发任务，以及程序检查过的
唯一 `epsilon: 2 → 4` 规则修改；这个入口不接受用户脚本或模型配置。
程序调用已有 CLI，在每一步保存命令、退出码、机器耗时和 stdout/stderr 哈希；
要求初次 FAIL、复验 PASS、两轮各 8 次真实 FDTD、两份证据完整性通过，
并核对原始输入、导入副本、原候选、任务、任务锁和仓库示例不变。
任一步不符合预期便停止并保留日志，不改物理政策或验收容差。

这是一项自动化开发验证，没有记录真人审核，人工编辑数和审核时间保持 null。
运行结果见新目录中的 `operations.json`、前后 `report.html` 和 `report.json`。
