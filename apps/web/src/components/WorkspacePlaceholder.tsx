interface ScopeItem {
  term: string;
  description: string;
}

interface WorkspacePlaceholderProps {
  title: string;
  note: string;
  scope: ScopeItem[];
  apiSurface: string;
}

/**
 * 工作区骨架页：如实呈现该工作区的功能范围与接线状态。
 * 刻意不渲染任何伪造数据或假图表——契约定稿后逐项替换为真实实现。
 */
export default function WorkspacePlaceholder({ title, note, scope, apiSurface }: WorkspacePlaceholderProps) {
  return (
    <section className="page">
      <div className="panel">
        <h2>
          {title} <span className="pending-badge">骨架 · 待契约接线</span>
        </h2>
        <p className="panel-note">{note}</p>
        <dl className="workspace-scope">
          {scope.map((item) => (
            <div key={item.term}>
              <dt>{item.term}</dt>
              <dd>{item.description}</dd>
            </div>
          ))}
        </dl>
        <p className="wiring-note">
          <span>
            阻塞于各向异性数据契约定稿（重构方案阶段 2）。目标接口：<code>{apiSurface}</code>
            。契约冻结后由 openapi-typescript 生成类型并替换占位。
          </span>
        </p>
      </div>
    </section>
  );
}
