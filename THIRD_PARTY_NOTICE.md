# 第三方资源与使用说明

PhotonGuard项目源码遵循GPL-2.0-or-later，许可文本位于根目录LICENSE及app/source/LICENSE，版本声明位于app/source/pyproject.toml。

| 资源 | 作用 | 许可或使用方式 |
|---|---|---|
| Python | 本地服务与执行环境 | PSF |
| NumPy | 数值数组、二维FFT与解析计算 | BSD-3-Clause及发行通知 |
| tmm | 薄膜传输矩阵计算 | MIT |
| SciPy | 有界非线性最小二乘与局部参数优化 | BSD-3-Clause及发行通知 |
| DeepSeek API | 条件理解与下一步建议 | 服务商适用条款，使用者个人账户 |

第三方依赖在使用者电脑准备环境时下载，各发行包的LICENSE与NOTICE继续适用。依赖版本以 app/source/pyproject.toml 和 app/launcher 的环境锁定文件为准。DeepSeek通过个人账户的远程API使用，不随项目分发模型权重。

随附历史膜厚案例使用教学合成数据；保存结果与截图来自项目任务记录。外部用户CSV的使用权利取决于其数据来源。
