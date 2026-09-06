# 重构方案（v0.10.0 → v1.0.0）

本文档记录全栈重构的目标、架构、阶段划分与验收标准。已确认的前提：**前后端并行重写**、**前端采用 React + Vite + TypeScript**、**无向后兼容硬约束**（可走 Breaking Change）。

---

## ⛔ 阻塞项：各向异性数据契约（未解除前不得进入阶段 1 及以后）

热膨胀本质上是**二阶对称张量**，而现有数据集全部为**标量**，方向信息从未被采集。用户将提供**新的各向异性数据集**。在数据契约定稿前，任何涉及数据模型、复合模型、筛选引擎的重构都必须暂停——否则将把标量假设固化进新架构，后续推倒重来的代价远高于等待。

### 已核实的现状

| 位置 | 事实 |
|---|---|
| `db/schema.py:109-116` | `points_json` 为 `[[T, alpha], ...]`，每温度点仅 1 个数 |
| `api/app.py:605,792` | 导出表头自述 `volumetric_thermal_expansion_coefficient_1_per_K`，即体积量 α_V |
| `datasets/schema/*.json` | 无张量分量字段，也无晶系字段 |
| Phonopy QHA | 标准 QHA 只输出体积量 α_V，无法提供方向信息 |

### 物理要点

- `α_V = tr(α) = α₁₁ + α₂₂ + α₃₃` 是**旋转不变量**，现有标量数据即此迹，因此**不是错误数据、不必作废**；"体积零膨胀"在张量框架下依然成立。
- 方向线膨胀 `α(n) = nᵀαn` 需要全张量。
- 每个温度点需存的分量数取决于晶系：立方 1、六方/三方/四方 2、正交 3、单斜 4、三斜 6。**单斜与三斜的主轴随温度转动，必须存完整张量而非仅主轴值。**

### 新数据集交付时需确认的字段定义

1. 晶系字段，或由 POSCAR 推导晶系的规则。
2. 每温度点的张量分量：给出 `α₁₁ α₂₂ α₃₃ α₂₃ α₁₃ α₁₂` 中的哪几个、以何顺序。
3. 坐标系约定：相对于晶轴 `(a, b, c)` 还是笛卡尔系；单斜/三斜是否同时给出随温度变化的晶格角。
4. 量纲约定：体膨胀 α_V 还是线膨胀分量；单位 `1/K` 还是 `ppm/K`。
5. 缺失张量数据的材料如何降级到标量 α_V。

### 可先行处理的量纲问题（与张量化正交）

- `composites/` 中搜索不到任何体积↔线膨胀的 3 倍换算（Kerner/Turner 里的 `3.0` 是弹性约束项 `3K_pK_m/(4G_m)`，与膨胀量纲无关）。因此 ZTE 容差 `zte_tolerance_ppm_per_k` 直接与 α_V 比较，其语义相对线膨胀**偏大 3 倍**。
- `importer.py:32` 将 `TE_300K` 标注为 `1/K`，但样例值 `-16.24` 的量级只可能是 `ppm/K`，标注与实际相差 **10⁶**。

---

## 1. 重构目标

| 维度 | 现状 | 目标 |
|---|---|---|
| 后端分层 | 路由内直接写 SQL 与领域编排，`create_app()` 917 行 | `api → services → domain → repositories` 四层，依赖严格单向 |
| 前后端契约 | 52 路由 / 0 个 `response_model`，字段名两边硬编码 | OpenAPI 为唯一真值，自动生成 TS 类型 |
| 领域层 | 与 I/O 深度耦合，物理公式双份实现 | 纯函数、零 I/O，公式与单位单一真值 |
| 数据访问 | SQL 散落 16 个文件，无迁移机制 | 集中于 repositories 层，版本化迁移 |
| 错误处理 | 2 个自定义异常，`except ValueError` 重复 25 次 | 领域异常体系 + 全局 handler + 统一错误 envelope |
| 前端 | 4519 行全局作用域，9 个重复 Canvas 绘图器 | React 组件化 + ECharts 统一绘图 |
| 可测试性 | 无 `conftest.py`，测试依赖真实数据库 | 领域层 100% 纯单测，集成测试用临时库 |

**必须保留的设计**（重构不得破坏）：

- 双库分离：`catalog-v1.sqlite`（`mode=ro&immutable=1` 只读）与 `workspace.sqlite`（读写），由 `db/schema.py` 代码级强制。
- Agent 的 SQL 四层防护（`agent/database_tools.py:195-286`）：只读连接 + 关键字白名单 + `set_authorizer` 表级授权 + 行数与超时限制。
- Agent 审批边界（`PENDING_APPROVAL`）：模型不得自行批准计算任务。
- 任务状态机集中定义（`jobs/states.py`）与恢复链环检测。

## 2. 必须先解决的 P0 缺陷

### P0-1 ｜ 筛选与精修的复合模型口径不一致（需物理判定）

- 精修/设计：`composites/curve_rom.py:240-262` 的 Kerner 含完整弹性修正项
  `α = f_m·α_m + f_p·α_p + correction·(α_p − α_m)`
