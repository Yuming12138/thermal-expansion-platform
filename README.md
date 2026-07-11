# 热膨胀材料智能计算与设计一体化平台

英文仓库名：`thermal-expansion-platform`

当前版本：`0.5.0`（6701条活跃数据库、快速筛选、精确任务、ZTE设计与受控Agent）

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
- 受控 MatterSim 弹性张量与 QHA 任务：固定 WSL/Conda/MatterSim/VASPKIT/Phonopy 命令、任务状态机、日志、弹性正定性和质量门控；
- 失败后仅重跑 QHA 的恢复任务：复用已完成的弹性张量，不重复应变计算，并支持嵌套恢复链路；
- QHA 位移级进度读取与虚频、非正定弹性张量、未应变弹性能异常等质量警告；
- 单温点及温区 `alpha(T)` 曲线 ZTE ROM，输出体积分数和质量分数；
- 受控 Agent 工具注册、白名单调用和严格科学请求格式；
- 旧科研代码到新模块的迁移映射。
- 可运行的 FastAPI 服务与浏览器界面：材料检索、G-Ẽ 景观、SBR、单温点/温区 ROM、CIF/POSCAR 结构检查、快速筛选、精确任务和受控 Agent。
- 独立 Python 进程执行的受控 ALIGNN 剪切模量预测接口，以及 MatterSim + CrystalNN + SBR 的上传结构快速筛选；模型、源码、Python环境均可通过环境变量配置。

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

## 运行与结果边界

- 上传结构的快速结果用于预筛；即使运行耗时受硬件和模型冷启动影响，也不以“秒级”作为对外性能承诺。
- 精确任务可能耗时较长。系统将原始任务日志保留在 `var/runs/<job-id>/`，并在恢复时复用已完成的弹性结果。
- 若 QHA 日志报告虚频，平台仍可保留曲线供诊断，但会标记为定性结果，不能作为高置信热膨胀结论。
- 软件著作权的功能与截图清单见 [docs/software-registration.md](docs/software-registration.md)。
- V0.5.0 的真实集成验证证据见 [docs/validation.md](docs/validation.md)。
