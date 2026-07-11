# V0.5.0 集成验证记录

验证日期：2026-07-12。

## 已验证能力

| 能力 | 证据 |
| --- | --- |
| 材料数据库 | HTTP 健康接口返回 6701 条活跃材料、6701 个结构和 160824 个属性值。 |
| Web 与科学工具 | 浏览器中实际验证材料列表、SBR、快速 SBR、ZTE ROM 和受控 Agent；浏览器控制台无错误。 |
| 快速筛选 | BaCrSi4O10 已通过真实 ALIGNN、MatterSim、CrystalNN 和 SBR Worker 运行。 |
| 精确弹性与 QHA | QHA-only 恢复任务 `e54a79c3-fdb0-4752-9ffe-37426a008027` 复用父任务弹性张量，完成 11 个体积点、11 个热力学 YAML 和 Phonopy-QHA 拟合。 |

## 精确任务结果

- 样品：BaCrSi4O10；
- `alpha(300 K) = -26.005501997 ppm/K`；
- 热膨胀曲线：100 个温度点；
- 弹性张量正定，最小本征值为 `21.3956120346 GPa`；
- 质量警告：VASPKIT 报告未应变弹性能非零，且 QHA 检测到虚频。

该任务的虚频使用 Phonopy 的诊断性绝对频率近似生成热性质。因此该 `alpha(T)` 曲线用于平台流程验证和定性分析，不能替代动力学稳定性确认。

## 可重复检查

```powershell
Set-Location 'D:\9.Project\9.NTE&PTE_dataset\14.thermal_expansion_platform'
uv run python -m unittest discover -s tests -v
Invoke-RestMethod http://127.0.0.1:8000/api/precision/jobs/e54a79c3-fdb0-4752-9ffe-37426a008027
```
