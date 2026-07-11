# 系统架构

平台V1采用模块化单体；耗时计算通过独立Worker执行，暂不拆分微服务。

```mermaid
flowchart LR
    UI["Web界面 / Agent"] --> API["应用服务与受控工具注册"]
    API --> DB["材料数据库与数据版本"]
    API --> JOB["计算任务中心"]
    JOB --> ADAPTER["机器学习势模型适配器"]
    ADAPTER --> ELASTIC["弹性工作流"]
    ADAPTER --> QHA["QHA工作流"]
    DB --> SBR["SBR筛选"]
    DB --> ZTE["NTE/PTE复合与ZTE设计"]
    ELASTIC --> DB
    QHA --> DB
    SBR --> REPORT["报告与结果溯源"]
    ZTE --> REPORT
```

用户上传结构首先进入ALIGNN快速筛选路径：预测`G`，结合MatterSim静态内聚能和CrystalNN配位数计算`E_tilde`，在秒级返回带误差区间的SBR判断。边界材料再升级到完整弹性张量和QHA工作流。

关键边界：

- `PotentialAdapter`只提供能量、力、应力及模型元数据；
- `ElasticWorkflow`和`QHAWorkflow`负责流程编排，不直接绑定MatterSim；
- Agent只能调用注册工具，不能执行任意Shell；
- 数据库同时记录材料事实、数据集版本、计算参数和结果来源；
- 长任务只传递任务ID，工作目录和大文件保存在`var/`或外部对象存储。
