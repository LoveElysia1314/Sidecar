# Legacy 锚点算法归档

`legacy-anchor-v1` 已退出默认生产路径，源码冻结在
`src/dualign/core/legacy_anchor_aligner.py`。它不在 GUI 中提供选择，也不会作为新算法
拒绝后的回退；仅保留 CLI 显式回归和 benchmark：

```powershell
dualign align document-a.md document-b.md --algorithm legacy-anchor-v1
```

其流程为：全文原子余弦矩阵；用绝对最低分和双边 trust margin 递归寻找单调 `1:1`
锚点；锚点间用受限 DP 补赝锚点；枚举连续、恰含一个基准行且跨度有限的 `N:1/1:N`
候选；重编码拼接文本并由最终 DP 选择关系或 gap。

冻结实现包含的主要历史参数是：锚点最低余弦 `0.60`、trust-margin 斜率 `0.10` 与截距
`0.05`、合并跨度上限 `20`、低锚点预检 `0.20`、最大锚点间隙 `50` 和容器上限 `10`。
这些常量在高度平行语料上曾换取很好的速度，但错误锚点会限制后续候选，低信号文档的
拒绝语义也依赖启发式质量指标。

保留它的理由是可复现实验、检查迁移退化和读取旧报告，而不是继续修复。任何 legacy
行为变化都会破坏 benchmark 基线；若发现旧算法优于新算法的案例，应进入新算法的能力
评估或分歧审阅，不应再向冻结模块增加阈值和例外。
