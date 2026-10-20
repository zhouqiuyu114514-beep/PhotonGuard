# RC7 观测与统计协议有限研究

这是可重跑开发证据，不是正式参赛材料。运行需要项目已有 NumPy / SciPy 环境，不使用 key、不执行 AI 请求、不运行 FFT/FDTD。

```sh
PYTHONPATH=.:local-validation/optics-optional-deps OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  /home/zhou/projects/PhotonGuard/.runtime/run-python -B \
  research/rc7-observation-20261013/run.py /path/to/new-empty-output
```

输出目录必须不存在，以免覆盖已有证据。脚本先写完整协议，按照 6 个开发情境、6 个检查情境顺序运行。检查情境也在第一项拟合前固定，未根据开发成绩调核、噪声、范围或阈值。每情境只拟合 point 与已校准 K 两支，每支一次固定 9 起点拟合，共最多 24 次拟合、720000 残差调用。首轮执行实际为 24 次拟合、216 个局部优化、26056 次残差调用。

独立教学对象先产生可见的校准观测，再产生初次强度扫描。分析器收到校准权重、坐标和来源，不收到器件真值。生成器用标量三角函数，分析器用 NumPy 函数，但共同理想物理模型明确披露。这不是独立仪器验证，也不是盲测。两支全部拟合完成后才产生另外一份教学验证扫描，不用它选择模型或调参。

三类各 4 个情境：

- 无平均：教学核为 delta，两个模型数值一致，缝宽差异小于 5e-8 μm。脚本原始 1e-10 算术胜负计数会计入舍入/收敛微小变化，不能报告为科学改进。
- 完整包络与已知非零核：4 项的缝宽、缝距和独立教学预测误差都改善。仅限这些预注册合成场景。
- 窄局部覆盖：已知核也没有普遍优势，缝距 3/4 退化，最大配对退化约 0.15345 μm；所有负结果保留。

另保存 301 个点、3 个相位的精确单频恒等式，不进行拟合。对称归一核的局部作用可被自由幅度/背景完全吸收，最大浮点差异 4.44e-16。该例允许“无法区分，需要校准或停止”；不把完整变化包络也宣称永远不可辨识。

## 复用接口

`inverse_models.predict_observation(x, parameters, model, group)` 是实际拟合与规划共用的观测预测。`predict` 保留原几何模型。已校准核只支持双缝，按真实坐标 `x-offset_mm` 评估解析模型，不按数组索引滤波，不对扫描边缘补伪观测。

```python
group['observation'] = {
    'kind': 'CALIBRATED_INTENSITY_AVERAGE',
    'kernel': {
        'offsets_mm': [-0.08, 0.0, 0.08],
        'weights': [0.25, 0.5, 0.25],
        'source': 'INDEPENDENT_CALIBRATION',
        'reference': '公开校准资料标识或用户明确说明',
    },
}
```

权重为积分质量，必须非负、和为 1、最多 65 个递增物理位置；不静默归一。来源可为 USER_DECLARED / INDEPENDENT_CALIBRATION / TEACHING_GENERATOR。POINT_SAMPLE、UNKNOWN、AVERAGING_UNKNOWN 仅注明观测适用性，不自动确诊模糊，不把原 PASS 变成失败。

旧 `EQUAL_DATASET_TRAINING_COUNT` 设置、历史计划结构及除法顺序保留。显式别名 `equal_dataset_mse` 使用同样目标，它的局部尺度只是目标灵敏度，不冒充真实协方差；本轮没有实现夹心方差估计。

新的 `declared_independent_noise` 必须逐组显式声明：

```python
settings['weighting'] = 'declared_independent_noise'
group['scale_source'] = 'KNOWN_MEASUREMENT_SD'
group['noise'] = {
    'sigma': 0.01,  # 正标量或逐点数组；半径 CSV 若自带 SD 必须一致
    'independent': True,
    'source': 'USER_DECLARED',
    'reference': '明确的噪声及独立性声明',
    'acquisition_id': '同一次物理采集的稳定 ID',
}
settings['future_noise'] = {k: v for k, v in group['noise'].items() if k != 'acquisition_id'}
```

仅修改数值尺度不会自动成为真实噪声声明。新协议残差为 `(prediction-observed)/sigma_i`；旧协议保持再除训练点数平方根。新协议 soft_l1 必须同时给 `f_scale_units='STANDARDIZED_NOISE_SD'`，显式等组协议使用 `SCALE_NORMALIZED_GROUP_RMS`，不悄悄更改异常点折扣单位。独立模式的局部线性尺度仍不是置信区间；稳健损失规划仍为线性代理。

`goal_design.information(..., future_assumption={noise_multiplier:..., amplitude_multiplier:...})` 只变未来组的公开敏感性假设；已知固定幅度不改，自由幅度被原批准范围限制，不改现有观测或事实。新独立协议若缺未来噪声声明，规划会要求补齐。

`observation_contract.merge_acquisition_fragments(groups,settings)` 提供显式导入前合并，返回 `groups` 和 `raw_csv_by_file`。同 acquisition_id 分片需先合并，恢复一个观测/一组曝光辅助参数；重复坐标不删除，直接拒绝。校准、曝光、物理条件或来源冲突拒绝。调用者保存返回的新 CSV 再导入，不覆盖旧记录。复制同一规范数据换 ID 也会被独立协议拒绝。声明仍依赖来源诚信，程序不能证明两个经过修改的文件确实来自独立实验。

13 项专项测试覆盖旧 81+81 等权数值一致、独立重复局部信息增长、拆片合并信息不变、复制拒绝、未来 5/81 点区别、稳健单位、非均匀物理坐标核、边界支持、候选曲线确实使用核和固定辅助参数。已有 39 项 inverse/goal 回归同时通过；这些小测试的拟合与上述 24 次研究窗口分开计数。

`audit_legacy.py` 只读核验 RC6 保存的 9 份 inverse 计划，哈希/固定预算/划分全部保持可验证，新增拟合为 0。初次研究启动因遗漏 PYTHONPATH 项目根而在导入阶段失败，尚未创建研究目录、开始拟合或消耗研究额度；原失败日志保留。随后正确启动只执行了上述一个批次。

方法接口来源：[SciPy least_squares 官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html)，尤其 `f_scale` 的残差单位和 `max_nfev` 不含数值 Jacobian 探测调用。本项目另累计实际残差调用。单频恒等式为直接代数推导及本目录保存的数值重放，没有使用外部黑箱结论。
