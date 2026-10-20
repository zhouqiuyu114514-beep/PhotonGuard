# 三类无 UI、无 Key 的反向实验例子

这是开发复用入口，不是竞赛稿。三个脚本调用同一套有限拟合、证据和建议模块；不创建 Web 任务，不读取浏览器设置、个人 API Key 或隐藏评测对象，不调用语言模型。例子使用已公开的教学参数，不能再称盲测。

另有 RC8 小型单频校准例子：`python examples/inverse/single_frequency_calibration.py --teaching --out /tmp/pg-contrast --approve`。它只进行一次线性参照拟合，保存输入、独立暗场、策略与结果；也可用 `--input input.json` 替换教学输入。输出 `CONTRAST_AT_FREQUENCY`，不产生完整核或缝宽认证，不重置生产任务额度。

从源码根目录运行，先安装项目及分析依赖：

```sh
python -m pip install '.[analysis]'
```

如在未安装项目的源码副本中运行，先设置 `PYTHONPATH=.`。拟合工作进程目前使用 Linux 的内存/CPU 上限，Windows 请在 WSL 中运行；只读 JSON 不需要求解器。

## 明确输入与批准

计划 JSON 必须声明所有物理条件、待估范围、残差尺度、目标及允许位置。教学计划不能直接套在未知实测数据上；实测必须更改 `source` 和实际条件。点数与各组权重按 `settings.weighting` 的协议解释，数值尺度不是已经测得的噪声或置信区间。以下命令从源码根目录执行：

可选 `acquisition` / `followup_acquisition` 对象分别声明初次/补采的 `observation`、`noise`、`scale`、`scale_source`。不填写观测方式时保持未知；不会自动补已校准核。采用 `declared_independent_noise` 时必须按核心合同给出逐组 `noise.sigma`、`independent=true`、来源、参考和稳定 `acquisition_id`，以及 `KNOWN_MEASUREMENT_SD`；不同采集不能复用同一 ID，拆文件或复制 CSV 不会变成新独立证据。

```sh
python examples/inverse/generate_teaching.py --model slit --out /tmp/pg-slit.csv
python examples/inverse/slit_goal_compare.py --csv /tmp/pg-slit.csv --plan examples/inverse/slit-plan.json --out /tmp/pg-slit-run --approve

python examples/inverse/generate_teaching.py --model gaussian --out /tmp/pg-gaussian.csv
python examples/inverse/gaussian_followup.py --csv /tmp/pg-gaussian.csv --plan examples/inverse/gaussian-plan.json --out /tmp/pg-gaussian-run --strategy fixed --approve
python examples/inverse/generate_teaching.py --model gaussian --proposal /tmp/pg-gaussian-run/proposal.json --out /tmp/pg-gaussian-followup.csv
python examples/inverse/gaussian_followup.py --out /tmp/pg-gaussian-run --resume --followup /tmp/pg-gaussian-followup.csv --approve

python examples/inverse/generate_teaching.py --model film --out /tmp/pg-film.csv
python examples/inverse/film_identify.py --csv /tmp/pg-film.csv --plan examples/inverse/film-plan.json --out /tmp/pg-film-run --approve
python examples/inverse/generate_teaching.py --model film --proposal /tmp/pg-film-run/proposal.json --out /tmp/pg-film-followup.csv
python examples/inverse/film_identify.py --out /tmp/pg-film-run --resume --followup /tmp/pg-film-followup.csv --approve
```

输出目录必须新建，禁止覆盖已有证据；第二阶段只接受保存计划的实际坐标，使用 `--resume` 累计额度，不重复初拟合。教师生成器独立读取已经选定的坐标，然后生成新噪声扫描；实际仪器使用者在同一位置采集自己的 CSV 后执行第二阶段。读取结果不需要批准或新计算：

```sh
python examples/inverse/film_identify.py --out /tmp/pg-film-run --inspect
```

`workflow.json` 保存原/联合估计、诊断、累计预留额度、输入和结果哈希；`proposal.json` 保存基础方案、有限候选、预测尺度与选择原因。每个独立 CLI 目录最多 2 次拟合、1 次剖面、1 次补采、90000 次预留残差调用；每次仍使用核心的 30000 残差、60/120 秒、1 GiB 限制。失败保留记录和已用额度，不自动重试。这里是单独的复用研究任务，不续接或重置生产工作台的根额度。

