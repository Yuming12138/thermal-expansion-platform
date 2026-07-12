# 发布目录数据库说明

## 目的

`catalog-v1.sqlite` 是可随轻量版平台分发的离线科研目录库。接收方不需要拥有原始 JSON、CSV、POSCAR 目录或 `thermal_expansion.dat` 文件，即可完成材料查询、结构查看、热膨胀曲线绘制和 ZTE 复合设计。

SQLite 数据库引擎由 Python/打包程序提供，不要求用户单独安装数据库服务器。

## V1 内容口径

- NTE 数据版本 `nte-candidates-6701-v1-1`：6701 个材料；
- PTE 数据版本 `pte-reference-185-v1`：185 个材料；
- 总计：6886 个材料、6886 个 POSCAR、6886 条历史 QHA 热膨胀曲线；
- 材料属性值：163229 条；
- 不包含开发期失败任务、测试任务、用户任务或复合设计记录。

总数 6886 是 `6701 NTE + 185 PTE`，不是 NTE 数据量发生变化。

## 清理规则

发布构建器会：

1. 使用 SQLite 在线备份从开发库创建一致性快照；
2. 仅保留 `historical_qha_thermal_expansion` 发布曲线任务；
3. 删除开发期精确计算任务和复合设计记录；
4. 将本机绝对路径替换为 `catalog://<release>/<material>/thermal_expansion.dat`；
5. 清理数据版本清单中的绝对来源目录；
6. 执行外键检查、完整性检查和 `VACUUM`；
7. 生成 SHA256 和发布清单文件。

曲线数据点和 POSCAR 内容已经存入 SQLite；`catalog://` 仅用于来源追踪，不是读取原始文件所需的真实路径。

## 构建命令

```powershell
uv run python -m te_platform build-release-catalog `
  --source-db 'var\dev.db' `
  --output 'var\releases\catalog-v1.sqlite' `
  --replace
```

每次正式发布都应保存数据库文件及其同名清单：

```text
catalog-v1.sqlite
catalog-v1.sqlite.manifest.json
```

## 运行边界

当前平台运行时数据库仍需要可写，因为任务系统会保存作业状态。轻量发布包应把内置 `catalog-v1.sqlite` 视为不可变母版，并在首次运行时复制到用户数据目录。下一阶段再将用户上传、计算任务和设计结果彻底拆到独立的 `workspace.sqlite`。

数据库的技术清理完成并不自动等于可以公开分发。正式对外发布前仍需检查数据来源、模型权重和第三方许可证；NTE 数据版本当前保留 `internal_research_pending_rights_review` 分发状态。

## 已完成的离线验证

在不调用原始数据目录的条件下，使用发布数据库的独立运行副本验证了：

- 服务健康检查与 6701 条 NTE 主版本统计；
- 材料名称检索；
- 材料详情和 100 点热膨胀曲线；
- PTE/NTE 真实曲线配对与 100 点 ZTE 混合曲线；
- 发布数据库在验证前后 SHA256 不变。
