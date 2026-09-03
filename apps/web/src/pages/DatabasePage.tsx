import WorkspacePlaceholder from "../components/WorkspacePlaceholder";

export default function DatabasePage() {
  return (
    <WorkspacePlaceholder
      title="材料数据库"
      note="6701 条 NTE 候选与 185 条 PTE 参考的检索、排序与对比入口。"
      scope={[
        { term: "检索与排序", description: "按 G、Ẽ、ξ、CTE 排序；CTE 区间筛选；关键词匹配材料键与化学式。" },
        { term: "元素筛选", description: "周期表点选元素，限定组合必须包含或排除的元素集合。" },
        { term: "收藏对比", description: "最多 4 个材料的持久化收藏，属性表与真实 QHA α(T) 曲线叠加。" },
        { term: "材料详情", description: "数据版本、来源 SHA256、Ẽ 标准公式、POSCAR 与 thermal_expansion.dat 下载。" },
        { term: "分析项目", description: "收藏组合保存为命名项目，导出 CSV、JSON、独立 HTML 与离线 PDF。" },
      ]}
      apiSurface="/api/materials*, /api/datasets/current"
    />
  );
}