## 输入格式和边界

| 脚本 | CSV 列 | 本例目标与边界 |
|---|---|---|
| `slit_goal_compare.py` | `position_mm,intensity_relative` | 理想相位 0、傅里叶焦平面、已知波长/焦距；有限 a/d 及允许曝光/背景估计；输出基础与候选方案，不能保证局部方案更好 |
| `gaussian_followup.py` | `z_mm,radius_1e2_um`，可选 `radius_sd_um` | M²=1 自由传播，同一全局 z 坐标；示例只有 5 个新位置，联合估计 w0/z0；1/e² 半径不是 FWHM |
| `film_identify.py` | `wavelength_nm,reflectance_calibrated` | 已知实折射率、法向入射、无损单层，仅反演厚度；本例目录只能 633/660/780 nm，任意亮度不能代替校准反射率 |

坐标必须递增、数值有限；解析器不会清洗或自动改单位。单波长膜厚保留周期和对称多解；追加一个波长也不保证唯一。`T=1-R` 不构成第二份独立证据。两份教学数据共享理想物理公式；独立生成代码不等于独立实验物理验证。公开生成器使用固定种子，重新运行相同种子不是新的独立观测。

## 薄 API 与替换策略

稳定入口位于 `photonguard.experiments.reuse`：`run`、`followup`、`inspect`。`run(..., strategy=callback)` 把公开状态副本传给本地可信 Python 策略。JSON 输入不能指定代码或动态导入模块。

```python
from photonguard.experiments import reuse

spec = reuse.read_json('examples/inverse/gaussian-plan.json')
state = reuse.run('/tmp/pg-gaussian.csv', spec, '/tmp/another-run',
                  approve=True, strategy=reuse.fixed_strategy)
```

替换策略读到声明条件、当前观测、真实已保存结果、候选菜单与目标；读不到尚未传入的后续 CSV 或生成器参数。输出只允许 `input_sha256`、`positions_mm`（薄膜为 `wavelengths_nm`）和 `reason`。统一验证检查状态绑定、有限性、点数、硬范围、步距、禁止扩展和近轴边界/允许波长目录。内置固定策略选择已验证目录内的基础方案；它用来展示复用接口，不声称新算法优于默认策略。自定义策略仍需研究者自己验证其效果。

这里使用现有 NumPy/SciPy/tmm 计算能力；算法来源、版本与许可证见 `docs/THIRD_PARTY.md`。项目 GPL 声明保持不变，未将第三方商业 API 当作团队开源模型。

## RC9 开发入口与依赖用途

上述三个脚本及薄 API 继续沿用，没有为新版页面另写一套求解器。修改教学案例时，改 `*-plan.json` 中的公开物理条件、目标与允许范围；新 CSV 必须来自明确的新采集或新生成输入，不能复制文件冒充独立观测。替换观测策略使用上面的 `strategy=callback`，数值算法仍由核心合同验证。

| 依赖 | 当前用途 | 缺少时 |
|---|---|---|
| Python 3.10+、NumPy | 核心数据、解析模型与基础计算 | 安装项目必需 |
| SciPy（`analysis`） | 三类有限反向拟合 | 仍可查看旧结果、导出和使用基础正向工具；反向计算暂停 |
| tmm | 单层/多层膜正向及膜厚分析 | 项目安装时提供；膜计算需此依赖 |
| LightPipes（`experiments`） | 可选衍射传播引擎 | 使用并明确标注 NumPy 后备 |
| Meep / MPB | 保留的高级波动与证书研究入口 | 不是三项用户任务或这些 CLI 例子的前置条件 |
| DeepSeek API | 工作台中的语言条件整理与下一步建议 | 三个 CLI 例子均不需要 Key、网络或模型调用 |

产品接续位于 `photonguard.experiments.task_flow`：它组合现有 `observation_group` 操作，不改变上述 CLI 状态或累计额度。纯摘要位于 `task_view.summary`，页面与导出共享；发送模型时去掉图中原始采样数组，保留同一份目标、估计和变化。
