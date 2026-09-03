import WorkspacePlaceholder from "../components/WorkspacePlaceholder";

export default function LandscapePage() {
  return (
    <WorkspacePlaceholder
      title="热膨胀景观"
      note="论文 Fig. 1d 的全库景观视图：G、Ẽ、ξ 与 CTE 的散点关系。"
      scope={[
        { term: "景观散点", description: "全库 6701 条材料的双属性散点，支持框选、悬停详情与跨工作区定位。" },
        { term: "参考基线", description: "内置 Fig. 1d 参考数据（/static/fig1d-reference.json）叠加对照。" },
        { term: "元素统计", description: "按元素统计材料分布，辅助候选方向的快速判断。" },
        { term: "渲染方案", description: "旧版自研 Canvas 由 ECharts canvas 渲染替代，承载全库点数的交互缩放。" },
      ]}
      apiSurface="/api/materials/landscape, /api/materials/elements"
    />
  );
}
