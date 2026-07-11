# V1开发路线

## 阶段0：项目与数据基础

- [x] 独立Git仓库
- [x] 6702条候选数据版本清单
- [x] 数据导入与SQLite结构
- [x] SBR和标量ROM核心
- [x] 任务状态与Agent工具白名单骨架

## 阶段1：科学计算引擎

- [x] ALIGNN剪切模量预测适配器与模型溯源
- [x] 快速E_tilde/SBR计算和灰区判断
- [x] 受控外部ALIGNN Worker与上传结构剪切模量预测接口
- [x] MatterSim内聚能与CrystalNN配位数Worker及完整快速SBR接口
- [x] 独立ALIGNN运行环境与受控预测Worker
- [x] MatterSim适配器
- [x] 弹性工作流迁移、实际任务验证与结果解析
- [x] QHA工作流迁移、仅QHA恢复和虚频质量门控
- [x] 受控WSL执行器、日志和位移级进度读取
- [ ] Slurm执行器、通用断点续算和结果哈希

## 阶段2：数据库与复合设计

- [x] 材料查询、详情和G-Ẽ景观API
- [ ] `alpha(T)`、`K(T)`、`G(T)`数据库曲线实体
- [x] ROM温区 `alpha(T)` 优化
- [ ] 修正后的Schapery–HS模型
- [x] 体积分数与质量分数转换

## 阶段3：Web与Agent

- [x] FastAPI服务
- [x] 浏览器材料数据库界面（基础版）
- [x] Web精确任务提交、状态轮询和结果展示
- [ ] 计算结果图表与科研报告导出
- [x] 受控工具调用型Agent
- [ ] PDF/CSV科研报告
