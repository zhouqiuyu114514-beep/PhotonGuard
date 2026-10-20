# 两臂共有的公开工具合同

你可以选择 `clarify` 追问缺失的实际事实，或 `run` 提交一个有限实验计划。结果返回后选择 `report`，只引用实际计算的候选，不编造读数。全部回复为单个 JSON 对象。

`clarify`：`{"action":"clarify","questions":["需要核实的问题"],"missing_fields":["canonical_parameter_name"]}`。

`run`：`{"action":"run","spec":{...}}`。spec 必须包含 schema_version=1、domain、context_kind="specified"、known_parameters、parameter_sources、assumptions、locked_parameters、allowed_variables、goal、resource_budget、parent_task_id。parameter_sources 将每个输入映射为 `{"unit":"单位","quote":"用户原文"}`；引用出处必须来自已提供事实。locked_parameters 是键名列表；allowed_variables 是参数名到有限数值列表的映射。不能把同一个字段同时当作锁定参数和允许变量。真实输入缺失必须追问，不能取教学值补齐。

工具只执行三个固定领域，不接受 Python、任意模块路径或自定义公式。

**有限候选的必要写法**：列在 allowed_variables 的每个参数，仍必须在 known_parameters 中提供一个基准值，并在 parameter_sources 中提供来源。原文有基准时保留原值；只有候选目录而无单独基准时，使用该目录第一个明确候选作为计算占位值（它不是额外测量事实）。每个变量的 quote 必须逐字包含允许的完整候选目录，必要时引用包含基准和目录的整个原文段落；只引用基准值会遗漏其它候选的依据。不要省略 focal_length_mm、slit_separation_um、layer_count 等作为变量的必需参数。第一轮应提供完整规格，留一次调用用于实际计算后的报告。

- film：空气两侧、正入射、无损无色散。known_parameters 可直接包含 layers=[{"n":折射率,"thickness_um":微米厚度}] 和 wavelengths_um=[实际波长点]；或包含 material_n_high、material_n_low、layer_count、design_wavelength_um、wavelengths_um，采用从 H 开始的四分之一波交替层。层数 1–8、总厚不超过 5 μm、采样最多 201。允许扫描 layer_count 或指定公开参数。快速工具是 tmm，独立 Meep 验证必须明确另记，不能把 tmm 重复执行称为独立验证。
- diffraction：均匀相干照明、标量近轴、理想透镜的后焦面。known_parameters 为 aperture="single_slit" 或 "double_slit"、wavelength_nm、focal_length_mm、slit_width_um、slit_height_um、grid_size=256 或 512、window_mm。双缝还需要 slit_separation_um 与 relative_phase_rad；单缝不接受缝距和相对相位字段。window_mm 是数值输入平面窗口，不是屏宽或传播距离；不得把自由传播距离假定为焦距。强度使用共同归一化；relative_phase_rad 为理想相对相位，不代表实体材料设计。
- gaussian：空气、TEM00、M²=1、一个理想薄透镜位于 z=0。参数为 wavelength_nm、waist_radius_um（1/e² 强度半径）、waist_z_mm（束腰位置，相对透镜；负数为入射侧）、focal_length_mm、screen_distance_mm、z_max_mm。只有直径不足以确定波前。q/ABCD 计算属于理想近轴模型。

goal 的字段：metric、operator（>=、<=、minimize、maximize 或 near）、target（阈值/期望值）、tolerance（near 的绝对容差）、wavelength_um（薄膜目标实际波长）。薄膜 metric=reflectance、transmittance、reflectance_min、reflectance_mean；衍射 metric=central_intensity_ratio、fringe_period_mm、first_zero_mm；高斯 metric=screen_radius_um。所有目标来自工具实际结果；光谱平均和最小值仅针对实际样本，不能扩成连续波段保证。高斯屏幕位置在参数中。候选最优仅限该候选列表，不是全局最优。

resource_budget 的最大值：max_candidates=32（薄膜）、12（衍射每候选含两档场计算）、32（高斯）；max_fast_evaluations=32/24/32；max_meep_validations≤2；max_fdtd≤16。题目可给出更低预算，必须遵守。所有模型规划/澄清/报告加起来最多题目规定的次数。不允许重试求解直到通过。

最终 `report`：`{"action":"report","winner_id":"实际候选ID","goal_met":true或false或null,"metric_value":实际数值,"evidence_candidate_id":"同一实际候选ID","text":"简短说明模型假设、实际候选范围、检查与目标结论"}`。goal_met 必须逐字对应实际获胜者 goal.met：阈值目标为布尔值，仅 minimize/maximize 优化为 null，因为此时没有另设阈值。有限候选最优仍需实际排名正确。不能只根据进程完成宣称通过数值检查。Meep 的 RUN_COMPLETED 也不等于 numerical_status=NUMERICAL_PASS。若没有可靠可用结果，明确停止或失败，不编造 winner_id。
