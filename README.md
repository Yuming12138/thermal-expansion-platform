# 热膨胀材料智能计算与设计一体化平台

英文仓库名：`thermal-expansion-platform`

当前版本：`0.3.0`（Web/API基础版、ALIGNN快速筛选与6701条活跃数据库）

本项目把课题中的物性计算、剪切—键合比判别、材料数据管理、NTE/PTE复合设计和Agent工具调用整合为一套可追溯平台。

## 当前已经落地

- 独立Git仓库和模块化Python包；
- 6702条原始NTE候选材料快照及6701条力学质量清洗活跃版本；
- SQLite数据模型、数据集版本和来源记录；
- JSON/JSON.GZ数据导入、唯一性和结构完整性校验；
- 剪切—键合比 `xi = G / E_tilde` 判别；
- ALIGNN预测G、快速E_tilde计算及带误差区间的上传结构预筛；
- ALIGNN快速预筛链路及模型误差区间；运行时间取决于硬件与模型是否常驻，不作为对外性能承诺；
- 两相ROM零热膨胀体积分数计算；
- 计算任务状态机和受控Agent工具注册骨架；
- 旧科研代码到新模块的迁移映射。
- 可运行的FastAPI服务与浏览器界面：材料检索、G-Ẽ景观、SBR、ROM和CIF/POSCAR基础检查。

## 项目结构

```text
src/te_platform/       平台核心代码
datasets/              数据版本、清单、模式和样例
docs/                  架构、数据契约和迁移说明
tests/                 核心算法与导入测试
apps/web/              后续Web前端
environments/          独立计算环境定义
var/                   本地数据库、任务和结果，不进入Git
```

## 快速开始（PowerShell）

无需安装第三方依赖即可运行当前数据和算法核心：

```powershell
Set-Location 'D:\9.Project\9.NTE&PTE_dataset\14.thermal_expansion_platform'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m te_platform init-db
python -m te_platform import-dataset
python -m te_platform dataset-stats
python -m te_platform search-materials --query Zr --limit 10
python -m te_platform material-detail 'CsNO3-mp-561851'
python -m te_platform classify-sbr --g 20.5 --e-tilde 8.0
python -m te_platform fast-screen --g-pred 20.5 --e-coh -4.2 --cell-volume 120 --atom-count 12 --avg-cn 3.5
python -m te_platform optimize-zte --alpha-pte 8.0 --alpha-nte -12.0
```

也可以使用统一入口脚本：

```powershell
.\scripts\tep.ps1 dataset-stats
```

## 启动Web界面（PowerShell）

```powershell
uv sync
.\scripts\run-web.ps1
```

随后在浏览器打开 <http://127.0.0.1:8000>。接口文档位于
<http://127.0.0.1:8000/docs>，测试可用 `uv run python -m unittest discover -s tests -v`。

## 科学边界

- 正式PTE/NTE分类边界使用 `xi_c = 2.84`；
- `xi < 2.5`仅表示高通量预筛中的高概率NTE候选；
- SBR用于热膨胀符号分类，不等价于精确预测完整 `alpha(T)`；
- 当前活跃数据库包含6701条记录，不代表全部材料均可直接合成；
- MatterSim、Phonopy、VASPKIT等属于外部依赖，不作为本仓库自有源码。

## 下一阶段

1. 把上传结构连接到常驻ALIGNN + MatterSim快速预测Worker；
2. 将现有MatterSim弹性与QHA流程迁移到统一模型适配器；
3. 将完整ROM曲线优化和修正后的Schapery-HS模型迁入；
4. 建立计算Worker、断点续算和结果质量标记；
5. 开发受控工具调用型Agent和科研报告导出。
