# ALIGNN快速热膨胀筛选模式

## 用户流程

```text
上传CIF/POSCAR
→ 结构解析和基本质量检查
→ ALIGNN预测剪切模量G
→ MatterSim-5M静态能量计算内聚能
→ CrystalNN计算平均配位数
→ 计算键合模量E_tilde
→ 计算xi=G/E_tilde
→ 返回PTE/NTE快速判断、误差区间和后续建议
```

该模式不进行应变扫描和11体积点QHA，适合作为用户上传结构后的秒级预筛。模型应在独立Worker中常驻，避免每次请求重新加载约48.6 MB权重。

本机实测同一示例POSCAR：CPU回退模式下首次加载模型并预测约`3.45 s`，模型常驻后的第二次完整调用约`0.16 s`，其中神经网络前向推理约`0.11 s`。因此Web服务采用常驻Worker后，可以合理描述为秒级或亚秒级快速预筛。

## ALIGNN模型证据

- 模型：`jv_shear_modulus_gv_alignn`
- 训练目标：`shear_modulus_gv`
- 输出单位：GPa
- 标准化/PCA：未启用
- 测试集：1968条
- MAE：9.476007 GPa
- RMSE：17.796999 GPa
- R2：0.769104
- checkpoint SHA256：`fd967902c3c42da64b7f1ef9258e2c0bdf16765429afea1fb7f0dd4d7e57f2f8`
- config SHA256：`65d2a1a27534a6fdc5554ef6e980b10756e4dd2f7403bd7c7fc55464ec996c79`

由于G预测存在误差，平台会把MAE传播为xi区间。区间跨越`xi_c=2.84`时，不给出强结论，而是进入`boundary_review`，建议计算完整弹性张量和QHA。

## 环境要求

当前Windows基础Python环境不能直接运行该模型：缺少DGL，同时NumPy 2.x与现有Torch/ALIGNN构建不兼容。预测Worker应使用独立锁定环境，至少满足：

- Python 3.10或3.11；
- `numpy<2.0`；
- `torch<=2.2.1`；
- `dgl<=1.1.1`；
- JARVIS-Tools、pymatgen或ASE；
- 本地ALIGNN源码与模型权重均记录SHA256。

当前`alignn` Conda环境已通过真实权重和示例POSCAR验证。该环境的DGL为CPU构建，且旧版Torch不支持当前RTX 5060 Ti的`sm_120`，所以平台会自动回退CPU；这不影响常驻模型后的秒级响应。

## 精确模式升级

用户需要更高可信度时，可将同一结构升级为：

```text
完整弹性张量 → 实际G → 精确SBR → 声子/QHA → alpha(T)
```

快速模式和精确模式必须共用同一个材料ID、结构哈希和任务溯源记录。
