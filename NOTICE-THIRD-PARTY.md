# 第三方软件与数据说明

本仓库的自有部分重点包括任务编排、数据治理、质量控制、SBR判别、复合优化、结果溯源、报告和Agent工具接口。

后续计算环境可能使用以下第三方项目，但不会把它们的源码或模型权重作为本项目自有代码登记：

- ASE
- ALIGNN（NIST Terms of Use，须保留原许可与免责声明）
- DGL
- MatterSim及其模型权重
- Phonopy / Phono3py
- pymatgen（MIT），用于 POSCAR/CIF 解析、CrystalNN 周期近邻和键合图生成
- VASPKIT
- NumPy / SciPy / Pandas
- FastAPI / SQLAlchemy
- 3Dmol.js 2.5.5（BSD-3-Clause），用于浏览器端晶体结构交互渲染；许可证随文件保存在 `src/te_platform/web/vendor/3Dmol-2.5.5-LICENSE.txt`

6702条候选材料数据包含由Materials Project标识关联的派生信息和本课题计算结果。在公开发布仓库或数据库前，应再次核查原始数据条款、引用方式和可再分发范围。当前仓库先作为课题内部的可追溯研发版本。
