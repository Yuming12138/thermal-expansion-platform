# 热膨胀材料智能计算与设计一体化平台

英文仓库名：`thermal-expansion-platform`

当前版本：`0.5.0`（6701条活跃数据库、快速筛选、精确任务、ZTE设计与受控Agent）

本项目把课题中的物性计算、剪切—键合比判别、材料数据管理、NTE/PTE复合设计和Agent工具调用整合为一套可追溯平台。

## 当前已经落地

- 独立Git仓库和模块化Python包；
- 6702条原始NTE候选材料快照及6701条力学质量清洗活跃版本；
- 独立的185条PTE参考材料版本 `pte-reference-185-v1`，每条均保存POSCAR和0–990 K完整QHA热膨胀曲线；
- SQLite数据模型、数据集版本和来源记录；
- JSON/JSON.GZ数据导入、唯一性和结构完整性校验；
- 剪切—键合比 `xi = G / E_tilde` 判别；
- ALIGNN预测G、快速E_tilde计算及带误差区间的上传结构预筛；
- ALIGNN快速预筛链路及模型误差区间；运行时间取决于硬件与模型是否常驻，不作为对外性能承诺；
- 两相ROM零热膨胀体积分数计算；
- 分级结构预测入口：快速模式运行 ALIGNN G + MatterSim/CrystalNN Ẽ，精准模式独立计算完整弹性张量并使用 Hill G 完成 SBR，QHA 模式独立输出并保存 `alpha(T)`；
- 受控 MatterSim 弹性张量与 QHA 任务：固定 WSL/Conda/MatterSim/VASPKIT/Phonopy 命令、任务状态机、日志、弹性正定性和质量门控；
- 失败后仅重跑 QHA 的恢复任务：复用已完成的弹性张量，不重复应变计算，并支持嵌套恢复链路；
- QHA 位移级进度读取与虚频、非正定弹性张量、未应变弹性能异常等质量警告；
- 基于真实PTE/NTE `alpha(T)` 曲线的温区ZTE设计：检索两相材料、指定温区与目标热膨胀系数，优化固定体积分数并绘制PTE、NTE和混合曲线；
- 受控 Agent 工具注册、白名单调用和严格科学请求格式；
- 旧科研代码到新模块的迁移映射。
- 可运行的 FastAPI 服务与浏览器界面：材料检索、论文 Fig. 1d 景观、CIF/POSCAR 统一上传、三级预测、单温点/温区 ROM 和受控 Agent。
- 独立 Python 进程执行的受控 ALIGNN 剪切模量预测接口，以及 MatterSim + CrystalNN + SBR 的上传结构快速筛选；模型、源码、Python环境均可通过环境变量配置。

## 项目结构

```text
src/te_platform/       平台核心代码
datasets/              数据版本、清单、模式和样例
docs/                  架构、数据契约和迁移说明
tests/                 核心算法与导入测试
apps/web/              后续Web前端
environments/          独立计算环境定义
var/                   便携数据目录：数据库、上传、任务、结果和本机加密配置，不进入Git
```

## 快速开始（PowerShell）

无需安装第三方依赖即可运行当前数据和算法核心：

```powershell
Set-Location 'D:\9.Project\9.NTE&PTE_dataset\14.thermal_expansion_platform'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m te_platform init-db
python -m te_platform import-dataset
python -m te_platform import-pte-reference `
  --source-root 'D:\9.Project\9.NTE&PTE_dataset\9.gruneisen_parameter\PTE_materials' `
  --summary-csv 'D:\9.Project\9.NTE&PTE_dataset\9.gruneisen_parameter\plot_alpha_M\PTE_materials_summary_alpha_neg_300K_v3.csv'
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

Web 服务默认使用两个完全分离的数据库：

```text
var/releases/catalog-v1.sqlite   只读材料目录、结构、属性和历史曲线
var/workspace.sqlite             用户上传、预测任务和计算结果
var/uploads/                     用户上传的结构
var/runs/                        精确计算任务与结果
var/config/agent.env             本机 Agent 接口、模型和密钥配置
```

可通过 `TEP_CATALOG_DATABASE_PATH` 和 `TEP_WORKSPACE_DATABASE_PATH` 修改位置。启动时不会再从原始科研目录自动导入数据；缺少 `catalog-v1.sqlite` 会直接报告配置错误。

## 构建可分享的离线目录数据库

不要直接分发历史开发数据库。维护人员需要从明确指定的归档或数据构建库生成独立目录库：

```powershell
uv run python -m te_platform build-release-catalog `
  --source-db 'D:\path\to\archived-development.db' `
  --output 'var\releases\catalog-v1.sqlite' `
  --replace
```

