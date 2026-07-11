# 现有科研代码迁移映射

现阶段不把旧目录整体复制进新仓库。迁移时按算法单元重写接口、消除硬编码并增加测试。

| 旧代码 | 新模块目标 | 当前状态 |
|---|---|---|
| `D:\9.Project\10.recalcu_elastic_nte\auto_elastic_sh\elastic_calculator.py` | `compute/workflows/elastic.py` | 待迁移；先修正退出码、任务状态和模型解耦 |
| `D:\9.Project\10.recalcu_elastic_nte\auto_elastic_sh\qha_calcu.py` | `compute/workflows/qha.py` | 待迁移；先修正体积缩放、虚频和结果质量门控 |
| `D:\9.Project\10.recalcu_elastic_nte\auto_elastic_sh\batch_qha_Cij.py` | `jobs/worker.py` | 待迁移；保留批量编排思想 |
| `D:\9.Project\10.recalcu_elastic_nte\auto_elastic_sh\predict_g_avgcn_etilde.py` | `screening/sbr.py`及计算服务 | 已建立判别核心；特征计算待迁移 |
| `D:\9.Project\12.High_through_screening\predict_cif.py`及`jv_shear_modulus_gv_alignn` | `screening/alignn_shear.py` | 已建立懒加载适配器并真实验证；不迁移硬编码路径和静默NaN逻辑 |
| `D:\9.Project\5.NTE_PTE_Composite\utils\rom_zte_screening.py` | `composites/rom.py` | 已建立标量ROM核心；曲线优化待迁移 |
| `D:\9.Project\5.NTE_PTE_Composite\utils\optimize_vt_schapery.py` | `composites/schapery_hs.py` | 待修正相映射及上下界后迁移 |
