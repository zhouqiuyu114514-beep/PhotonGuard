# 独立小型证书

数学命题及模型语义见 [PROOF_ZH.md](PROOF_ZH.md)。本模块只签发冻结周期连续模型的子结果，目标排序未绑定，不能改写生产 QPM。

使用交付包的 model.json 与 basis-binding-v3/common-r40-trials.npz。Linux/WSL 中从源码根目录运行：

```sh
python -B -m research.goal_certificate.bounded_checker --model /path/model.json --pump
python -B -m research.goal_certificate.bounded_checker --model /path/model.json --trials /path/common-r40-trials.npz --reassemble --output /new/path/recheck.json
```

第一条纯标准库，≤256 MiB/60秒；第二条依赖NumPy，≤1 GiB/600秒，启动时还要求可用RAM至少为上限两倍。Linux资源限制和墙钟闹钟均生效。输出文件必须不存在；错误即停。第二条会新增两次局部矩阵组装，0物理本征求解、0API，需要单独的复现窗口。本次原8次组装预算已耗尽，不在其中再次执行。

清单/已存3×3矩阵重放属于完整性复核；只有重新组装才复核从DOF到矩阵的链。交付记录保留两次失败及两次明确的计划修订，不删除失败后冒充首轮成功。

优化模式（`-O`、`-OO`或`PYTHONOPTIMIZE`启用）会在导入时明确拒绝，避免跳过内核断言。新CLI输出附execution_binding，记录实际输入字节和检查器源码哈希、优化级别；它不替代模型来源认证或目标模式绑定。云端复现与本轮修复范围见[接收记录](../../docs/CLOUD_REPRODUCTION_FOLLOWUP_20261008_ZH.md)。