生成的 `catalog-v1.sqlite` 已内置 NTE/PTE 材料、POSCAR、属性和完整热膨胀曲线，接收方不需要原始科研数据目录。构建器会删除开发期计算任务，将绝对路径替换为 `catalog://...` 逻辑来源，并生成包含文件哈希与计数的 `.manifest.json`。平台只读打开目录库，用户上传和新计算结果写入独立的 `workspace.sqlite`。详见 [发布目录数据库说明](docs/release-catalog.md)。

平台默认采用便携模式，所有运行数据都保存在项目内 `var/`，不会固定写入用户 C 盘目录。整个目录可以复制到其他磁盘或电脑；目录库随程序一起复制。发布或分享前应删除包含本机密钥的 `var/config/agent.env`，由接收方配置自己的 Agent。

配置 AI Agent：运行 `scripts\configure-agent.ps1`，脚本会用记事本打开项目内、已排除 Git 的 `var/config/agent.env`。将密钥粘贴在 `TEP_AGENT_API_KEY=` 后并保存。Agent 默认使用 OpenAI 兼容接口和 `gpt-5.6-luna`，只允许调用材料检索、材料详情、真实曲线全库查询、SBR、ZTE 设计、结构检查与计算任务等领域白名单工具，不会执行任意 shell 命令。

Agent 对话框支持直接附加 CIF/POSCAR。模型可以自主检查结构并提出快速、精准弹性或 QHA 计算计划，但不能自行批准计算：平台会持久化一个 `PENDING_APPROVAL` 动作，只有用户点击“确认并提交”后才启动后台任务。任务运行期间对话框会显示进度，成功后展示相应指标或完整热膨胀曲线。该控制层与计算层分离方式参考了 `openai/codex` 的公开工具路由和审批设计。

模型会根据问题自动选择计算层级：快速判断 NTE/PTE 倾向使用 `fast`，完整弹性张量与精准 SBR 使用 `elastic`，直接获得 α(T) 使用 `qha`。三种模式都进入后台任务并经过相同的用户审批边界；前端会根据任务类型展示快速筛选指标、弹性结果或 QHA 曲线。

## 科学边界

- 正式PTE/NTE分类边界使用 `xi_c = 2.84`；
- `xi < 2.5`仅表示高通量预筛中的高概率NTE候选；
- SBR用于热膨胀符号分类，不等价于精确预测完整 `alpha(T)`；
- 当前活跃数据库包含6701条记录，不代表全部材料均可直接合成；
- ZTE页面使用独立的185条PTE参考集与6701条NTE候选集；PTE界面仅显示化学式，但内部保留原目录编号用于曲线溯源；NTE选择项要求真实曲线在300 K为负。
- 当前复合模型输出体积分数；若要换算质量分数，需要进一步接入两相密度。用户上传曲线或结构作为复合相属于后续扩展入口。
- MatterSim、Phonopy、VASPKIT等属于外部依赖，不作为本仓库自有源码。

## 运行与结果边界

- 上传结构的快速结果用于预筛；即使运行耗时受硬件和模型冷启动影响，也不以“秒级”作为对外性能承诺。
- 精确任务可能耗时较长。系统将原始任务日志保留在 `var/runs/<job-id>/`，并在恢复时复用已完成的弹性结果。
- 若 QHA 日志报告虚频，平台仍可保留曲线供诊断，但会标记为定性结果，不能作为高置信热膨胀结论。
- 软件著作权的功能与截图清单见 [docs/software-registration.md](docs/software-registration.md)。
- V0.5.0 的真实集成验证证据见 [docs/validation.md](docs/validation.md)。