- 全库筛选：`composites/screening.py:548` 一律使用线性混合
  `mixed = pte_curve + f·(nte_curve − pte_curve)`
  其中 `f` 由 `_volume_fractions()`（`:208-262`）按 Turner/Kerner 换算，**修正项被丢弃**。

后果：185×6701 排名给出的 RMS / 覆盖率，与候选详情精修结果可能对不上。

处置：由你判定哪个是物理真值，然后统一到 `domain/composites` 的单一实现，并补回归测试锁死两者一致。

### P0-2 ｜ `ξ` 正式边界自相矛盾

- `screening/sbr.py:6` `FORMAL_BOUNDARY = 2.84`（判定用）
- `api/app.py:313` `formal_boundary: 2.84151`（`/api/about` 对外上报）

处置：收敛为 `domain` 层单一常量，对外上报与判定同源。

### P0-3 ｜ 精准任务无超时、无取消

- `jobs/precision_runner.py:296-301` `subprocess.run` 未传 `timeout`，QHA 可无限挂起。
- `jobs/states.py` 定义 `CANCELLED`，但无终止进程 / join 线程的任何逻辑。

处置：引入任务执行器抽象，支持超时、取消与结构化日志轮转。

### P0-4 ｜ 状态迁移竞态

`jobs/repository.py:179-193` 先读状态、再另开连接 UPDATE，两操作不同事务，双 worker 可同时通过校验后双写。参考 `agent/actions.py:99-113` 已有的乐观锁写法（`UPDATE ... WHERE id=? AND status=?` + rowcount 检查）统一修正。

## 3. 目标架构

```text
apps/web/                     前端源码（新建，Vite + React + TS）
src/te_platform/
  api/                        HTTP 层
    routes/                   按域拆分 router（materials / composites /
                              screening / structures / jobs / agent / reports）
    schemas/                  Pydantic v2 请求 + 响应模型
    deps.py                   依赖注入提供者
    errors.py                 领域异常 → HTTP 映射 + 全局 handler
  services/                   用例编排、事务边界、外部进程与任务生命周期
  domain/                     纯函数，零 I/O
    units.py                  单位换算与物理常数（唯一真值）
    materials.py              Material / AlphaCurve 值对象
    composites/               ROM / Turner / Kerner 单一实现（标量与向量同源）
    screening/                SBR 判别与快速预筛
  repositories/               SQL 集中于此，只读与读写连接分离
  infra/                      迁移、外部进程、WSL、存储
var/releases/catalog-v1.sqlite   只读目录库
var/workspace.sqlite             读写工作库
```

强制约束：

1. `domain` 层不得 import `api`、`services`、`repositories`、`infra`，不得执行 I/O。用 import-linter 或 CI 脚本静态校验。
2. `api` 层不得直接写 SQL，只依赖 `services`。
3. `repositories` 层不得 import `api` 或 `services`（修复现有 `jobs/precision_runner.py:11` 反向 import `api.structures` 的倒置）。

## 4. 技术选型

| 项 | 选择 | 理由 |
|---|---|---|
| 前端框架 | React 18 + Vite + TypeScript | 类型可与后端契约对齐；生态成熟 |
| 服务端状态 | TanStack Query | 统一 loading / 错误 / 重试 / 竞态，替代手写 `api()` |
| 客户端状态 | Zustand | 轻量，替代 28 个全局 `let` |
| 图表 | Apache ECharts | 需承载 6701 点散点、多曲线叠加、2D 热图；canvas 渲染，体积小于 Plotly |
| 3D 结构 | Crystal Toolkit（Materials Project 同源） | Dash/VTK.js 组件挂载于 FastAPI `/ctk/`，详情页直接嵌入；3Dmol 仅保留给上传/组合工作区 |
| 类型生成 | openapi-typescript | 从 FastAPI OpenAPI 生成 TS 类型，契约单一真值 |
| 后端契约 | Pydantic v2 + `response_model` 全覆盖 | 现状 0 个响应模型，是最大契约缺口 |
| 迁移 | 轻量顺序迁移器（版本化 SQL 文件） | 替代 `CREATE TABLE IF NOT EXISTS` |

## 5. 分阶段路线图

### 阶段 0：地基与回归基线

1. 打通可运行环境：下载或构建 `var/releases/catalog-v1.sqlite`，使 `uv run python -m unittest discover -s tests -v` 全绿。
2. 录制当前 52 个 API 的响应样例快照，作为重构前后的行为对照基线。
3. 补齐 CI：ruff + mypy + 测试。
4. 新增 `tests/conftest.py`，用临时目录与临时数据库隔离。

**验收**：测试套件在干净环境下可重复运行且全绿；CI 通过。

### 阶段 1：领域层纯化 ⛔ 待各向异性数据契约定稿后启动

本阶段的核心是数据模型与物理公式，直接依赖新数据集的字段定义。**阻塞项未解除前只做两件不依赖新数据的事**：`domain/units.py` 的单位与常数收敛、量纲问题澄清（见阻塞项章节末）。

