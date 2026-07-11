# 数据集管理

## 活跃数据版本

`nte-candidates-6701-v1-1`包含6701条唯一材料记录，是平台默认数据库版本。它从原始6702条快照中排除了`CsNO3-mp-561851`，原因是`K_GPa=-88.209`。

`nte-candidates-6702-v1`继续作为不可变的原始历史版本保存，每条记录均包含POSCAR结构和24项材料属性。

原始来源：

```text
D:\9.Project\5.NTE_PTE_Composite\0.NTE_new_dataset\nte_ml_features_filtered.json
```

原始目录约5.7 GB，并包含大量QHA图、PDF及中间数据。为保持仓库清洁，Git只纳入结构与属性JSON压缩快照；原始QHA结果目录不复制进Git，通过清单中的路径和校验和追溯。

数据发布约定：

- `datasets/manifests/`：版本、来源、记录数和校验和；
- `datasets/schema/`：字段契约；
- `datasets/sample/`：可直接进入普通Git的小样例；
- `datasets/releases/`：Git LFS管理的完整压缩快照；
- `datasets/processed/`：可重建的Parquet/SQLite等产物，不进入Git。

不得直接修改已经发布的数据快照。字段修正或记录增删应发布新版本，并保留转换脚本和变更说明。
