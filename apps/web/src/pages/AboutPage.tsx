export default function AboutPage() {
  return (
    <section className="page">
      <div className="panel">
        <h2>关于软件</h2>
        <p className="panel-note">热膨胀材料智能计算、筛选、数据管理与零膨胀设计平台。</p>
        <dl className="workspace-scope">
          <div>
            <dt>当前版本</dt>
            <dd className="data-figure">0.10.0（前端重构骨架 0.1.0）</dd>
          </div>
          <div>
            <dt>判别描述符</dt>
            <dd>
              剪切—键合比 <span className="about-formula">ξ = G / Ẽ</span>
              ，其中 <span className="about-formula">Ẽ = U_V / n</span>
            </dd>
          </div>
          <div>
            <dt>数据规模</dt>
            <dd className="data-figure">6701 条活跃 NTE 候选 · 185 条 PTE 参考（含 0–990 K QHA 曲线）</dd>
          </div>
          <div>
            <dt>科学边界</dt>
            <dd>
              SBR 用于热膨胀符号分类，不等价于精确预测完整 α(T)；ZTE 三模型均为理想两相估算，
              不包含孔隙率、界面反应、织构与微裂纹效应。
            </dd>
          </div>
          <div>
            <dt>数据契约</dt>
            <dd>
              正在向各向异性热膨胀张量迁移（α_V = tr(α) 为旋转不变量，现有标量即此迹）。
              详见 docs/data-contract-audit.md 与 docs/refactor-plan.md。
            </dd>
          </div>
          <div>
            <dt>源码</dt>
            <dd>
              <a href="https://github.com/Yuming12138/thermal-expansion-platform" target="_blank" rel="noreferrer">
                github.com/Yuming12138/thermal-expansion-platform
              </a>
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
