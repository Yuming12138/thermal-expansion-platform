import WorkspacePlaceholder from "../components/WorkspacePlaceholder";

export default function PredictPage() {
  return (
    <WorkspacePlaceholder
      title="结构预测"
      note="上传 CIF/POSCAR 后的三级预测工作台：快速、精准弹性与 QHA。"
      scope={[
        { term: "结构检查", description: "CIF/POSCAR 统一上传，CrystalNN 周期键合图与 3Dmol.js 周期结构显示。" },
        { term: "快速模式", description: "ALIGNN 剪切模量 + MatterSim/CrystalNN Ẽ 的上传结构预筛，带误差区间。" },
        { term: "精准模式", description: "完整弹性张量独立计算并以 Hill G 完成 SBR；正定性与质量门控。" },
        { term: "QHA 模式", description: "独立输出并保存 α(T)；虚频等异常标记为定性结果。" },
        { term: "审批边界", description: "全部计算经 PENDING_APPROVAL 用户确认后启动，任务进度可在工作台轮询。" },
      ]}
      apiSurface="/api/structures/*, /api/precision/*"
    />
  );
}
