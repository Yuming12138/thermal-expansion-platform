# 跨平台便携版使用说明

本目录是热膨胀材料智能计算与设计平台的跨平台便携版。材料目录数据库、结构、属性和历史 QHA 曲线已经包含在包内，不依赖开发者电脑上的原始科研目录。

## 运行前准备

需要安装 `uv`。`uv` 会在本目录的 `.runtime/` 中准备 Python 和依赖，不会把平台虚拟环境固定安装到系统盘。安装说明：

<https://docs.astral.sh/uv/getting-started/installation/>

第一次运行需要联网下载 Python/基础依赖。完成一次初始化后，平台环境和缓存保存在本目录中。

## Windows

双击：

```text
start-windows.cmd
```

建议将压缩包解压到较短的目录，例如 `D:\TEP`，避免 Windows 未启用长路径支持时影响 Python 环境初始化。

也可以在 PowerShell 中运行：

```powershell
.\start-windows.ps1
```

## macOS

首次运行可在终端中执行：

```bash
chmod +x start-macos.command start-linux.sh
./start-macos.command
```

如果 macOS 阻止从访达直接打开，可右键 `start-macos.command` 后选择“打开”，或从终端运行上述命令。

## Linux

```bash
chmod +x start-linux.sh
./start-linux.sh
```

平台启动后会打开 <http://127.0.0.1:8000/>。关闭启动终端或按 `Ctrl+C` 即可停止。

## 便携数据位置

```text
var/releases/catalog-v1.sqlite   内置只读材料目录数据库
var/workspace.sqlite             首次启动时创建的个人工作数据库
var/uploads/                     用户上传结构
var/runs/                        计算任务和结果
var/config/agent.env             用户自己的 Agent 配置和密钥
.runtime/                        当前电脑的 Python 环境与依赖缓存
```

复制或移动整个目录即可保留个人工作数据。换到不同操作系统或 CPU 架构时，建议删除 `.runtime/` 后重新启动，让 `uv` 创建匹配新电脑的环境。

## Agent 配置

将 `var/config/agent.env.example` 复制为 `var/config/agent.env`，填写接收者自己的 API 密钥。发布包不包含开发者密钥。

## 功能边界

- 材料查询、历史 QHA 曲线、Fig. 1d、SBR、ZTE 设计和 Agent 数据工具可以使用基础便携环境运行。
- ALIGNN、MatterSim、Phonopy、VASPKIT 和模型权重属于可选科学计算环境，不包含在基础便携包中。
- 精准弹性和 QHA 新计算需要根据接收电脑的操作系统、硬件和模型授权单独配置，或者连接后续的远程计算服务。

需要配置本机计算环境时，将 `var/config/compute.env.example` 复制为 `var/config/compute.env`，再填写 ALIGNN、MatterSim 或 WSL 精准计算环境的位置。基础查询功能不需要该文件。
