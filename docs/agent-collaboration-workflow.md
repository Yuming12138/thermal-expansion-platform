# Codex–WorkBuddy 协作开发规则

> 这是本项目的固定开发约定。除非用户明确改变它，后续任务都按此流程执行。

## 1. 固定分工

### Codex（主负责人）

Codex 负责需要跨文件判断、物理/数据边界或较高风险的工作：

- 数据契约、SQLite schema、导入/发布目录和后端架构；
- 各向异性数据接入、曲线/弹性张量 provenance、计算流程边界；
- 设计系统、复杂页面布局、跨页面视觉重构和响应式问题；
- 涉及多个模块的功能、性能、兼容性和安全边界；
- 发布打包、远程部署、回滚以及最终集成验收；
- 审核 WorkBuddy 的改动并决定是否合并。

### WorkBuddy（隔离实现者）

WorkBuddy 负责边界清晰、可独立验收的小任务，例如：

- 单个页面的文案、标签、空状态或简单控件调整；
- 单个已有组件的局部 CSS 微调；
- 不改变数据契约的单个按钮/交互修复；
- 配套的局部测试、说明文字或小型兼容性修复。

WorkBuddy 不应自行修改发布数据库、数据选择规则、共享 schema、密钥、部署配置或 Codex 正在编辑的文件，除非任务提示明确授权。

## 2. 任务分流规则

Codex 接到任务后先做只读检查并分流：

- 需要设计判断、跨模块修改、数据/物理语义判断或部署操作：Codex 直接完成；
- 只涉及一个小范围文件、验收标准可写成几条明确断言：给用户一份可直接转发给 WorkBuddy 的 prompt；
- 边界不清或可能影响数据正确性：先由 Codex 澄清/设计，再拆出简单实现。

给 WorkBuddy 的 prompt 必须包含：目标、允许修改的文件、禁止触碰的目录、保持不变的 DOM/API 契约、验收条件、要运行的测试，以及“完成后提交 commit 并返回 hash”。不要只给一句模糊的“把页面改好看”。

## 3. worktree 和合并边界

- Codex worktree：`F:\\1.playground\\2.thremal_expansion_web\\thermal-expansion-platform-codex`，分支 `codex-anisotropic-integration`。
- WorkBuddy worktree：`F:\\1.playground\\2.thremal_expansion_web\\thermal-expansion-platform-ui`，分支 `redesign-sharp-geometric`（如分支名变化，以实际 `git worktree list` 为准）。
- 两个 worktree 不得同时编辑同一文件；尤其不能并行改 `styles.css`、`index.html`、schema 或发布脚本。
- WorkBuddy 完成后只返回 commit hash 和测试结果；Codex 先查看 diff、文件范围和提交祖先，再决定 cherry-pick 或合并，不能盲目复制文件。
- 合并前由 Codex 在自己的 worktree 运行相关测试和浏览器 smoke test；冲突由 Codex 统一解决。
- 生成的截图、缓存、临时数据库和本地密钥不进入提交；发布数据库保持只读，工作区数据库与任务输出分离。

## 4. 数据集和测试的明确边界

- 当前生产候选 release：`nte-candidates-3665-agv2-v2`，版本 `2.0.0`。
- 生产目录包含 3665 个材料、3665 条 Cartesian 曲线、3665 条 directional 曲线；AGV2 与立方对称 QHA 的方法来源必须保留在 provenance 中。
- `tests/catalog_fixture.py` 仍使用仓库内旧的 6701 条轻量测试快照。若测试报“缺少 `nte-candidates-3665-agv2-v2`”，首先判断为测试夹具与当前默认 release 不同步，不得据此断言生产各向异性数据不存在。
- 测试夹具、生产 catalog 和可写的 `workspace.sqlite` 是三个不同边界；测试不得改写生产 catalog。

## 5. 反馈—实现—验收循环

1. 用户在实际预览或远程部署中反馈问题。
2. Codex 复现并判断是复杂架构/样式问题还是简单局部问题。
3. 简单问题由 Codex 生成 WorkBuddy prompt；复杂问题由 Codex 直接修改。
4. 实现完成后检查 diff、DOM/API 契约、关键视口和相关测试。
5. Codex 集成合并并记录 commit；只有验证通过后才更新远程部署。
6. 部署后再次读取 health endpoint 和实际页面，不能以“进程启动”替代可用性验证。

## 6. 当前部署状态（2026-09-04）

- 本地 Codex 预览：`http://127.0.0.1:8127/`，代码来自 Codex worktree，目录库指向本机共享的 3665 release 文件。
- `fuyao` 上的本平台实例：`http://10.10.58.87:8189/`，当前仍是 `nte-candidates-6697-paper-v1`（旧 CSS `0.10.0-13`），不是新的 3665 各向异性版本。
- `fuyao:8104` 和 `fuyao:8100` 是 NTE/PTE Dataset Portal，不应误认为本平台的新部署。
- 下一次部署前必须先打包 3665 catalog 与当前代码，做 release manifest/SHA256 校验，再在 fuyao 上以新端口或明确的可回滚 release 切换；未经用户确认不覆盖旧实例。

## 7. 远程仓库同步规则

- 远程仓库：`https://github.com/Yuming12138/thermal-expansion-platform`（remote 名称 `origin`）。
- 本地 Codex worktree 是开发 source of truth；远端旧提交或旧发布包不自动优先于本地版本。
- 每次同步前先执行只读的 `git fetch origin`、查看目标分支与提交图，并确认要覆盖的确切分支；不得把未核实的远端改动混入数据或代码。
- 用户已允许以本地为准覆盖远端并清理旧内容。实际覆盖仅对明确指定的目标分支使用 `git push --force-with-lease`，保留可追溯的本地 commit；不使用无保护的 `--force`。
- 未明确指定目标分支时，先推送同名审查分支，不改写远端 `main`；需要将本地基线替换远端 `main` 时，再单独确认并记录目标 commit。
- 远端仓库只保存源码、轻量清单和文档；catalog 数据库、密钥、缓存、截图和运行时数据库不上传。发布数据通过版本化 release/manifest 传递并校验 SHA256。
