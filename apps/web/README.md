# Web 前端（React 重构骨架）

热膨胀平台的 React 18 + Vite + TypeScript 前端。技术选型与阶段划分见
[docs/refactor-plan.md](../../docs/refactor-plan.md)。

## 当前状态

**阶段 3F 骨架**：工程配置、设计 tokens、应用外壳与 5 个工作区占位页已就位，
`npm run build` 可通过类型检查与产物构建。业务数据接线**阻塞于各向异性数据契约定稿**
（见 docs/data-contract-audit.md 的阻塞项章节），骨架页如实标注等待状态，不渲染伪造数据。

## 开发

```powershell
# 先启动后端（默认 127.0.0.1:8000）
..\..\scripts\run-web.ps1

# 再起前端 dev server（/api 与 /static 自动代理到后端）
npm install
npm run dev
```

## 命令

| 命令 | 说明 |
|---|---|
| `npm run dev` | 开发服务器，端口 5173，代理 `/api`、`/static` 到 8000 |
| `npm run build` | 类型检查 + 产物构建，输出到 `src/te_platform/web/dist`（便携版打包路径） |
| `npm run typecheck` | 仅类型检查 |
| `npm run preview` | 预览构建产物 |

## 结构

```text
src/
  styles/tokens.css    设计 tokens 三层契约：原始值（继承旧版视觉）→ 语义 → 组件
  styles/app.css       外壳样式，只消费语义层
  lib/api.ts           传输层封装：错误归一 + 超时 + JSON（契约定稿后接入生成类型）
  lib/materialContext  材料上下文：跨工作区保持当前材料，存储键沿用旧版
  components/          AppShell（页头/导航/材料条）、工作区骨架页
  pages/               材料数据库 / 结构预测 / 热膨胀景观 / ZTE 复合设计 / 关于
```

## 设计约束

- 便携版必须离线可用：系统字体栈，不引入外部字体与 CDN。
- 视觉体系继承旧版 `src/te_platform/web/styles.css`（石油蓝绿 accent、冷蓝灰中性色、
  NTE 蓝 / PTE 红语义对），tokens.css 之外的组件禁止写裸色值。
- 图表统一用 ECharts（替代旧版 9 个自研 Canvas 绘图器），3D 结构保留 3Dmol.js。
