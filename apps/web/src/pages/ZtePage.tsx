import WorkspacePlaceholder from "../components/WorkspacePlaceholder";

export default function ZtePage() {
  return (
    <WorkspacePlaceholder
      title="ZTE 复合设计"
      note="两相复合的零热膨胀设计：温区目标曲线、全库筛选与实验配方。"
      scope={[
        { term: "曲线设计", description: "恒定或分段线性 α_target(T) 的反向设计，ROM / Turner / Kerner 三模型对照。" },
        { term: "全库筛选", description: "185 × 6701 组合统一温度网格评估，工程约束与 Pareto 多目标比较。" },
        { term: "候选详情", description: "两相三维结构、原始 QHA 曲线、三模型曲线叠加与定量对照。" },
        { term: "鲁棒性", description: "配比窗口扫描、温度—浓度二维偏差地图与称量质量换算。" },
        { term: "设计项目", description: "条件、完整排名与已选候选保存到 workspace.sqlite，可跨刷新恢复。" },
      ]}
      apiSurface="/api/composites/*"
    />
  );
}