1. 建立 `domain/units.py`，收敛全部物理常数与单位换算：
   `160.21766208`（eV/Å³→GPa）、`1e6`（ppm）、`1.66053906660`（amu→g）、`2.84` / `2.5`（ξ 边界）、`9.476007`（ALIGNN MAE）。
   现状 `160.21766208` 硬编码 7 处，含 SQL 内一份（`catalog/queries.py:248`）。
2. 定义值对象 `Material`、`AlphaCurve`、`CompositeDesign`，替换 `material_pair.py:266-285` 等处的裸 dict（现状 `α(T)` 曲线有 tuple / list / ndarray 三种表示并存）。
3. **统一复合模型**：`domain/composites` 只保留一套 ROM / Turner / Kerner 实现，标量版与向量版同源；修复 P0-1。
4. 为领域层补 100% 纯单测，含 Kerner 双实现一致性测试。

**验收**：`domain` 层零 I/O、测试覆盖达 100%；`grep -r "sqlite3\|open(\|requests\|subprocess" domain/` 无结果。

### 阶段 2：契约定稿 ⛔ 待各向异性数据契约定稿后启动（前后端的分水岭）

1. 定义全部 Pydantic v2 请求与响应模型，覆盖所有对外端点。
2. 生成 OpenAPI 与 TS 类型，提交 `apps/web/src/types/api.ts`。

**验收**：`openapi.json` 中每个端点都有完整响应 schema；TS 类型生成成功，前端开始消费。

### 阶段 3：并行实施 ⛔ 依赖阶段 2

**前端脚手架例外**：Vite + React + TS 的工程骨架、路由与构建流水线不依赖数据契约，可在阻塞期内先行搭建。

**后端（阶段 3B）**

1. `api/app.py` 按域拆分为 7 个 router，`create_app()` 瘦身为装配函数。
2. 依赖注入替代闭包捕获 db 路径（现状 52 个路由闭包捕获，无法独立单测）。
3. `repositories` 层集中全部 SQL，引入版本化迁移。
4. 统一错误体系 + 全局 exception handler，消除 25 处重复的 `except ValueError`。
5. 修复 P0-3（超时 / 取消）与 P0-4（竞态），解依赖倒置。
6. 清理 20 个无消费者的死路由。

**前端（阶段 3F）**

1. Vite + React + TS 脚手架，`apps/web/`。
2. 按工作区拆分页组件：检索、Fig.1d 景观、结构详情、ZTE 设计、ZTE 筛选、Agent 对话；材料数据库不再提供独立的收藏/材料对比工作区。
3. ECharts 替换 9 个自研 Canvas 绘图器。
4. 统一持久化策略：筛选结果与 Agent 历史纳入持久化（现状刷新即失，但 URL 恢复逻辑 `app.js:3359` 仍假定其存在）。
5. XSS 由 React 默认转义兜底，消除 98 处人工 `escapeHtml`；补充 CSP。

**验收**：后端新旧实现在阶段 0 的响应快照上行为等价（除 P0 修复点外）；前端各工作区功能对齐现状。

### 阶段 4：收尾与发布

1. 改造便携版构建流程：`scripts/build-portable-release.py` 集成 Vite 构建产物。
2. 更新 `README.md` / `README-PORTABLE.md` / `CHANGELOG.md` / `docs/software-registration.md`（软著功能与截图清单）。
3. 版本号升至 1.0.0，标注 Breaking Change。

## 6. 待确认的关键决策

1. **P0-1 物理真值**：全库筛选是否应当补上 Kerner 弹性修正项？补上会使筛选变慢（修正项是逐点向量运算），需评估 185×6701 规模下的性能影响。
2. **P0-2 边界值**：`2.84` 与 `2.84151` 哪个是正式值？
3. **死路由处置**：20 个无前端消费者的端点（`/api/materials/landscape`、`/api/composites/rom`、`/api/agent/tools`、`/structures/alignn-shear` 等）是删除还是保留供 CLI / Agent 使用？
4. **3D 结构**：已采用 Crystal Toolkit；后续可将上传/组合工作区的临时 3Dmol 视图统一迁移到同一组件。
5. **精准计算链路**：`precision/` 依赖 WSL + Conda + MatterSim + VASPKIT + Phonopy 的固定环境。重构时是否保留这条链路，还是改为容器化？

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 领域层重写引入物理回归 | 科研结论错误，后果最严重 | 阶段 0 录制响应快照；阶段 1 补 Kerner 双实现一致性测试；关键公式保留原实现作为对照实现并行验证 |
| 并行重写导致前后端契约漂移 | 集成阶段大量返工 | 阶段 2 契约定稿后再并行，且 TS 类型由 OpenAPI 生成，禁止手写 |
| 便携版发布流程断裂 | 无法交付给用户 | 阶段 4 优先验证，且 Vite 构建产物路径在阶段 3F 即按发布要求约定 |
| 数据迁移出错 | 用户工作库数据丢失 | 迁移器强制备份 + 迁移前校验；`catalog` 只读库不受影响 |
| 工作量超出预期 | 长期半成品状态 | 严格按阶段验收，每阶段结束都保持可运行状态 |
