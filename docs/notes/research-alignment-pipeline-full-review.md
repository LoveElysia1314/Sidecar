# 统计门控稀疏 MDL 全量异常审阅

> 归档说明（2026-08-24）：本文是后验重加权版本的逐岛人工证据，不再描述现行主流程；
> 收敛算法改用双模型分歧输出，见 `docs/research-alignment-pipeline.md`。

日期：2026-08-23
状态：隔离研究；未接入生产

## 一、范围与总结果

扫描旧生产报告后，共有 292 个当前正文哈希仍匹配且含异常的文档，覆盖 761 条 `NON_1TO1 / LOW_SCORE / MIX` 异常关系。

新旧路径有 68 个文档不同，形成 99 个最小单调差异岛。逐岛审阅为：修正 50、退化 45、等价 1、无法可靠判断 3。

组合层实际改变 11 个岛：修正 10、退化 1；全语料新增 2163 个组合文本编码。

## 二、门控结论

求解前依次检验文档对应存在性和互惠匹配的顺序一致性。覆盖率仅作为缺失量诊断。顺序异常使用 beta-binomial 链外对模型：正常文档允许不同的背景链外率，避免一两个重复标题或作者名制造远距离 mutual-nearest 后触发误拒。

- 20 个真实平行校准章：顺序拒绝 0/20；
- 20 个真实错配：存在性拒绝 20/20；
- 6 个块乱序：顺序拒绝 6/6；
- 292 个真实异常文档：顺序拒绝 0/292。

这些数字仍复用小规模探索校准集，不能当生产错误率。beta-binomial 还假设文档内链外互惠对在给定潜在错误率后近似二项分布，需要独立大样本检验。

## 三、全流程

1. 全文原子余弦矩阵；
2. 真实错配 conformal null 检验是否存在对应；
3. mutual-nearest 对、加权 LIS 随机化检验及 beta-binomial 链外率检验顺序；
4. 最大加权单调链仅作为无余弦阈值脚手架；
5. 每个脚手架点的相邻中心窗口提交全部局部 Pareto 前沿支持边；
6. 完整语法结构码下的稀疏全局原子 MDL；
7. 只对稀疏 N:1/1:N 候选编码完整块及 leave-one-out 消融；
8. 将组合增益秩转换成归一化条件 bits，再运行同一稀疏全局 MDL。

## 四、差异岛逐项审阅

| 文档/岛 | 区间 | 生产结构 | 新结构 | 判断 | 理由 |
| --- | --- | --- | --- | --- | --- |
| chapters-58524.report.json#1 | [24, 24]→[26, 26] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-58524.report.json#2 | [27, 27]→[29, 29] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-58524.report.json#3 | [30, 30]→[32, 32] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-58524.report.json#4 | [33, 33]→[35, 35] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-59425.report.json#1 | [97, 97]→[99, 99] | 1:2+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-114224.report.json#1 | [314, 313]→[316, 314] | 2:1 | 1:0+1:1 | correction | 正文与译文对应，附加译注没有被翻译；新路径把译注保留为 gap。 |
| chapters-114226.report.json#1 | [57, 57]→[59, 59] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-115539.report.json#1 | [390, 389]→[392, 391] | 1:2+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-123119.report.json#1 | [134, 132]→[136, 133] | 1:1+1:0 | 2:1 | regression | 新路径把未译出的译注或编者说明吸收到相关正文，主题相关不等于被翻译。 |
| chapters-123119.report.json#2 | [194, 191]→[196, 192] | 1:1+1:0 | 2:1 | regression | 新路径把未译出的译注或编者说明吸收到相关正文，主题相关不等于被翻译。 |
| chapters-123119.report.json#3 | [368, 363]→[370, 364] | 1:1+1:0 | 2:1 | regression | 新路径把未译出的译注或编者说明吸收到相关正文，主题相关不等于被翻译。 |
| chapters-123494.report.json#1 | [19, 19]→[22, 21] | 1:1+2:1 | 2:1+1:1 | ambiguous | 首句原本已有直接对应；中间句是否为漏译插句受乱码影响，无法可靠断定新旧哪条更好。 |
| chapters-123497.report.json#1 | [234, 232]→[236, 233] | 2:1 | 1:0+1:1 | correction | 正文与译文对应，附加译注没有被翻译；新路径把译注保留为 gap。 |
| chapters-123503.report.json#1 | [8, 7]→[10, 8] | 2:1 | 1:1+1:0 | regression | 英文包含被拆出的短句、叙述或说话人归属；新路径错误地把该源行改成 gap。 |
| chapters-132720.report.json#1 | [468, 468]→[469, 470] | 1:1+0:1 | 1:2 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| chapters-134955.report.json#1 | [72, 72]→[74, 73] | 1:0+1:1 | 2:1 | regression | 新路径把未译出的译注或编者说明吸收到相关正文，主题相关不等于被翻译。 |
| chapters-134955.report.json#2 | [182, 181]→[184, 182] | 1:1+1:0 | 2:1 | regression | 新路径把未译出的译注或编者说明吸收到相关正文，主题相关不等于被翻译。 |
| chapters-135252.report.json#1 | [349, 346]→[351, 347] | 2:1 | 1:0+1:1 | regression | 英文包含被拆出的短句、叙述或说话人归属；新路径错误地把该源行改成 gap。 |
| chapters-138109.report.json#1 | [73, 73]→[75, 74] | 1:1+1:0 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| chapters-138528.report.json#1 | [57, 57]→[59, 58] | 1:0+1:1 | 2:1 | regression | 新路径把未译出的译注或编者说明吸收到相关正文，主题相关不等于被翻译。 |
| chapters-138529.report.json#1 | [258, 258]→[260, 260] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-143617.report.json#1 | [105, 105]→[108, 108] | 1:0+1:1+1:2 | 1:1+1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-143619.report.json#1 | [122, 122]→[125, 123] | 2:0+1:1 | 3:1 | ambiguous | 目标混合覆盖第一、第三源句而中间问句疑似漏译；当前连续 N:1 语法无法精确表达。 |
| chapters-143619.report.json#2 | [158, 156]→[160, 157] | 1:1+1:0 | 2:1 | regression | 新合并吸收了明确未译出的相邻回应或叙述；旧 gap 更诚实。 |
| chapters-146059.report.json#1 | [69, 65]→[71, 66] | 2:1 | 1:1+1:0 | regression | 英文包含被拆出的短句、叙述或说话人归属；新路径错误地把该源行改成 gap。 |
| chapters-146061.report.json#1 | [22, 22]→[24, 23] | 2:1 | 1:1+1:0 | regression | 英文包含被拆出的短句、叙述或说话人归属；新路径错误地把该源行改成 gap。 |
| chapters-146062.report.json#1 | [76, 76]→[78, 78] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| chapters-146063.report.json#1 | [67, 66]→[69, 67] | 2:1 | 1:1+1:0 | regression | 英文包含被拆出的短句、叙述或说话人归属；新路径错误地把该源行改成 gap。 |
| 37501.report.json#1 | [3, 3]→[6, 4] | 2:0+1:1 | 3:1 | correction | 表单字段由多条源行共同组成一个目标字段；新 N:1 比旧孤行切分完整。 |
| 37502.report.json#1 | [674, 670]→[677, 671] | 1:0+2:1 | 3:1 | correction | 表单字段由多条源行共同组成一个目标字段；新 N:1 比旧孤行切分完整。 |
| 37504.report.json#1 | [216, 215]→[217, 217] | 1:1+0:1 | 1:2 | correction | 单条源行内部包含目标侧拆成多行的完整内容；新 1:N 保持了全部译文。 |
| 37506.report.json#1 | [617, 617]→[618, 619] | 0:1+1:1 | 1:2 | regression | 新 1:N 把分隔符或仅目标侧存在的译注并入源句。 |
| 37506.report.json#2 | [619, 620]→[621, 621] | 1:1+1:0 | 2:1 | correction | 表单字段由多条源行共同组成一个目标字段；新 N:1 比旧孤行切分完整。 |
| 39722.report.json#1 | [318, 318]→[320, 320] | 2:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 46022.report.json#1 | [91, 91]→[93, 92] | 2:1 | 1:1+1:0 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 46022.report.json#2 | [418, 416]→[420, 418] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 46022.report.json#3 | [840, 836]→[842, 837] | 1:0+1:1 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 43559.report.json#1 | [29, 29]→[31, 31] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 44312.report.json#1 | [342, 342]→[344, 344] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 44312.report.json#2 | [364, 363]→[366, 364] | 1:0+1:1 | 2:1 | correction | 表单字段由多条源行共同组成一个目标字段；新 N:1 比旧孤行切分完整。 |
| 44312.report.json#3 | [366, 364]→[368, 365] | 1:0+1:1 | 2:1 | correction | 表单字段由多条源行共同组成一个目标字段；新 N:1 比旧孤行切分完整。 |
| 44405.report.json#1 | [397, 397]→[399, 399] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 46592.report.json#1 | [520, 520]→[522, 522] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 49047.report.json#1 | [205, 204]→[207, 206] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 49137.report.json#1 | [277, 276]→[279, 277] | 2:1 | 1:1+1:0 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#2 | [281, 279]→[283, 280] | 2:1 | 1:1+1:0 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#3 | [295, 290]→[297, 291] | 2:1 | 1:0+1:1 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#4 | [297, 291]→[299, 292] | 2:1 | 1:0+1:1 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#5 | [299, 292]→[302, 294] | 1:1+2:1 | 2:1+1:1 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#6 | [305, 297]→[307, 298] | 2:1 | 1:0+1:1 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#7 | [337, 326]→[339, 327] | 2:1 | 1:0+1:1 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49137.report.json#8 | [415, 398]→[417, 399] | 2:1 | 1:1+1:0 | regression | 目标行同时翻译台词与叙述/说话人归属；新路径拆掉其中一部分或发生局部错位。 |
| 49950.report.json#1 | [604, 603]→[626, 603] | 10:0+10:0+2:0 | 22:0 | equivalent | 两边都把同一连续区域作为 gap，仅连续 gap 的聚合粒度不同。 |
| 52004.report.json#1 | [241, 241]→[243, 243] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 52010.report.json#1 | [70, 68]→[72, 70] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 54253.report.json#1 | [87, 87]→[89, 88] | 1:0+1:1 | 2:1 | correction | 中文名与罗马字名是同一字段的双重表示；合入唯一英文姓名比删除中文名更合理。 |
| 54253.report.json#2 | [97, 96]→[99, 97] | 1:0+1:1 | 2:1 | correction | 中文名与罗马字名是同一字段的双重表示；合入唯一英文姓名比删除中文名更合理。 |
| 55274.report.json#1 | [103, 103]→[105, 104] | 1:0+1:1 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 55274.report.json#2 | [135, 135]→[136, 137] | 1:2 | 1:1+0:1 | correction | 目标侧分隔符、纠错句或译注不是源句译文；新路径将附加目标行独立为 gap。 |
| 60555.report.json#1 | [232, 232]→[233, 234] | 1:2 | 0:1+1:1 | regression | 目标把同一源句拆成声音、续句或引语两行；新路径错误地把其中一行设为 gap。 |
| 64862.report.json#1 | [201, 201]→[203, 202] | 1:1+1:0 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 67551.report.json#1 | [145, 145]→[147, 147] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 68461.report.json#1 | [366, 366]→[368, 368] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 107651.report.json#1 | [898, 898]→[900, 900] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 107651.report.json#2 | [1620, 1619]→[1622, 1620] | 1:1+1:0 | 2:1 | regression | 新合并吸收了明确未译出的相邻回应或叙述；旧 gap 更诚实。 |
| 107651.report.json#3 | [2093, 2090]→[2095, 2091] | 2:1 | 1:0+1:1 | regression | 源文本只是排版换行；新路径丢掉了句首或句尾续行。 |
| 76225.report.json#1 | [316, 316]→[317, 318] | 1:2 | 1:1+0:1 | regression | 目标把同一源句拆成声音、续句或引语两行；新路径错误地把其中一行设为 gap。 |
| 76225.report.json#2 | [402, 403]→[405, 404] | 1:1+2:0 | 3:1 | regression | 新合并吸收了明确未译出的相邻回应或叙述；旧 gap 更诚实。 |
| 76225.report.json#3 | [909, 907]→[911, 909] | 1:0+1:2 | 1:1+1:1 | regression | 新路径发生语义错位：相邻行与错误的目标句/译注配对。 |
| 85835.report.json#1 | [6, 6]→[8, 7] | 1:1+1:0 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 95004.report.json#1 | [148, 148]→[151, 151] | 2:1+1:1+0:1 | 1:1+1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 95004.report.json#2 | [169, 169]→[171, 171] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 103226.report.json#1 | [144, 144]→[146, 146] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 103226.report.json#2 | [199, 199]→[200, 201] | 1:1+0:1 | 1:2 | regression | 新 1:N 把分隔符或仅目标侧存在的译注并入源句。 |
| 103233.report.json#1 | [221, 222]→[222, 224] | 1:1+0:1 | 1:2 | regression | 新 1:N 把分隔符或仅目标侧存在的译注并入源句。 |
| 103237.report.json#1 | [305, 305]→[308, 308] | 1:0+1:1+1:1+0:1 | 1:1+1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 110129.report.json#1 | [273, 273]→[275, 275] | 2:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 110135.report.json#1 | [80, 80]→[81, 82] | 1:1+0:1 | 1:2 | regression | 新 1:N 把分隔符或仅目标侧存在的译注并入源句。 |
| 110188.report.json#1 | [377, 374]→[379, 376] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 110188.report.json#2 | [389, 386]→[391, 388] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 110193.report.json#1 | [6, 6]→[8, 7] | 1:1+1:0 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 110304.report.json#1 | [98, 98]→[99, 100] | 1:1+0:1 | 1:2 | correction | 单条源行内部包含目标侧拆成多行的完整内容；新 1:N 保持了全部译文。 |
| 131705.report.json#1 | [9, 9]→[10, 12] | 0:1+1:2 | 0:2+1:1 | correction | 目标侧分隔符、纠错句或译注不是源句译文；新路径将附加目标行独立为 gap。 |
| 131705.report.json#2 | [215, 218]→[216, 220] | 0:1+1:1 | 1:2 | regression | 新 1:N 把分隔符或仅目标侧存在的译注并入源句。 |
| 131707.report.json#1 | [372, 372]→[373, 374] | 1:2 | 1:1+0:1 | regression | 目标把同一源句拆成声音、续句或引语两行；新路径错误地把其中一行设为 gap。 |
| 131713.report.json#1 | [384, 384]→[386, 385] | 1:0+1:1 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 115160.report.json#1 | [39, 39]→[41, 41] | 0:1+1:1+1:0 | 1:1+1:1 | regression | 新路径发生语义错位：相邻行与错误的目标句/译注配对。 |
| 115160.report.json#2 | [198, 199]→[199, 201] | 1:2 | 1:1+0:1 | correction | 目标侧分隔符、纠错句或译注不是源句译文；新路径将附加目标行独立为 gap。 |
| 115162.report.json#1 | [6, 6]→[8, 8] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 115162.report.json#2 | [13, 13]→[15, 15] | 1:0+1:1+0:1 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 117095.report.json#1 | [113, 113]→[115, 114] | 2:1 | 1:1+1:0 | correction | 正文与译文对应，附加译注没有被翻译；新路径把译注保留为 gap。 |
| 126203.report.json#1 | [458, 457]→[460, 459] | 0:1+1:1+1:0 | 1:1+1:1 | correction | 相邻短台词的数量和顺序一一对应；新路径消除了旧路径的成对孤行或偏移。 |
| 127904.report.json#1 | [0, 0]→[1, 2] | 1:1+0:1 | 1:2 | correction | 单条源行内部包含目标侧拆成多行的完整内容；新 1:N 保持了全部译文。 |
| 127908.report.json#1 | [148, 146]→[150, 147] | 1:1+1:0 | 2:1 | correction | 单条源行内部包含目标侧拆成多行的完整内容；新 1:N 保持了全部译文。 |
| 130648.report.json#1 | [209, 209]→[211, 210] | 1:1+1:0 | 2:1 | correction | 源句被排版硬换行；新 2:1 恢复了完整句子。 |
| 147106.report.json#1 | [99, 99]→[101, 100] | 1:0+1:1 | 2:1 | ambiguous | 两个极短否定/应答只有一个目标句，文本含疑似错字，无法确认是合理合并还是漏译。 |
| 147724.report.json#1 | [254, 254]→[256, 255] | 2:1 | 1:1+1:0 | regression | 源文本只是排版换行；新路径丢掉了句首或句尾续行。 |
| 174914.report.json#1 | [149, 149]→[151, 150] | 1:0+1:1 | 2:1 | regression | 新增合并吸收了同主题但没有出现在目标文本中的相邻句。 |
| 157947.report.json#1 | [91, 91]→[93, 92] | 2:1 | 1:1+1:0 | regression | 源文本只是排版换行；新路径丢掉了句首或句尾续行。 |

## 五、旧异常关系逐条状态

`preserved_nonstructural` 表示结构未变且异常属于文本质量；`preserved_structure` 表示新旧都选择同一非 1:1。差异岛内异常继承上表人工判断。

| # | 报告:位置 | 类型 | 关系 | 对照 | 审阅 | 原文摘录 | 译文摘录 |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | chapters-58497.report.json:357 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我猜，那家伙八成正气得火冒三丈吧。 | I bet she's absolutely furious right now. |
| 2 | chapters-58498.report.json:9 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「你这不就大意了吗？」 | "Well, that's what you get for letting your guard down." |
| 3 | chapters-58500.report.json:645 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不过，要说没办法也是没办法。 | But there's no helping it. |
| 4 | chapters-37910.report.json:16 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 烦死了，别用「彼氏」称呼我。假如我是女的，你会改叫「彼女氏」吗？（注：日文中会以彼氏／彼女称呼男女朋友。另外，日本社会的笼统观念中，是认为御宅… | Shut up, don't call me "boyfriend." If I were a girl, would you call me… |
| 5 | chapters-39033.report.json:194 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 倒不如说，学姊这样不太妙…… | Rather, Senpai was in a dangerous state... |
| 6 | chapters-58504.report.json:168 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「呃，我看还是不太好吧？」 | "Well, I don't think that's such a good idea..." |
| 7 | chapters-58511.report.json:152 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 倒不如说，反而更…… | If anything, she felt even closer... |
| 8 | chapters-55193.report.json:217 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 接下来就差原画，等于十拿九稳。 | All that's left is the key art, so it's basically in the bag. |
| 9 | chapters-55195.report.json:45 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 那家伙说了没问题就不会有问题。 | If she says she's fine, then she's fine. |
| 10 | chapters-55198.report.json:87 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 好，这样我们就互不相欠。 | There. Now we're even. |
| 11 | chapters-55199.report.json:62 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 明明我捅了让社团随时瓦解都不奇怪的大楼子。 | Even though I'd caused a blunder big enough that the circle could have … |
| 12 | chapters-58519.report.json:143 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 御宅黄门　　作词：安艺伦也 | Otaku Pilgrimage　　Lyrics: Tomoya Aki |
| 13 | chapters-55207.report.json:261 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 话说学姊，你现在才讲太诈了啦。 | Senpai, it's not fair to drop this on me now. |
| 14 | chapters-55209.report.json:237 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不方便的话再跟我连络。 | Let me know if that doesn't work for you. |
| 15 | chapters-55804.report.json:54 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “讨厌，不是吧。。。“ | "Oh no, you're kidding..." |
| 16 | chapters-85135.report.json:1 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 翻译： Jc丶X | Translation: Jc丶X |
| 17 | chapters-81501.report.json:1 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 翻译： Jc丶X | Translation: Jc丶X |
| 18 | chapters-81503.report.json:48 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | “怎么样？认罪吗？愿意承认自己装纯骗男人的绿茶婊的本性了吗？如果愿意承认，这一次就在你的大腿内侧用油性笔写上五个‘正’字饶过你吧。” | "Well? Will you confess? Will you admit to your true nature as a sly bi… |
| 19 | chapters-81503.report.json:99 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | ……现在，在刚刚完成的诗羽肖像画（姿势和服装说明略）上，英梨梨正拼命往大腿和腹部上添加大量的“正字”，并画上了指向某个部位的箭头，还注上了“请… | ...Now, on the just-completed portrait of Utaha (pose and outfit descri… |
| 20 | chapters-51251.report.json:600 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「给我适可而止红坂……」 | "That's enough, Kosaka!" |
| 21 | chapters-58524.report.json:24 | NON_1TO1 | 1:0 | realigned | correction | 安艺伦也 |  |
| 22 | chapters-58524.report.json:26 | NON_1TO1 | 0:1 | realigned | correction |  | Tomoya Aki |
| 23 | chapters-58524.report.json:28 | NON_1TO1 | 1:0 | realigned | correction | 加藤惠 |  |
| 24 | chapters-58524.report.json:30 | NON_1TO1 | 0:1 | realigned | correction |  | Megumi Kato |
| 25 | chapters-58524.report.json:32 | NON_1TO1 | 1:0 | realigned | correction | 波岛出海 |  |
| 26 | chapters-58524.report.json:34 | NON_1TO1 | 0:1 | realigned | correction |  | Izumi Hashima |
| 27 | chapters-58524.report.json:36 | NON_1TO1 | 1:0 | realigned | correction | 冰堂美智留 |  |
| 28 | chapters-58524.report.json:38 | NON_1TO1 | 0:1 | realigned | correction |  | Michiru Hyodo |
| 29 | chapters-58525.report.json:127 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「那、那个，伦也。」 | Th-That, Tomoya. |
| 30 | chapters-58525.report.json:143 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「就、就是说啊，彼此彼此喽。」 | "Th-That's right... it takes two to tango." |
| 31 | chapters-58526.report.json:94 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「学姊是指……」 | "What do you mean, senpai?" |
| 32 | chapters-58533.report.json:215 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 老套得令人傻眼。 | So cliché it was almost ridiculous. |
| 33 | chapters-59425.report.json:97 | NON_1TO1 | 1:2 | realigned | correction | 【你有什么资格说我。。。】 | [You're one to talk...] / [I have every right to~] |
| 34 | chapters-59425.report.json:98 | NON_1TO1 | 1:0 | realigned | correction | 【有，当然有~】 |  |
| 35 | chapters-59426.report.json:11 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 【不好意思，先喝上了】 | "Sorry, I've gone ahead and started without you." |
| 36 | chapters-59426.report.json:29 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 在不死川书店这一相当有名的出版社中，任职不死川FANTASTIC文库这一轻小说程度的副编辑长，名副其实的工作狂（死语）式的CAREER WOM… | At the fairly well-known publishing house Fujigawa Books, she held the … |
| 37 | chapters-59426.report.json:181 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 【嘛，才能的话是的…人的话先不说】 | "Well, in terms of talent, yes... As for the person herself, that's ano… |
| 38 | chapters-59427.report.json:183 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 【那再见呐】 | "Well, see you then." |
| 39 | chapters-59430.report.json:254 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 同时，致现在仍在相同道路上奔驰的，【新友】们。（【旧友】，【新友】原文中其实是同音梗，原文为【友】和【トモ】发音是一样的，翻译采取【旧友】【新… | And at the same time, to her [new friends], who were still racing down … |
| 40 | chapters-59430.report.json:270 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 【Icy Tail Yo（阿姨洗铁路）（这里也是同音梗，Icy Tail Yo的日文发音和【愛してるよ】发音相近，这里丸户揭开了【icy ta… | \[Icy Tail Yo (Aishiteru yo) (This is also a pun—the Japanese pronuncia… |
| 41 | chapters-76751.report.json:83 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “我说阿苑啊。” | "Hey, Sonoko." |
| 42 | chapters-91438.report.json:5 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 扫图：Jc丶X | Scanner: Jc丶X |
| 43 | chapters-91439.report.json:1 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 扫图：Jc丶X | Scan: Jc丶X |
| 44 | chapters-114222.report.json:10 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 这难道是什么杀人案件的导入吗?我在心里这么吐槽道。 / 老爸用他充满热情的声音，摆出了一副跟希独睾演讲时一模一样的姿势说道。 | I couldn't help but wonder if this was the opening scene of some murder… |
| 45 | chapters-114222.report.json:77 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “你可拉jb倒吧。” | "That's the dumbest thing I've ever heard." |
| 46 | chapters-114224.report.json:53 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | “对不起，既然你都这么说了。” |  |
| 47 | chapters-114224.report.json:249 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 回头一看，原来是读卖前辈。 | When I turned around, it was Senpai Yomi. |
| 48 | chapters-114224.report.json:314 | NON_1TO1 | 2:1 | realigned | correction | 具体内容概括起来就是这样的。 / 从形迹可疑的我的行动来看，她推测到了我在房前做了什么，她似乎在怀疑我是不是在观察晾在室内的内衣。虽然她认为内… | The gist of it was this: from my suspicious behavior, she'd deduced wha… |
| 49 | chapters-114226.report.json:36 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 是啊，像那样说真的好吗? | Yeah, I guess that's fair. |
| 50 | chapters-114226.report.json:57 | NON_1TO1 | 0:1 | realigned | correction |  | "Sure, whenever you have time." |
| 51 | chapters-114226.report.json:59 | NON_1TO1 | 1:0 | realigned | correction | “嗯，所以等有空的时候再说吧。” |  |
| 52 | chapters-115538.report.json:381 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不由得这样嘟囔着。 | I couldn't help muttering. |
| 53 | chapters-115539.report.json:32 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「今年的夏天好像也很热呢。」 / 犹豫了半天，我还是做出了稳妥的回答。 | "The summer seems like it's going to be hot again this year," I said, s… |
| 54 | chapters-115539.report.json:115 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 读卖栞前辈。 | Yomiuri Senpai. |
| 55 | chapters-115539.report.json:306 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「原本是要留给后辈的啊。」 | "I was saving some for you, kouhai." |
| 56 | chapters-115539.report.json:389 | NON_1TO1 | 1:2 | realigned | correction | 「……这是必须要说的话吗？」 | "...Is it something that can't wait?" / "Yes. It's something I need to … |
| 57 | chapters-115539.report.json:390 | NON_1TO1 | 1:0 | realigned | correction | 「是的。我想说的是」 |  |
| 58 | chapters-115540.report.json:96 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 然后我故弄玄虚地说。 | I paused for dramatic effect. |
| 59 | chapters-115540.report.json:260 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 什么啊，真闲啊。 | What the hell, they had that much free time? |
| 60 | chapters-115542.report.json:44 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 我不想后悔。如果事后只会让自己出丑的话，那样就好。 |  |
| 61 | chapters-122579.report.json:2 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 润色：黑玉 ,Accelerator | Polish: 黑玉, Accelerator |
| 62 | chapters-122581.report.json:194 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 绫濑的话是谎言——虽然不至于这样说，但是我还是感觉有点奇怪。她回到她自己的房间后，我也稍微思考了一下那种模糊不清的感觉的真面目。然后我突然意识… | It wasn't that Shiori's words were a lie—but still, something felt off.… |
| 63 | chapters-122582.report.json:194 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “你这家伙，果然和绫濑有些什么吧？” | "You've definitely got something going on with her, don't you?" |
| 64 | chapters-122582.report.json:294 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 前辈这个人，真是难懂啊。 | Senpai really is hard to read. |
| 65 | chapters-123116.report.json:10 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 也就是说她已经起床了。 / 果然还是闷在房间里了吗，她是在学习还是在打扫呢？ | So she was up after all. Still holed up in her room, huh—was she studyi… |
| 66 | chapters-123117.report.json:307 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 算是来者不拒。 | I just wasn't turning anyone away if they came to me. |
| 67 | chapters-123119.report.json:13 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 话虽如此，但奈良坂已经知道了。嘛，就算是暴露了也不会困扰，所以我也好，绫濑也好，都没有想过去干堵她的嘴之类的事。 | That said, Nara坂 already knew. Well, even if it got out, it wouldn’t ca… |
| 68 | chapters-123119.report.json:18 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「感觉好怪。」 / 我嘀咕了一句。 | “This is weird,” I muttered. |
| 69 | chapters-123119.report.json:20 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 没错，在那之后奈良坂用LINE发了追加的指令。必须穿制服，带学生包，一定不能忘记带学生证——她这样严命了。说是学生打折的话，只带学生证不就行了？ | Right, after that, Nara坂 had sent additional instructions via LINE. We … |
| 70 | chapters-123119.report.json:25 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 嘛，能称之为绫濑朋友的就这样奈良坂吧。 | Well, I guess Nara坂 was about the closest thing Ayase had to a friend. |
| 71 | chapters-123119.report.json:26 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 真不愧是水星高中交流力第一的奈良坂（我封的），奈良坂一看见我就像伸展身体一样挥舞着手。身材娇小的她，像这样最大限度地伸展身体的姿态，让人联想到… | Sure enough, Nara坂—the undisputed queen of social skills at Suisei High… |
| 72 | chapters-123119.report.json:34 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 为了不妨碍从验票口涌出的人潮，全员简单地做了自我介绍。每个人做简单的自我介绍报上姓名时，奈良坂都会插嘴,所以实际上花了不少时间也没办法。 | So as not to block the flow of people streaming out of the ticket gates… |
| 73 | chapters-123119.report.json:40 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 大家都笑了。用玩笑来活跃气氛，这就是奈良坂特殊的交流技巧吧。 | Everyone laughed. Lightening the mood with jokes—that was Nara坂’s speci… |
| 74 | chapters-123119.report.json:45 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我不由得吓了一跳。反应迟钝和动作僵硬并不是被他巨大的体格吓到，而是明明是第一次见面却直呼其名。难道说这也是奈良坂活跃空气的效果吗。 | I couldn’t help but flinch. It wasn’t because of his massive build or m… |
| 75 | chapters-123119.report.json:51 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 不只是我，其他人自我介绍时奈良坂也会配合他们说些无聊的俏皮话或者像强调名字特征的傻话，所以就连不怎么记得住别人名字的我也能对在场的人的名字和性… | Not just me—whenever anyone introduced themselves, Nara坂 would add a si… |
| 76 | chapters-123119.report.json:52 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂真绫真是可敬。 | Nara坂 Masayo was genuinely impressive. |
| 77 | chapters-123119.report.json:60 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「所以奈良坂，为什么要穿制服？」 | “So Nara坂, why the uniforms?” |
| 78 | chapters-123119.report.json:69 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂这个人，好像比想象中更体贴。 | Nara坂, that woman, was more considerate than I’d expected. |
| 79 | chapters-123119.report.json:70 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 恐怕今天的学生中有些父母的教导很严格，必须通过说谎才能出来玩的人也有吧。比如说参加学校委员会的工作，准备校园开放日什么的，说了这种慌。事先和那… | Some of today’s students probably had strict parents and had to lie to … |
| 80 | chapters-123119.report.json:71 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂再次让我见识到了人类交流能力的极限。 | Nara坂 had once again shown me the limits of human social capability. |
| 81 | chapters-123119.report.json:73 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 领悟了高度调整能力的奈良坂站在队伍排头，以换乘的民营铁路检票口为目标朝气蓬勃地迈出了脚步。 | Nara坂, having grasped the art of adjustment, took the lead and strode e… |
| 82 | chapters-123119.report.json:74 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 好了，在奈良坂老师的率领下，我们创造了暑假的回忆——远足开始了。 | And so, under Teacher Nara坂’s command, we set off to create our summer … |
| 83 | chapters-123119.report.json:78 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 因为奈良坂邀请而聚集起来的，算上我，绫濑和奈良坂，男女共10人。男生和女生正好都是5人。也就是说，和我初次见面的有7人。 | Counting me, Ayase, and Nara坂, there were ten of us in total, boys and … |
| 84 | chapters-123119.report.json:99 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 听到年了吧这么说后，我把看到这些东西后的感想坦率地说了出口。 | When Nara坂 said that, I gave my honest impression of what I saw. |
| 85 | chapters-123119.report.json:109 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 身旁的田端由美（好像确实是这个名字，奈良坂介绍时说过和山手线的站名发音一样）同学听到绫濑的话后瞪大了眼睛。 | The girl beside her, Tabata Yumi (I think that was her name—Nara坂 had s… |
| 86 | chapters-123119.report.json:116 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | （译注：縁日即有庙会的日子。） |  |
| 87 | chapters-123119.report.json:132 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂穿这露出度很高的比基尼，柠檬色的分体式泳装与她活泼开朗的性格很般配。但她娇小的身材和幼稚的行为和想象中比基尼的煽情相去甚远，说成可爱会更… | Nara坂 was in a high-exposure bikini—a lemon-colored two-piece that suit… |
| 88 | chapters-123119.report.json:134 | NON_1TO1 | 1:0 | realigned | regression | （译注：坦基尼，两件套泳装，包括无袖短上衣和比基尼下裤。） |  |
| 89 | chapters-123119.report.json:148 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 在我准备吐出进一步反驳的言语时，奈良坂插话了。 | Just as I was about to voice further objections, Nara坂 cut in. |
| 90 | chapters-123119.report.json:152 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 这样说着，奈良坂在原本就竖起的食指旁再添上中指，做出双指插眼的动作。真凶残啊，奈良坂。 | With that, Nara坂 added her middle finger beside her already-raised inde… |
| 91 | chapters-123119.report.json:160 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂再次发出了将冰冷的空气炒热般的宣言。 | Nara坂 declared again, as if reheating the chilled air. |
| 92 | chapters-123119.report.json:162 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂指着水上滑梯。 | Nara坂 pointed at the waterslide. |
| 93 | chapters-123119.report.json:164 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 根据奈良坂制作的《创造美好夏日回忆的计划表》上所写的内容，整个早上大家都会以游乐设施为中心来回移动。 | According to the “Plan for Creating Wonderful Summer Memories” that Nar… |
| 94 | chapters-123119.report.json:166 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我一边玩，一边回想起预定表写的日程安排。我对奈良坂的考虑赞叹不已。 | As I played, I thought back to the schedule written on the plan. I was … |
| 95 | chapters-123119.report.json:170 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 只是，这种情况下就算是就读高中相同的同级生，班级和性别不同的十人，关系也不可能突然变得很好。更何况像奈良坂这样交友广泛的人还交了各种各样的朋友。 | But even so, with ten people of different classes and genders from the … |
| 96 | chapters-123119.report.json:173 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 那一点奈良坂也考虑到了吧。 | Nara坂 had probably thought about that too. |
| 97 | chapters-123119.report.json:177 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 所以，作为出门游玩的一介普通高中生，她计划将集体活动的顺序往后推，先让大家去玩了必玩的游乐设施。根据奈良坂的企划，午后还有男女混合的活动。 | So, as any ordinary high schooler organizing a day out, she’d planned t… |
| 98 | chapters-123119.report.json:180 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 12点过后，我们看准公共座位空着的时机，决定开始吃午餐。看着随心所欲地聊早上的事件并欢笑着的大家，可以说奈良坂的目的漂亮地达成了。 | After noon, we grabbed a spot at the public seating area and decided to… |
| 99 | chapters-123119.report.json:188 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 大家都像小学生一样充满元气地回应了奈良坂。虽然有些平静、但是张开嘴轻声回应的绫濑很有趣。 | Everyone responded to Nara坂 with all the energy of elementary schoolers… |
| 100 | chapters-123119.report.json:190 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我不知道浮板Otheello是不是正式的名称，说不准这是奈良坂自己命名的。那是个规则很简单的游戏。 | I didn’t know if “float boat Othello” was the official name—it might’ve… |
| 101 | chapters-123119.report.json:194 | NON_1TO1 | 1:0 | realigned | regression | （译注： berulla 是一种猜拳游戏,用于把很多人分为两组,分组时只出石头和布，相同的手形的人一组。） |  |
| 102 | chapters-123119.report.json:197 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我偶然和绫濑在同一组。奈良坂在敌对阵营。 | By chance, I ended up on the same team as Ayase. Nara坂 was on the oppos… |
| 103 | chapters-123119.report.json:202 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂一边说着「像这样做」，一边演示了将浮板在水上推出，迅速拉开距离的方法。 | Nara坂 demonstrated—she pushed her board across the water and quickly pu… |
| 104 | chapters-123119.report.json:207 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂将设好计时器的手机放进防水手机套。在她宣告比赛开始后，我们在泳池的边缘开始了游戏。 | Nara坂 put her phone, timer set, into a waterproof pouch. With her call … |
| 105 | chapters-123119.report.json:210 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂的手机流出了时长3分钟的轻快旋律。 | Nara坂’s phone played a cheerful three-minute melody. |
| 106 | chapters-123119.report.json:212 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 大家随着奈良坂的号令一齐停下了移动。 | At Nara坂’s call, everyone stopped moving at once. |
| 107 | chapters-123119.report.json:216 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 好像再次设置完手机计时器的奈良坂这样说道。 | Nara坂, having apparently set her phone’s timer again, said. |
| 108 | chapters-123119.report.json:218 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 话说回来……虽然好像谁都没注意到，但奈良坂计时器设置的音源，那个是动漫的op吧。要问我为什么注意到了那点的话，这部动漫在第一季完结之前丸就安利… | That said… though nobody seemed to notice, the sound Nara坂’s timer play… |
| 109 | chapters-123119.report.json:222 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 奈良坂说完，我精疲力尽地坐到游泳池边。 | When Nara坂 finished, I flopped down exhausted at the pool’s edge. |
| 110 | chapters-123119.report.json:335 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | （译注：出自《你的名字》。） |  |
| 111 | chapters-123119.report.json:341 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「和真绫的关系变得很好了呢」 | "You've gotten close with Maya, haven't you?" |
| 112 | chapters-123119.report.json:368 | NON_1TO1 | 1:0 | realigned | regression | //译注:黑箱，控制论中指一种既不能打开又不能从外部窥视其中奥秘的信息系统。常以比喻难以了解其内情的事物。 |  |
| 113 | chapters-123494.report.json:20 | NON_1TO1 | 2:1 | realigned | ambiguous | （苦虫：嚼时发苦的一种想象中的虫子） / “苦虫?不巧我没嚼过。” | "I don't know what 'bitter' tastes like. Never bitten into anything lik… |
| 114 | chapters-123494.report.json:236 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 一边说着其他无关痛痒的话题，一边洗着两个人的碗。量少，也用不着洗碗器，但我总觉得很想这么做。或者，绫濑也是吗? |  |
| 115 | chapters-123495.report.json:56 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “还好吧?” | "I made it." |
| 116 | chapters-123495.report.json:146 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 一片混乱。 | My mind was spinning. |
| 117 | chapters-123497.report.json:43 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | “嗯，女性除了各种各样的事情之外，挑战一下平时不怎么做的新事情也能分散注意力，不是很好吗?” / 丸对呆呆地思考着的我说。 | "Besides women, trying something new you don't usually do could be good… |
| 118 | chapters-123497.report.json:191 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | （日本女性有以摘花代指上厕所的说法） |  |
| 119 | chapters-123497.report.json:233 | NON_1TO1 | 2:1 | realigned | correction | （日式发音中sail和sell谐音） / 她弯着高高的背鞠了一躬:“请多关照。” | She bent her tall frame into a bow. "Nice to meet you." |
| 120 | chapters-123498.report.json:9 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 根据昨天晚上和绫濑的谈话，把我和绫濑的面谈日期定在一起，所以告诉亚季子休息一天就可以了。 / 所以老爸说不用请假也没关系。 | Based on last night's conversation with Ayase, we'd coordinated the dat… |
| 121 | chapters-123498.report.json:16 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 对我来说，小时候姑且不论，到了十七岁，父母再婚，就会认为是父亲有了妻子，但不会认为是有了新的母亲。 / 老爸和亚季子似乎都有这种感觉，老爸又补… | For me—well, setting aside my childhood, at seventeen, when your parent… |
| 122 | chapters-123498.report.json:20 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 被这么一说，我明白了。亚季子小姐并不是因为被赋予了保护我的职责才想当母亲的。 / 从立场上来说，是义理的母亲和儿子，但不是这样的，而是父亲、亚… | Put that way, I understood. Akiko didn't want to be my mother because s… |
| 123 | chapters-123498.report.json:108 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 她对周围的态度变得柔和，在之前一直认为绫濑是不良学生而害怕她的男生之间人气直线上升。因为她不再是孤高的存在，所以主动搭讪、接近她的男生越来越多… | Her attitude toward those around her softened, and her popularity among… |
| 124 | chapters-123498.report.json:188 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 听了前辈安慰似的话，我“诶?”她歪着头看着我的脸。 / “什么意思?” | I tilted my head at the sympathy in her voice. "What do you mean?" |
| 125 | chapters-123500.report.json:68 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “啊，又来了!” | "Oh, you're already going?" |
| 126 | chapters-123500.report.json:193 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我觉得三方面谈不需要什么努力的要素……算了吧。 | I doubted a parent-teacher-student conference required "doing your best… |
| 127 | chapters-123500.report.json:232 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “三方面谈，加油!” | "Good luck with your conference!" |
| 128 | chapters-123502.report.json:106 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 读卖前辈嘟囔了一声。 | Yomiuri-senpai muttered. |
| 129 | chapters-123502.report.json:198 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 说起来也是。 | Now that she mentioned it. |
| 130 | chapters-123502.report.json:310 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 报了一箭之仇吗? | Did she just get me back for that? |
| 131 | chapters-123503.report.json:4 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | （表参道： 表参道商业街—东京最为繁华的商业街之一,总长不过1000米左右,与原宿、涉谷、代官山一起形成东京四个最具特色、风格不同的时装店聚集… |  |
| 132 | chapters-123503.report.json:8 | NON_1TO1 | 2:1 | realigned | regression | 暑期补习结束后的实力测试成绩明显提高了，好不容易才想就这样正式去上学，这样对父母说过。 / 我没有说谎。 | My scores on the placement test after the summer intensive course had i… |
| 133 | chapters-123503.report.json:73 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 所以你以为我也是来搭讪的吗? | So that's why she thought I was hitting on her. |
| 134 | chapters-123504.report.json:383 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 真是没办法啊，藤波叹着气笑了。 | Fujinami let out a rueful laugh, as if there was nothing to be done. |
| 135 | chapters-123506.report.json:119 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 穿好鞋子的绫濑站起身，一动不动。 | She finished putting them on and stood still. |
| 136 | chapters-123506.report.json:126 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 但在那之前，绫濑突然转过身，胡乱地脱下刚穿好的鞋子，拉起我的手，我被那纤细手腕意想不到的力量拉住。 / 被绫濑突然的强硬举止吓了一跳，我被拉到… | But before I could, Ayase spun around abruptly, kicked off the shoes sh… |
| 137 | chapters-128239.report.json:16 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 和奈良坂同学关系好的是绫濑同学。 | The one she's close with is Ayase. |
| 138 | chapters-128239.report.json:214 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 说起来，刚才新庄同学好像是用，友和，称呼丸的来着。 | Come to think of it, Shinjo had called Maru "Tomokazu." |
| 139 | chapters-128239.report.json:391 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 需要注意的是，只剩下一两本的书得从平放换成插入书架中。（译：平放（平置き）：常去书店的大火应该经常见到，一部分希望吸引顾客注意的热销书或者新出… | One thing to watch out for: books that had only one or two copies left … |
| 140 | chapters-128239.report.json:429 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 茅塞顿开。 | A light bulb went off. |
| 141 | chapters-128240.report.json:21 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 更加怎样都好的一句话。 | That's even less of a concern. |
| 142 | chapters-128240.report.json:72 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 真绫狐疑着说道。 | Maya spoke with a knowing air. |
| 143 | chapters-128241.report.json:4 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我在烦恼的是，该怎样才能约会成功。 / 虽然没有自信说能让她共处的时候感到开心，但至少不想让气氛无聊。 | What I was agonizing over was how to make the date a success. I couldn'… |
| 144 | chapters-128241.report.json:29 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我想起昨天的绫濑同学。 / 正因为看到了她睡过头后迷迷糊糊的样子，我才真正体会到她平时全副武装的样子有多厉害。 | I recalled Ayase from yesterday. It was precisely because I'd seen her … |
| 145 | chapters-128241.report.json:188 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 大概是面向女性的商场中，不仅有我模糊想象中的『真·动漫周边』之类的商品，还有自己喜欢的角色所属的学生宿舍舍章为主题的钥匙扣和笔记本之类的。 /… | In the section aimed at women, there wasn't just the "full-on anime mer… |
| 146 | chapters-128242.report.json:17 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 感觉强人所难了啊……。 | Seems like I'm asking for something hard to answer... |
| 147 | chapters-128242.report.json:64 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 明明不是自己在接吻，身体深处却开始发热。无意识之下的脑海中，将情侣的脸替换成我和浅村君的脸画面不禁浮现，在想什么呢，这般，心中冷静的自我在斥责… | It's not even me who's kissing, yet something deep inside me starts to … |
| 148 | chapters-128242.report.json:146 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 想要互相触碰。我不禁如是渴望到。 / 正如在那间无人可见的密闭房间之中，与他身体相拥的那一刻。 | I want to touch him. I ache for it, just like that moment in the sealed… |
| 149 | chapters-128245.report.json:228 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我觉得自己还真是不适合当赌徒呢。毕竟是如此令人好懂的性格。 | I really wasn’t cut out for lying. My intentions were that transparent. |
| 150 | chapters-128247.report.json:152 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 绫濑同学吐槽道。 | Ayase shot back. |
| 151 | chapters-128249.report.json:191 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「诶—？……嘛啊行吧。机会有的是呢。」 / 有吗？ | "Eh?…Well, fine. There'll be other chances." Will there? |
| 152 | chapters-136058.report.json:12 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「这是什么？」 / 绫濑同学睁大眼睛。 | "What is this?" Ayase's eyes went wide. |
| 153 | chapters-136058.report.json:32 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「知道了。赌一场就行了对吧。」 / 绫濑同学毫不犹豫，拿了正中间那颗。 | "Okay. So it's just one bet, right." Ayase didn't hesitate, taking the … |
| 154 | chapters-128534.report.json:175 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 客观上来看容不容易滑就不知道了。 | Whether it would actually slip is another question. |
| 155 | chapters-128534.report.json:232 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我和绫濑同学都是。 | Neither of us had. |
| 156 | chapters-128535.report.json:13 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “所以说啊，怎么样都好啦。” | "Honestly, it doesn't matter." |
| 157 | chapters-129041.report.json:117 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “这不是当然的吗？” | "Well, of course I did." |
| 158 | chapters-130078.report.json:215 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 背对着我的道谢声，读卖前辈快步走出了办公室。 | She strides out of the office with a wave, not looking back. |
| 159 | chapters-130079.report.json:11 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “真绫。难不难为情啊！” | "Mayo. Don't you find that embarrassing?!" |
| 160 | chapters-130246.report.json:27 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 就算吐不吐槽，都会被捉弄是吗。 | Whether I gave her a straight response or a deadpan reaction, she was g… |
| 161 | chapters-131970.report.json:20 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 今天是我生日，晚上我们要一起吃饭的时候已经被读卖姐打听出来了。 / 虽然没怎么问浅村君，但他有说18点打完工以后一起去吃饭。要是预约的话大概就… | She'd already dug out of me that I was having dinner with him tonight f… |
| 162 | chapters-131970.report.json:127 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 也就是说，因悲剧造成的少女心灵创伤是刺入了加伊眼睛和心脏的恶魔之镜的碎片，而穿越一万年时间前来帮助少女的少年就是格尔达。（） / 调换性别可能… | In other words, the trauma carved into the girl by the tragedy is the s… |
| 163 | chapters-131971.report.json:44 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 不能只被当作哥哥和妹妹看待，反过来说，如果绫濑同学拒绝了过多的邀请，就会显得不自然，无法拒绝的情况，也是会有……。 / 不会吧。那实在是不会发… | If she's seen only as a little sister, then fine, but conversely, if Ay… |
| 164 | chapters-131971.report.json:101 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 健一会儿身会比较好吗。 | Maybe I should get in a quick workout. |
| 165 | chapters-131972.report.json:148 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 要么说能干什么的话，就是看两眼单词卡吧。 | At best, I could flip through the flash cards a bit. |
| 166 | chapters-131973.report.json:109 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 穿过长长的隧道之后，父亲说了句“过了佐久就是小诸了哦”。 / 刚才分别的北陆新干线，与我们车所在的上信越自动车道再度交汇的地方，就是位于轻井泽… | After a long tunnel, my father said, "Once we pass Saku, it's Komoro." … |
| 167 | chapters-131973.report.json:209 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “是三和土啊……”（译：三和土是采用生石灰粉（或消石灰粉）、粘土、砂为原料，按体积比为3：2：1的比例，加水拌和均匀而成，主要用于建筑物的基础… | "It's a doma..." |
| 168 | chapters-131973.report.json:510 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不会吧，应该。 | No way... right? |
| 169 | chapters-131974.report.json:82 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 一想到这也是因为，我不能像浅村君那样对待孩子，心里就是无比的不甘心。但，到底要怎么对待孩子比较好，我是真的不知道。 / 面对大人的话倒是还好。… | And the fact that I couldn't interact with children the way he could fi… |
| 170 | chapters-131974.report.json:113 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 被浅村君这么一说，我顿时一惊。 | His words caught me off guard. |
| 171 | chapters-131975.report.json:85 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 头顶上一望无边的元旦的天空，除了远处的森林上方像贴上去一般的白云的边缘之外，是一片令人眼睛都会生疼的湛蓝。无风，湖面自然是浪静 / ，所以自蓝… | The New Year's sky stretched endlessly overhead. Aside from the edge of… |
| 172 | chapters-131975.report.json:163 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我脱口而出。 | The words slipped out before I could think. |
| 173 | chapters-132712.report.json:101 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「特意做的呢。」 | "You went to all this trouble." |
| 174 | chapters-132713.report.json:144 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「马马虎虎吧」 | "Decently, I guess." |
| 175 | chapters-132715.report.json:53 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 换句话说，变得开始钻牛角尖。 | In other words, he was going down a rabbit hole. |
| 176 | chapters-132716.report.json:83 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 去一趟大使馆，将去国外旅行的气氛炒作起来——我其实还没有这么考虑过。 / 怎么说才好？预习？ | Going to an embassy to pump myself up for traveling abroad—that's not r… |
| 177 | chapters-132720.report.json:142 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「这样的话，一开始拜托真绫就好了。」 | "If that's the case, we could have left it to Mayami from the start." |
| 178 | chapters-132720.report.json:294 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 才不是。 | *No, that's not what I meant.* |
| 179 | chapters-132720.report.json:394 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 真绫哗啦哗啦地泡着澡。 | Maya soaked in the tub with a splash. |
| 180 | chapters-132720.report.json:440 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「太好懂了。」 | "You're an open book." |
| 181 | chapters-132720.report.json:469 | NON_1TO1 | 0:1 | realigned | regression |  | "What do you mean, how would I know?" |
| 182 | chapters-132720.report.json:470 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 那算什么啊。 | What kind of response was that? |
| 183 | chapters-132721.report.json:136 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 真绫说道。 | That was Mayo. |
| 184 | chapters-132721.report.json:198 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不过和真绫所说一样。 | Still, she was right. |
| 185 | chapters-132721.report.json:209 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 真绫说道。 | That was Mayo. |
| 186 | chapters-132721.report.json:216 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我对真绫吐槽道。 | I shot back at her. |
| 187 | chapters-132721.report.json:287 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 要重视磨合。 | I'm supposed to value working things out. |
| 188 | chapters-132722.report.json:71 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 恐怕绫濑她们组和我们一样，这会儿应该正在前往圣淘沙岛吧。 / 说不定就在我坐的这辆巴士前面的巴士上，后面也有可能。因为在公共设施上可以连接WI… | Ayase's group is probably heading to Sentosa right now, just like ours.… |
| 189 | chapters-132726.report.json:27 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：牡丹雪（ぼたんゆき）指的是鹅毛大雪。而牡丹的读音ぼたん和纽扣的读音ボタン相同。 | Note: Botan-yuki (ぼたんゆき) refers to large, heavy snowflakes. The reading… |
| 190 | chapters-134955.report.json:72 | NON_1TO1 | 1:0 | realigned | regression | 译注：选自森鸥外《舞姬》赵玉皎译版。 |  |
| 191 | chapters-134955.report.json:183 | NON_1TO1 | 1:0 | realigned | regression | 译注：柴郡猫（Cheshire cat）是英国作家刘易斯·卡罗尔（Lewis Carroll,1832-1898）创作的童话《爱丽丝漫游奇境记… |  |
| 192 | chapters-134956.report.json:114 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「居然这么说话，这孩子也太可爱了吧——」 / 班长抱着佐藤同学，摸着佐藤同学的头。你的心情我真的明白。 | "Goodness, are you serious—this girl is adorable—" the class rep said, … |
| 193 | chapters-134956.report.json:237 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 无意中就说出了这样的话语。 | The words slipped out before I could stop them. |
| 194 | chapters-134958.report.json:67 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「我开动啦」 | "Thanks for the meal." |
| 195 | chapters-134958.report.json:192 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 怎么了？妈妈用这样的表情看着我。 | *What is it?* her expression asks. |
| 196 | chapters-135034.report.json:23 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 呼出一口气之后，我走进了餐厅。 | I let out a breath. / Then I stepped into the dining room. |
| 197 | chapters-135034.report.json:231 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | ——这样下去好吗？我们。 / 类似的疑问从思考的海底渐渐浮了上来。 | ——Is it okay for us to keep going like this? The question surfaced from… |
| 198 | chapters-135034.report.json:243 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 打开家门，两个人一起说了一声“我回来啦”。接着，两个人像是松了一口气一样，一起叹了一口气。终于回来了。 / 肚子饿了。想要快点吃饭。 | When we opened the front door, we said "We're home" together, then, as … |
| 199 | chapters-135229.report.json:93 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这样下去可不好。 | At this rate, things were in trouble. |
| 200 | chapters-135251.report.json:16 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 顺位上看没怎么掉下来，这也是于事无补的。 | The fact that my rank hadn't fallen much was cold comfort. |
| 201 | chapters-135252.report.json:300 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 和浅村君的关系，以及由这份关系引起的注意力不集中和成绩下降。 / 明明知道最理想的状态就是相互商量磨合，但却做不到。只能放任这种看不清的郁结导… | About my relationship with Asamura-kun, and the lack of concentration a… |
| 202 | chapters-135252.report.json:301 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 工藤副教授听了之后，希望我能进一步讲一讲自己的生长情况，做一下深入探讨。 / 虽然我不是很想说出来，但还是断断续续地说了生父和母亲的关系以及自… | After listening, Associate Professor Kudo asked me to elaborate further… |
| 203 | chapters-135252.report.json:303 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 工藤副教授听我全部说完之后，闭上眼睛，双手交叉放在膝盖上，身体纹丝不动地思考着。 / 就像雕像一样，一动也不动。这让我不得不用她时而眨一下睫毛… | After hearing everything, Associate Professor Kudo closed her eyes, fol… |
| 204 | chapters-135252.report.json:346 | NON_1TO1 | 2:1 | realigned | regression | 我试着在脑海中推演了一下她所说的事情。 / 没钱就无法买酒。但是要是给他钱，就能买到酒了。导致无法戒酒。 | I tried playing out what she'd described in my head. Without money, you… |
| 205 | chapters-135252.report.json:356 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我知道被人依赖是一件很舒服的事情。 / 虽然本质上来说我不喜欢被依赖，但是帮浅村考虑穿着搭配很开心，也确实感受到了自己对浅村君来说是必要的人。 | I know that being depended on feels good. Though I don't fundamentally … |
| 206 | chapters-135252.report.json:397 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 是吗？真的不足吗？需要考虑一下。 / 明明已经足够了，却因为饥饿，感到更加强烈的不足——有这种可能性。 | Is that so? Am I really deficient? I need to think about it. Even if I'… |
| 207 | chapters-135252.report.json:415 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 工藤副教授轻轻倾斜手中的杯子，优雅地将茶叶含在口中。 / 她翘着修长的腿，将白色外褂穿得像是一件披风一样，潇洒地坐在沙发上，一副轻松惬意的模样… | Associate Professor Kudo tilted the cup in her hand slightly and elegan… |
| 208 | chapters-135252.report.json:443 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 工藤副教授从沙发上站起身来。 / 顺势绕过了桌子————采用刺客一样的手法，抓住了我的后背。然后她的手肘撑在了沙发靠背上。我感觉着身后的气息。… | Associate Professor Kudo rose from the sofa. Then, circling around the … |
| 209 | chapters-135252.report.json:485 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 听他说完之后，我如实说道。 / 对磨合感到恐惧的事情，我也和你一样。 | After he finished, I said honestly. The fear of adjusting to each other… |
| 210 | chapters-137852.report.json:96 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「招待不周，承让了」 | "I'm glad you like it." |
| 211 | chapters-137852.report.json:160 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 只有两个人。我和绫濑，无论做什么都不会有人干预，都不会有人责备。当然，我也不是想 / 要做些什么！ | Just the two of us. Me and Ayase, free to do anything without anyone in… |
| 212 | chapters-137852.report.json:284 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 夹了一筷子炒鸡蛋以及下面的米饭，送入口 / 中。还有些湿润的鸡蛋配上已经失去水分的米饭，在口中混在了一起，嚼起来不是干巴巴的，口感不错。 | I scooped up a bit of the scrambled eggs along with the rice underneath… |
| 213 | chapters-138108.report.json:116 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不知不觉就说出来了。 | The words slipped out before I could stop them. |
| 214 | chapters-138109.report.json:74 | NON_1TO1 | 1:0 | realigned | regression | 也成了这个国家的人们所谓乡愁一类的感情 |  |
| 215 | chapters-138110.report.json:174 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这不是记得挺快的嘛。 | She catches on quick. |
| 216 | chapters-138110.report.json:211 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | Ps：冬天日本小孩子们通常会玩一种叫做「押し竞馒头」（おしくらまんじゅう）的游戏。游戏开始前，所有人背靠在一起手挽手，围成一个圆阵。游戏开始后… |  |
| 217 | chapters-138110.report.json:268 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 说着，她满脸堆笑，回到了便当前。似乎是终于满足了。 / 我的内心之中，出了一大堆毫无道理的冷汗。 | With that, she broke into a full grin and turned back to her lunchbox. … |
| 218 | chapters-138110.report.json:378 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 是真绫。 | That was Maya. |
| 219 | chapters-138194.report.json:43 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 校园里可能还有些潮湿，所以在外面比赛的人们就无法训练了。 / 而我们是体育馆竞技组，毫无悬念，必然会好好地做出最后的调整。 | The schoolyard would probably still be a bit damp, so people competing … |
| 220 | chapters-138194.report.json:56 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 因为之前一直纠结，所以迄今为止从来没有一起上过学。 / 果然，高中生里面要是男女生距离很亲近的一起上学的话，似乎会被寄予某种期待呀。 | Because I'd been so hung up about it, we'd never walked to school toget… |
| 221 | chapters-138194.report.json:86 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 吉田急忙观察左右，四下张望。不过，我绝对没有提高音量。 / 我只是遵照常识，小声询问了一下。 | Yoshida hastily looked around to check his surroundings. Though I certa… |
| 222 | chapters-138525.report.json:243 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 大家很开心。「好球！」「加油！」应援的声音此起彼伏。 / 对方发球，开始。 | Everyone was thrilled. Voices shouted out one after another—"Nice!" "Ke… |
| 223 | chapters-138527.report.json:16 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「好像是。」 | "Yeah, that's what I heard." |
| 224 | chapters-138528.report.json:20 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不，也会有脸色十分不好的学生存在。 | Well, not everyone looks so great. |
| 225 | chapters-138528.report.json:57 | NON_1TO1 | 1:0 | realigned | regression | Ps：这里别的不仔细介绍了，唯独阿波舞，这个舞日本人在南京大屠杀时候跳过。打倒日本帝国主义。 |  |
| 226 | chapters-138528.report.json:110 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 妈妈突然间就这么对我说。 / 当时我还觉得，您这是提出了多么难为情的称呼方式啊！ | She said it to me all of a sudden. Back then, I thought, what an embarr… |
| 227 | chapters-138529.report.json:258 | NON_1TO1 | 1:0 | realigned | correction | 「厉害！」 |  |
| 228 | chapters-138529.report.json:260 | NON_1TO1 | 0:1 | realigned | correction |  | "Way to go!" |
| 229 | chapters-138530.report.json:84 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 是在说浅村君看着丸君，然后有一个更进一步地看着浅村君的人吗？ / 搞不懂，所以我微微歪着头。 | Someone watching Asamura-kun as he watches Maru-kun—and someone watchin… |
| 230 | chapters-138530.report.json:120 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | Ps：枕词，日语写作枕词，读作まくらことば。日语和歌中的修辞手法之一，冠于特定词语前而用于修饰或调整语句的词语。 | Ps: Makura-kotoba, written in Japanese as 枕詞 and read as makura-kotoba.… |
| 231 | chapters-138530.report.json:247 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我问他是不是累了，结果他考虑再三才说感到有点累了。明明是自己的事，回答的还那么暧昧不明。 / 我不禁笑了起来。本来就是，那么拼命应援，不累才怪。 | When I asked if he was tired, he thought it over carefully before sayin… |
| 232 | chapters-143611.report.json:32 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「嗯?嘛啊……」 / 太一岳父喝着饭后茶，和我说明了起来。 | "Hmm? Well..." Touichi said, sipping his post-meal tea as he began to e… |
| 233 | chapters-143611.report.json:108 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 是真绫发来的。 | It was from Maya. |
| 234 | chapters-143611.report.json:155 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「应该，没被发现吧？」 | "I don't think he saw me..." |
| 235 | chapters-143612.report.json:21 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 那个时候虽说我意识到了自己情愫，但当下则是两情相悦。回想起来，绫濑那个时候应该也注意到了我。 / 我能指出绫濑自己都没意识到想和大家一起去泳池… | Back then, I'd already been aware of my feelings, but now we were in lo… |
| 236 | chapters-143614.report.json:21 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 读卖前辈若无其事地辩解道。 | Yomiuri-senpai brushed it off with a casual air. |
| 237 | chapters-143614.report.json:162 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 别一点声音没有就出现在背后啊。 | Don't sneak up on people like that. |
| 238 | chapters-143615.report.json:7 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 不过，在小园说出来之前，我从没想到后面能坐三个人。 / 感觉有点拥挤。让小园特意挪一下位置也有点奇怪。肯定是浅村君或者我之中的一个会坐后面，这… | That said, before Sonomura mentioned it, I'd never considered that the … |
| 239 | chapters-143615.report.json:147 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「沙季酱，好像很高兴呢（译注：原文：嬉しそう）」 | "Saki-chan, you seem happy. (Note from translator: original: 嬉しそう)" |
| 240 | chapters-143615.report.json:151 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「我也是！我也很开心！（译注：原文：乐しい）」 | "Me too! I'm having a great time too! (Note from translator: original: … |
| 241 | chapters-143615.report.json:177 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 然后，小圆似乎这次仍没有注意到，读卖前辈并没有说『所以没有男朋友』，而是说了『所以我的男朋友不存在』（译者注：原文分别为『だから彼氏がいない』… | And this time too, Sonomura didn't seem to notice: Yomiburi-senpai hadn… |
| 242 | chapters-143615.report.json:235 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「小园同学，给」 | "Sonomura-san, here." |
| 243 | chapters-143616.report.json:81 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「人好多啊」 | "Busy place, huh." |
| 244 | chapters-143617.report.json:105 | NON_1TO1 | 1:0 | realigned | correction | 唔姆？ |  |
| 245 | chapters-143617.report.json:107 | NON_1TO1 | 1:2 | realigned | correction | 「因为，浅村前辈真的很帅气呢」 | Hmm hmm? / "Because, Minami-senpai really is handsome, you know." |
| 246 | chapters-143619.report.json:122 | NON_1TO1 | 2:0 | realigned | ambiguous | 「我不是想要朋友，只是想要关系好的人」 / 「？有什么区别吗？」 |  |
| 247 | chapters-143619.report.json:158 | NON_1TO1 | 1:0 | realigned | regression | 「是啊。是啊。真的好辛苦。」 |  |
| 248 | chapters-143619.report.json:178 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 即使不是我的兴趣爱好，但如果对方喜欢书，我就会表现得也像喜欢读书一样。即使其实更喜欢酸的东西，可在朋友面前我会说自己超爱甜食。怕幽灵。喜欢猫。… | "Even if it's not something I'm actually into — if the other person lik… |
| 249 | chapters-146056.report.json:100 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 如果我这边不讲的话就有些不公平了吧。 | Only fair, since I asked about hers. |
| 250 | chapters-146058.report.json:57 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 什么嘛那是。 | What on earth is she talking about. |
| 251 | chapters-146058.report.json:127 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「这个，怎么办？」 / 她指着最后那一块曲奇问道。 | "What about this one?" she asked, pointing to the last cookie. |
| 252 | chapters-146059.report.json:3 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「很晴朗的秋天呢」 / 绫濑看着天空说道。 | "What a clear autumn day," Ayase said, looking up at the sky. |
| 253 | chapters-146059.report.json:8 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「因为想着晚上也差不多会冷了」 / 绫濑边说边把手上的毛衣举起来示意。 | "I figured it'd get chilly by evening," Ayase said, holding up the swea… |
| 254 | chapters-146059.report.json:12 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「学习有进展吗？」 / 绫濑突然问道。 | "How's the studying going?" Ayase asked suddenly. |
| 255 | chapters-146059.report.json:23 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 就像这样，说着绫濑揪起了肩膀的部分给我看。 |  |
| 256 | chapters-146059.report.json:66 | NON_1TO1 | 2:1 | realigned | regression | 「拍的真好啊，那个海报」 / 绫濑小声说道。 | "That poster's really well made," Ayase murmured. |
| 257 | chapters-146059.report.json:202 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「你也帮我拍了半身照了吧，那个也很辛苦啊——」 / 梅莉莎说道。 | "You took the headshot of me too, and that was just as tough—" Melisa s… |
| 258 | chapters-146059.report.json:289 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我不知道身旁的绫濑是怎么想的，大概，绫濑也……想到这我满脸通红地看向了绫濑。 / 绫濑也跟我想的一样…应该。 | I didn't know what Ayase beside me was thinking. Probably—she felt the … |
| 259 | chapters-146061.report.json:22 | NON_1TO1 | 2:1 | realigned | regression | 「话说回来，现在根本不是时候吧……」 / 我自言自语道。 | "Anyway, this really isn't the time for that..." I muttered to myself. |
| 260 | chapters-146061.report.json:136 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 这么一来，为了让他们两个都能来，还是把上午和下午都预留下来比较好。 / 我将文化祭的行程记在脑中，同时心想，绫濑能这么流畅地提出对策，或许是因… | With that, we'd reserve both the morning and afternoon slots on the day… |
| 261 | chapters-146061.report.json:365 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「啊……嗯。可以啊」 / 毕竟我有愧于她们，实在没办法拒绝。换句话说……她们两个也会来吗？ | “Ah… um, sure.” Given my guilt over them, I couldn’t exactly refuse. In… |
| 262 | chapters-146061.report.json:385 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 【今天要加班，很晚才回去，你们先吃饭，把门锁好早点休息吧。】 / 呃，也就是说…… | 【Working late tonight, won’t be back until late. Go ahead and eat witho… |
| 263 | chapters-146061.report.json:583 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「这件事对浅村君来说就是救赎吧」 | "That was your salvation, wasn't it?" |
| 264 | chapters-146062.report.json:76 | NON_1TO1 | 0:1 | realigned | correction |  | "Got it." |
| 265 | chapters-146062.report.json:78 | NON_1TO1 | 1:0 | realigned | correction | 「嗯」 |  |
| 266 | chapters-146062.report.json:97 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 边说着，边从旁边指着店里。 | She gestured to the café floor. |
| 267 | chapters-146062.report.json:128 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这下祸从口出了。 | I'd only dug my own grave. |
| 268 | chapters-146062.report.json:287 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「啊，是说正式的服装吗？嗯——，有没有呢？」 / 你看着我问这个不合适吧。但我现在是管家，没办法了我只好摇摇头，成人礼、婚礼、葬礼、祭奠这些因… | "Ah, formal wear, you mean? Hmm—does he?" you ask me like I'd know. But… |
| 269 | chapters-146062.report.json:406 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 「不是那个理由……」 |  |
| 270 | chapters-146063.report.json:58 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「有什么奇怪的地方吗？」 / 绫濑这样问。 | "Is something strange about it?" Ayase asked. |
| 271 | chapters-146063.report.json:66 | NON_1TO1 | 2:1 | realigned | regression | 「那个，只有我现在还没有使用提示的吧？」 / 绫濑说道。 | "Hey, I'm the only one who hasn't used their hint yet, right?" Ayase sa… |
| 272 | chapters-146063.report.json:75 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「这不就玩具里的芯片吗？」 / 那位男学生一副什么啊的表情，拿着那个塑料黄色芯片的女生把它反了过来后。 | "Isn't this just a toy chip?" The boy said with a puzzled expression. T… |
| 273 | chapters-146063.report.json:83 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「诶！嗯………….？」 / 绫濑困惑地看向奈良坂同学。 | "Huh? Um............?" Ayase looked at Naraoka in confusion. |
| 274 | chapters-146063.report.json:118 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「嗯，这个，去哪里喝呢？」 / 我举起了从奈良坂同学那里拿到的罐装果汁。 | "Here, where do you want to drink this?" I held up the canned juice we'… |
| 275 | 37501.report.json:3 | NON_1TO1 | 2:0 | realigned | correction | 姓名 / 比企谷  八幡 |  |
| 276 | 37502.report.json:169 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 这样看来，兼顾「自立」与「合作」应该是这个社团的活动宗旨。老师也不断 / 说着勤劳什么的，所以这应该是个为学生而努力的社团。 | So it seemed the club's guiding principle was balancing "self-reliance"… |
| 277 | 37502.report.json:299 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 由比滨卷起衣袖，开始打蛋，接着加入小麦粉、砂糖、奶油、香草精等材料。连对料理不甚了解的我都看得出，由比滨的手艺非比寻常。或许有人觉得不过 / … | Yui rolled up her sleeves and started cracking eggs, then added flour, … |
| 278 | 37502.report.json:360 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下闻言，跟着叹一口气。 | Yukinoshita sighed in response. |
| 279 | 37502.report.json:438 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 雪之下竟然陷入混乱，而且好像已精疲力竭。 / 好不容易将面团送入烤箱时，她已经累得频频喘气，平时那张扑克脸也冒着汗。打开烤箱后，和先前类似的香… | Yukinoshita had actually fallen into disarray, and she seemed utterly e… |
| 280 | 37502.report.json:536 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 原本不断点头的由比滨惊呼。 | Yui, who had been nodding along, gasped. |
| 281 | 37502.report.json:584 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「我认为只要能提升自己，应该不断挑战极限。就结果而言，那样对由比滨同学 / 也有帮助。」 | "I think the best way to improve yourself is to keep challenging your l… |
| 282 | 37502.report.json:661 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨  结衣 | Yui Yuigahama |
| 283 | 37502.report.json:670 | NON_1TO1 | 1:0 | realigned | correction | 你的信念和「勇者斗恶龙」的「作战」选项一样笼统呢。 |  |
| 284 | 37502.report.json:671 | NON_1TO1 | 2:1 | realigned | correction | 我个人认为你比较适合「勇往直前」的风格。还有，关于你的梦想，的确会有女生那样写。 / 附带一提，老师毕业之后，再也没有和写下那种梦想的女生见过… | Your motto is about as vague as the "Strategy" menu in Dragon Quest. Pe… |
| 285 | 37503.report.json:186 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下雪乃 | Yukinoshita Yukino |
| 286 | 37504.report.json:77 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「哼！那种陋习难道不是地狱吗？自己找喜欢的人一组？呵、呵、呵，吾不知大限何时将至，不可能对任何人产生好感！我不愿再受一次彷佛身心被撕裂般的别离… | "Hmph! Is that陋习 not hell itself? Choosing your own partner? Heh, heh, … |
| 287 | 37504.report.json:91 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 第一次上体育课时，我跟材木座都找不到组员，因而凑成一组后，接下来就一 / 直如此。老实说，我很想把这位重度中二病患者交易出去，但实在没有人肯收… | In the first P.E. class, neither Komachi nor I could find a partner, so… |
| 288 | 37504.report.json:216 | NON_1TO1 | 0:1 | realigned | correction |  | Yuigahama completely ignored Komachi's sentimental remark and looked at… |
| 289 | 37504.report.json:378 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 你的梦想从漫画家变成小说家，是因为不会画图吗？ |  |
| 290 | 37505.report.json:631 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 户冢  彩加 | Totsuka Saika |
| 291 | 37506.report.json:617 | NON_1TO1 | 0:1 | realigned | regression |  | ______________________________________________________________________ |
| 292 | 37506.report.json:621 | NON_1TO1 | 1:0 | realigned | correction | 雪之下  雪乃 |  |
| 293 | 37507.report.json:30 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 「笑点」了(小町说的是日本香堂的广告曲歌词。「笑点」则为日本的长青搞笑综艺节目)。 |  |
| 294 | 38977.report.json:78 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 比企谷　八幡 | Hikigaya Hachiman |
| 295 | 39033.report.json:375 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 辛苦了～＼〝(\*˙ω˙)ノ°＋ | Good work today~＼〝(\*˙ω˙)ノ°＋ |
| 296 | 39034.report.json:89 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | ＼〝(。˙ω˙)ノ°谢谢你教我递 | ＼〝(。˙ω˙)ノ° Thanks for teaching me |
| 297 | 39177.report.json:608 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 科的考试范围？ | inscribing a divine revelation? |
| 298 | 39177.report.json:634 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 昌隆。下次我们见面时，就是在战场上吧…… | smile upon your battles. Our next meeting will / surely be on the battl… |
| 299 | 39497.report.json:122 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | ……真是糟糕透顶。 | ...Just my luck. |
| 300 | 39497.report.json:202 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「自闭男，请客～♪」 | "Recluse, you're paying~♪" |
| 301 | 39497.report.json:381 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 无意识间，我只有「你也加入」这几个字讲得比较有男子气概。没办法，对方可是揪着运动衫的袖子，抬眼看着我说出「我想参加」这种话耶（注28　原文的「… | Unconsciously, I said only "you can join" with a bit more manliness. Wh… |
| 302 | 39497.report.json:630 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「谁是哈密瓜啊……」（注32　此处原文为「女郎」，日文发音跟「哈密瓜」相似。） | "Who are you calling a melon?..." (Note 32: The original line here is "… |
| 303 | 39622.report.json:10 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 也就是说，我是最强的。 | In other words: me. |
| 304 | 39622.report.json:228 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 总觉得老师的话中带有佩服的语气。 | There was a hint of admiration in her tone, or so it seemed. |
| 305 | 39722.report.json:177 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 咦？奇怪？ | Wait... hold on. |
| 306 | 39722.report.json:318 | NON_1TO1 | 2:1 | realigned | correction | 「唔，不妙，我要先去避风头。再会吧～」 / 「那不就是沙拉吃到饱吗（注16　上一句「再会吧」的原文「さらだばㄧ（saradaba）」，音近「沙… | "Uh-oh, not good. I'll be taking my leave. Sa-lad-bye~" (Note 16: The o… |
| 307 | 39722.report.json:319 | NON_1TO1 | 0:1 | realigned | correction |  | "Har har, that's a real salad-dressing joke..." |
| 308 | 46022.report.json:91 | NON_1TO1 | 2:1 | realigned | regression | 「不是轻……什么的那个吗？」 / 由比滨有些不解。 | "Isn't it... that light novel thing?" Yuigahama asked, looking confused. |
| 309 | 46022.report.json:108 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「那个游嬉社怎么了吗？」 / 由此滨把「游戏」这个字念得很奇怪。材木座听到她提问，又短暂思考一下。 | "What about that Game-y Club?" Yuigahama asked, pronouncing "game" oddl… |
| 310 | 46022.report.json:114 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 材木座，那样太难看了。 | Zaimokuza, that's just pathetic. |
| 311 | 46022.report.json:295 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 秦野如此暗示。 | A hint, from Hatanaka. |
| 312 | 46022.report.json:367 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「小、小雪乃，我们两个一组吧！」 | "I-I'm teaming up with Yukino!" |
| 313 | 46022.report.json:416 | NON_1TO1 | 0:1 | realigned | correction |  | "This is such a pain~" |
| 314 | 46022.report.json:418 | NON_1TO1 | 1:0 | realigned | correction | 「伤脑筋啊～」 |  |
| 315 | 46022.report.json:832 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 秦野如此低喃。 |  |
| 316 | 46022.report.json:834 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「不过，你们也是一群怪人……」 / 相模有些冷淡地回道。 | "But you guys are a bunch of oddballs too..." Sagami replied, rather dr… |
| 317 | 46022.report.json:838 | NON_1TO1 | 1:0 | realigned | regression | 由比滨见雪之下冷静地说出那种话，尴尬地笑着说道。 |  |
| 318 | 46025.report.json:471 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「什么啊？照你这么说，A型的人是『欸～粗枝大叶』（注47　粗枝大叶的日文为「ぉぉざつぱ（oozappa）」。此处是玩文字游戏，指O型的O是「o… | "What's that supposed to mean? By that logic, A types are 'eh~ carefree… |
| 319 | 41189.report.json:34 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 三年三班比企谷八幡 | Hikigaya Hachiman, Class 3-3 |
| 320 | 42034.report.json:132 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「我先说清楚，laurier就是月桂叶，你这个萝莉控（注29　laurier（ローリエ）和萝莉控（ロリコン）前半部发音相似。）。」 | "Let me make this clear, laurier is bay leaf. You lolicon (note 29: "La… |
| 321 | 42034.report.json:143 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 接下来是架饭锅，用锅子炒蔬菜和肉类。海老名突然冒出「蔬菜听起来好像YAOI……真猥亵」这句发言（注30　YAOI（やおい）是以男性同性爱情为题… | Next was setting up the rice cooking pot and sautéing the vegetables an… |
| 322 | 42034.report.json:207 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 开口的人是鹤见留美，她的声音相当冷淡。我决定从现在开始叫她「留留」。这是「机动战舰」（注31　「留留」原文为「ルミルミ」，类似「机动战舰」角色… | The speaker was Tsurumi Rumi, her voice quite cold. I decided to call h… |
| 323 | 42034.report.json:535 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 海老名姬菜 | Ebina Hina |
| 324 | 42770.report.json:32 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 如果你处在一个集团的边陲地带，他人基于社交上的礼貌，还是会来询问你的意愿，例如「嗯……你要去吗」这样子。 / 老实说，这种东西还是省省吧，根本… | If you're on the fringes of a group, people will still ask your opinion… |
| 325 | 42284.report.json:195 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 酥饼在房间内四处乱绕，不停嗅嗅闻闻。啊，对喔，因为家里还有一只猫，酥饼才会对它的气味产生反应。 / 至于我家的猫小雪，不知什么时候已经逃到冰箱… | Sable roamed around the room, sniffing at everything. Ah, right, since … |
| 326 | 42285.report.json:92 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这种话早点讲好不好？ | Why didn't you lead with that?! |
| 327 | 43057.report.json:105 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 酥饼嗅着草堆的气味，鼻子不断发出声音，然后啃起青草。猫跟狗都会像这样吃杂草，把胃里的毛球吐出来，这是带宠物出去散步时一定会遇到的情况，因此我和… | Suberu sniffed at the tufts of grass, his nose making little sounds, th… |
| 328 | 43331.report.json:100 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 炒面　　　　　　　l〇〇圆 | Yakisoba — 100 yen |
| 329 | 43559.report.json:29 | NON_1TO1 | 1:0 | realigned | correction | 「哎呀，好久不见。」 |  |
| 330 | 43559.report.json:31 | NON_1TO1 | 0:1 | realigned | correction |  | "Yeah, it has." |
| 331 | 43713.report.json:2 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 别开玩笑了！怎么可能？ | Yeah, right. Like hell it is. |
| 332 | 43775.report.json:2 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 风从微微开启的窗户吹进来，窗帘翻飞而起，露出窗外染成红色的卷积云。 / 这样的景色重复两、三次后，我停下翻开书本的手。不断从视线边缘晃过的细微… | A breeze slipped through the slightly open window, sending the curtain … |
| 333 | 43775.report.json:25 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「很会社交（注5　「遮光」和「社交」的日文发音相同。）却很阴暗？」 | "Blackout... and outgoing—wait, those sound the same, but you're still … |
| 334 | 44312.report.json:237 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 老师说得相当豪迈，我仿佛还在语尾听到一声「再见啦～」（注24　原文为「じゃあの」，是广岛方言中的道别用语。）。看来他是校庆活动的指导老师，坐在… | The teacher declared this with great gusto, and I could almost hear a "… |
| 335 | 44312.report.json:251 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 巡学姐看向雪之下，对她问道。 | Meguri-senpai turned to Yukinoshita, addressing her directly. |
| 336 | 44312.report.json:284 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 如果是面对融资团体（注27　「有志」跟「融资」的日文发音相同。），我还愿意去交涉，换成有志团体的话，还是算了。 | If it were a financing group (Note 27: "有志" (volunteers) and "融資" (fina… |
| 337 | 44312.report.json:326 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 可惜，我们进入千叶电视台跟JAGUAR先生见面的可能住太低，只好先忍耐下来。顺便提醒一下，这里说的JAGUAR不是《吹奏吧！嘉卡（注30　一部… | Unfortunately, the odds of us getting into Chiba TV and meeting JAGUAR-… |
| 338 | 44312.report.json:342 | NON_1TO1 | 0:1 | realigned | correction |  | "Sure." |
| 339 | 44312.report.json:344 | NON_1TO1 | 1:0 | realigned | correction | 「嗯。」 |  |
| 340 | 44312.report.json:363 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 生日 / 6月26日 | Birthday: June 26th |
| 341 | 44312.report.json:364 | NON_1TO1 | 1:0 | realigned | correction | 专长 |  |
| 342 | 44312.report.json:366 | NON_1TO1 | 1:0 | realigned | correction | 兴趣 |  |
| 343 | 44312.report.json:368 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 假日活动 / 在住家附近的超商打工、购物。 | Holiday activities: Working a part-time job at a convenience store near… |
| 344 | 44403.report.json:56 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下被她那么称赞，露出不敢当的表情。 | Yukinoshita looked somewhat modest at the praise. |
| 345 | 44404.report.json:58 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 叶山找到雪之下，走向她说明来意。 | Hayama found Yukinoshita and walked over to state his business. |
| 346 | 44404.report.json:290 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 这次的班服也不例外，上面印满大家的昵称，只有我的最普通，直接用「比企谷同学（注51　此处原文为「比企谷クン」。）」的本名上阵。昵称通常是用平假… | This year's shirt was no exception—it was covered in everyone's nicknam… |
| 347 | 44404.report.json:380 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 印象中，相模不是说过她会写申请单吗？为什么最后变成我写？这到底是怎么回事……完全搞不懂……搞不懂……科学小飞喵（注54　此处「完全搞不懂」的原… | I was pretty sure Sagami had said she'd write the application, hadn't s… |
| 348 | 44404.report.json:480 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下阳乃 | Yukinoshita Haruno |
| 349 | 44405.report.json:397 | NON_1TO1 | 1:0 | realigned | correction | 「喔，再见。」 |  |
| 350 | 44405.report.json:399 | NON_1TO1 | 0:1 | realigned | correction |  | "Mm, see you." |
| 351 | 44406.report.json:258 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 由比滨低喃。 |  |
| 352 | 44407.report.json:149 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 听我这么说，雪之下考虑了一下。 | Yukinoshita considered this for a moment. |
| 353 | 44408.report.json:201 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 其他人听了，不约而同地你看我、我看你。 | The others exchanged glances with each other. |
| 354 | 44408.report.json:226 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「嗯……可、可是，歌词我只记得一点点（注83　原文「记得一点点」为「うる觉え」，是日文中常见的错误念法。正确为「うろ觉え」。），不要对我太期待… | "Hmm... B-But, I only remember a little bit of the lyrics (Note 83: The… |
| 355 | 46589.report.json:111 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「鹿苑寺照司（注9　此处的「寺」与「司」发音相同。）……」 | "Rokuonji Terutsukasa (Note 9: The "ji" in Rokuon-ji sounds identical t… |
| 356 | 46592.report.json:30 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「八幡……京之都乃吾灵魂之故乡，可真令人怀念。呜呼啦呜呼啦（注33　此处原文为「ルフランルフラン」，来自法文「refrain」。高桥洋子有一首… | "Hachiman... Kyoto, the capital of the spirits, is my soul's homeland—h… |
| 357 | 46592.report.json:486 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 户部看出我的用意，对海老名伸手。 | Tobe caught my drift and reached out to Ebina. |
| 358 | 46592.report.json:520 | NON_1TO1 | 1:0 | realigned | correction | 「啊……」 |  |
| 359 | 46592.report.json:522 | NON_1TO1 | 0:1 | realigned | correction |  | "Yeah..." |
| 360 | 46593.report.json:266 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 没错，是「天下一品」，不是成人杂志《Deluxe Beppin》（注50　原文为「デラペつぴん」，与「天下一品」发音相近。）。据说他们的汤头相… | Indeed—it was Tenka Ippin, not the adult magazine *Deluxe Beppin* (Note… |
| 361 | 46594.report.json:164 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨终于恍然大悟。 | Yuigahama finally had her "aha" moment. |
| 362 | 46594.report.json:316 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 时间已经过了傍晚五点，我们在金阁寺等公车，准备回去旅馆。 / 叶山先用电话跟导师告知我们会晚到。最后回到旅馆时，男生的泡澡时间早已结束。 | It was already past five in the evening. We waited at the bus stop near… |
| 363 | 46595.report.json:64 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「我开动了。」 | "Thank you for the meal." |
| 364 | 46595.report.json:79 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下轻笑一下。这个关子卖得真不错。 | Yukinoshita chuckled lightly. She had a knack for building suspense. |
| 365 | 46608.report.json:134 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「怎么可能？」 | "Like that would ever happen." |
| 366 | 46610.report.json:662 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 第一个想到的是雪之下。 | Yukinoshita came up with one first. |
| 367 | 46610.report.json:710 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨这家伙，发表感想前一点都不知修饰。 | That Yuigahama, she doesn't even try to soften her verdict. |
| 368 | 46610.report.json:825 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下不遑多让。 | Yukinoshita fired back. |
| 369 | 46610.report.json:953 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「请、请问，闪剑（注76　原文为「闪ブレ」，是用LED手电筒改造的萤光棒，亮度远高于一般萤光棒。）有长度限制吗？」 | "Um, e-excuse me, is there a length limit for the flash blade (note 76:… |
| 370 | 53812.report.json:9 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 相乐总大人，尽管我们的作品刚好在同一季开播动画，还是承蒙您在百忙中撰写书腰推荐文（注77　本集的日本书腰推荐文为：「好开心！全世界最有趣的青春… | Sou Sagara-sama, even though our works happened to have their anime ada… |
| 371 | 48766.report.json:14 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 这也不奇怪，毕竟校庆让全校师生上下一心（除了我以外），运动会不分敌友的大混战（除了我以外），毕业旅行则是感情融洽的伙伴们的亲密时光（除了我以外… | It's no surprise, really. The school festival brought the entire school… |
| 372 | 48766.report.json:77 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「我看喔～笔名腐生物（注5　日本twitter流传的表情符号「┌（┌^O^）┐ホモォ……」，原用来影射喜欢BL作品的女性，后经二次创作等影响而… | "Let's see~ Pen name: Fudanshi-san (Note 5: A popularly circulated emoj… |
| 373 | 48767.report.json:153 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「眼珠比赛主（注17　「压轴比赛」日文写作「目玉竞技」，可直译为眼珠比赛。）……」 | "Eyeball event..." (Note 17: "Main event" in Japanese is written as "目玉… |
| 374 | 49047.report.json:165 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我在心里佩服着，然而偷瞄了一下对方，才发现她一脸愉快的喃喃自语着「那个也不错，可是还是选这个吧～」，这家伙大概是那个啦，只是在想自己最喜欢什么… | I admired her internally, but then I glanced over and saw her muttering… |
| 375 | 49047.report.json:204 | NON_1TO1 | 0:1 | realigned | correction |  | 'Decathlon' |
| 376 | 49047.report.json:206 | NON_1TO1 | 1:0 | realigned | correction | 『十日谈（注24　日文音近十项铁人。）』 |  |
| 377 | 49137.report.json:264 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「的确是呢……」 / 雪之下睁开眼睛回答。 | "Indeed..." Yukinoshita opened her eyes and replied. |
| 378 | 49137.report.json:276 | NON_1TO1 | 2:1 | realigned | regression | 「稍微隔开一点时间，让双方都冷静下来后，再看看情况……」 / 巡学姐补充老师的意思。 | "By putting a little distance between us and giving both sides time to … |
| 379 | 49137.report.json:279 | NON_1TO1 | 2:1 | realigned | regression | 「可是，一天两天就能冷静下来吗……」 / 由比滨喃喃自语。 | "Still, can things really cool down in a day or two..." Yuigahama murmu… |
| 380 | 49137.report.json:286 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「就算如此，比起保持现在的状态继续开会来得好多了。」 / 大概是感受到我的疑虑，平冢老师非常不情愿地说道。 | "Even so, it's better than continuing the meeting as we are now." Hirat… |
| 381 | 49137.report.json:289 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「这样没有问题吧？」 / 平冢老师向相模确认，相模点了点头。 | "That's fine, isn't it?" Hiratsuka-sensei asked Sagami for confirmation… |
| 382 | 49137.report.json:290 | NON_1TO1 | 2:1 | realigned | regression | 「是、的……」 / 断断续续地回答完后，相模又将头低了回去。 | "Y-yes..." Her answer was halting, and then she lowered her head again. |
| 383 | 49137.report.json:291 | NON_1TO1 | 2:1 | realigned | regression | 「……」 / 一直在旁观察着相模的雪之下，突然移开视线，转身面向巡学姐。 | "..." Yukinoshita had been quietly observing Sagami, but now she averte… |
| 384 | 49137.report.json:293 | NON_1TO1 | 2:1 | realigned | regression | 「嗯。那就由我们学生会负责联络啰。」 / 巡学姐一做出回应，干部们便马上理解巡学姐的意思，迅速地开始动作。大概是靠简讯还是朝会，总之虽然我不清… | "Mm. We'll handle the notices from the student council side, then." As … |
| 385 | 49137.report.json:297 | NON_1TO1 | 2:1 | realigned | regression | 「唔。先告辞了，八幡。」 / 一直沉默不语、被晾在一旁的材木座迅速地收好自己的东西，接着快步离开会议室。其他的学生会干部们也迅速地准备完毕，踏… | "Mm. I'll be going now, Hachiman." Kemizusa, who had been silent and ig… |
| 386 | 49137.report.json:309 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「嗯，是的。虽然不只这样……」 / 老师一边含糊回答，一边看向相模。 | "Yeah. Well, not just that..." Hiratsuka-sensei answered vaguely, then … |
| 387 | 49137.report.json:311 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「咦……」 / 大概是没有料到会被老师点名，相模思考了一会才开口。 | "Huh..." Sagami hadn't expected to be called on, apparently. She though… |
| 388 | 49137.report.json:326 | NON_1TO1 | 2:1 | realigned | regression | 「是、是的。」 / 相模虽然立刻应声回答，但是我想她大概根本没搞懂巡学姐在说什么。 | "Y-yes." Sagami answered immediately, but I doubt she had any idea what… |
| 389 | 49137.report.json:338 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「说说看。」 / 我被平冢老师催促，于是简单地做说明。 | "Go on." Hiratsuka-sensei urged me, so I gave a brief explanation. |
| 390 | 49137.report.json:344 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「我不是很懂……」 / 相模显得有些焦躁。 | "I don't really get it..." Sagami sounded a little irritated. |
| 391 | 49137.report.json:368 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「……那、那个。」 / 话说到一半，她偷瞄了雪之下一眼。 | "...Um." She started, then snuck a glance at Yukinoshita. |
| 392 | 49137.report.json:372 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「但、但是……」 / 相模企图反驳对方，却被雪之下一语打断。 | "B-but..." Sagami tried to counter, but Yukinoshita cut her off in a si… |
| 393 | 49137.report.json:378 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「我、我……」 / 她的声音颤抖着。 | "I... I..." Her voice trembled. |
| 394 | 49137.report.json:398 | NON_1TO1 | 2:1 | realigned | regression | 「……如果你很在意之后的情况，我可以告诉你不必担心。你可以放心交给我。」 / 雪之下持续追击，又补上了一句。 | "...If you're worried about what happens afterward, I can assure you. Y… |
| 395 | 49137.report.json:433 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「……是、呢。」 / 相模像是没有自信地喃喃自语。 | "...Y-yeah." Sagami murmured, sounding anything but confident. |
| 396 | 49137.report.json:441 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「好，拜托你了。」 / 雪之下回以微笑，由比滨便「哼」的一声用力点了点头。看来她很高兴雪之下愿意依靠自己。 | "Alright. Thank you." Yukinoshita replied with a smile, and Yuigahama g… |
| 397 | 49137.report.json:445 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「咦……不，这个……」 / 我看了看自己的双手。咦？好奇怪哟。我的双手一点也不空啊？难不成我的双手其实开了叫做风穴还是什么的洞，空洞到可以把妖… | "Huh... No, well..." I looked at my own hands. Huh? That's weird. My ha… |
| 398 | 49137.report.json:469 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 特别是由比滨，她一定会很辛苦。与已经心生嫌隙的运动社团人士沟通十分困难，这点可谓显而易见。若是如此，帮忙减轻这份负担，便是身为能干的男人——高… | Especially Yuigahama—she's going to have a rough time. Communicating wi… |
| 399 | 49950.report.json:77 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 看不下去的巡学姐插嘴说道。 | Meguri-senpai, unable to bear it, interjected. |
| 400 | 49950.report.json:215 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 通风良好的职场（注46　原文「风通しが良い」」亦指组织内部公开透明，高层与低层沟通无碍、不隐瞒造假的企业文化。），应该是指人少的意思吧，我一边… | "A well-ventilated workplace" (note 46: The original Japanese "風通しが良い" … |
| 401 | 49950.report.json:542 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 雪之下不加思索地回答。你也太过分啰…… / 户部确实是如垃圾一般无可救药的家伙，但他并不坏啊？你看，他不是愿意当我的代罪羔羊（强制）。 | Yukinoshita answered without missing a beat. That's a bit harsh… Though… |
| 402 | 49950.report.json:603 | NON_1TO1 | 10:0 | realigned | equivalent | One dayMobile talk Hachiman＆Yui / 由比滨结衣 / 嗨啰——(＝°ωﾟ)ノ！你跟中二联络了吗(·\_˙;？？ … |  |
| 403 | 49950.report.json:604 | NON_1TO1 | 10:0 | realigned | equivalent | 由比滨结衣 / 有更好的传达法吧((((;ﾟДﾟ)))))) / 还有，至少也用个表情符号吧>\_\< / 这样看起来很像在生气……(.\_.… |  |
| 404 | 49950.report.json:605 | NON_1TO1 | 2:0 | realigned | equivalent | 喂，你别给我只打两个字。 / *One dayMobile talk Hachiman and Yui* |  |
| 405 | 50480.report.json:709 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下听到这里，大大地叹一口气。 | Yukinoshita let out a long sigh at that. |
| 406 | 49454.report.json:43 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 两个人瞬间露出大失所望（注1　此处原文为「呆れられていた」，罗马拼音为「akirerareteita」。）的表情。这么说来，把「大失所望」的日… | The two of them instantly wear expressions of utter disappointment (not… |
| 407 | 49455.report.json:644 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我盯着完全空白的页面，思考该如何下笔。距离截稿已经进入倒数计时。嗯？你问我前几天在干什么？不是那样的，你误会了～是我一直没有灵感啦～你知道这种… | I stare at the completely blank page, thinking about how to begin. The … |
| 408 | 49455.report.json:666 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 『他说还没……嗯，我问问看。』 / 由比滨正在跟雪之下对话，所以在我听到答覆之前，隔了一点时间。 | 'He says not yet... Okay, let me ask.' There's a pause as Yuigahama tal… |
| 409 | 49496.report.json:484 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 「喔喔喔！」 |  |
| 410 | 49498.report.json:9 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 太阳照不进校舍后方与新大楼之间，因而此处比其他地方凉爽许多。如果从空中俯瞰，总武高中的主要校舍呈「口」字形，新大楼孤单地被遗落在外，大部分学生… | The sun never quite reaches the space between the main school building … |
| 411 | 49498.report.json:10 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 因此，现在除了我跟另一个人，这里没有第三者存在。 | Which made it the perfect spot for exactly two people, and no one else. |
| 412 | 49498.report.json:177 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下听见敲门声，立刻回应。 | Yukinoshita responded immediately. |
| 413 | 49498.report.json:428 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「举办活动如何？不是有很多跨校型（注43　此处原文为「インカレ」，是英语「inter college」的简称。之后提及的印度咖哩为「インドカレ… | "How about holding an event? Aren't there a lot of intercollegiate (Not… |
| 414 | 49498.report.json:716 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「多多指教，材木座同学。」 | "Let's do our best, Zaimokuza." |
| 415 | 49498.report.json:956 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 「……」 |  |
| 416 | 49498.report.json:1198 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 她露出了然于心的模样，打开书本继续阅读。由比滨禁不住好奇，摇晃她的身体追问： / 「咦，什么意思？到底是什么意思？」 | She looks like she understands, opens her book, and continues reading. … |
| 417 | 52004.report.json:241 | NON_1TO1 | 0:1 | realigned | correction |  | "Sounds good." |
| 418 | 52004.report.json:243 | NON_1TO1 | 1:0 | realigned | correction | 「好啊。」 |  |
| 419 | 52004.report.json:381 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「打扰啰。」 | "Mind if I come in?" |
| 420 | 52006.report.json:204 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 折本也佩服地叹道： | Orimoto let out an impressed sigh. |
| 421 | 52008.report.json:19 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 结果，叶山提的是其他事。 | But that wasn't what Hayama brought up. |
| 422 | 52008.report.json:497 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 真要说的话，那也算是自己年少不懂事吧。 | If anything, I'd chalk it up to the foolishness of youth. |
| 423 | 52009.report.json:35 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不过，他们也不得不那么做。 | But they didn't have a choice, really. |
| 424 | 52009.report.json:87 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 平冢老师听了，显得不太高兴。 | Hiratsuka-sensei frowned at that. |
| 425 | 52010.report.json:6 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 但是不论冲洗再久，仍旧觉得提不起精神。我最后索性放弃，关掉水龙头。 / 我瞅着镜中不断滴水的自己——你还是老样子，挂着一对死鱼眼。 | But no matter how long I stood under the spray, I still couldn't shake … |
| 426 | 52010.report.json:9 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 缓解疲惫的最好方式，莫过于寻求小动物的治愈。先前踩脚踏车踩得太激烈， / 腿部累积过多乳酸，整个人累到快瘫掉。 | There's no better cure for exhaustion than seeking comfort from a littl… |
| 427 | 52010.report.json:68 | NON_1TO1 | 0:1 | realigned | correction |  | "Here." |
| 428 | 52010.report.json:70 | NON_1TO1 | 1:0 | realigned | correction | 「嗯。」 |  |
| 429 | 52010.report.json:268 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 对面的海老名用手梳着黑色短发，提议： | Across from them, Ebina ran a hand through her black短发 and offered: |
| 430 | 52011.report.json:115 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「我问你，你……觉得叶山这个人怎么样？」 / 正要把问题问出口时，我临时修改自己的用字。我的内心住着一位纯情少女，直接说出「喜欢」这种字眼实在… | "Let me ask you... what do you—" I almost said "feel about Hayama," but… |
| 431 | 52011.report.json:360 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下看完资料，如此低语。 | Yukinoshita murmured after finishing the documents. |
| 432 | 52011.report.json:391 | NON_1TO1 | 0:1 | preserved_exactly | preserved_structure |  | *Clatter.* |
| 433 | 54253.report.json:87 | NON_1TO1 | 1:0 | realigned | correction | 折本佳织 |  |
| 434 | 54253.report.json:97 | NON_1TO1 | 1:0 | realigned | correction | 一色伊吕波 |  |
| 435 | 54717.report.json:129 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 开口一定要溜英文的玉绳听了，果然上钩。 | Tamazusa, who always had to slip in some English, took the bait as expe… |
| 436 | 54754.report.json:122 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 玉绳拿出精神，跟到场的小学生打招呼。 | Tamagawa gave a lively greeting to the elementary schoolers who'd arriv… |
| 437 | 54754.report.json:146 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 对于玉绳的请求，一色也显得很为难。 | Isshiki also seemed at a loss in response to Tamagawa's request. |
| 438 | 54754.report.json:339 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 所以，今天的晚餐就决定是First Kitchen话说回来，First Kitchen的简称是怎么回事（注32　First Kitchen原文… | And so, tonight's dinner was decided: First Kitchen. Speaking of which,… |
| 439 | 55128.report.json:265 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 一色丝毫没料到自己会被点名，大大地吃了一惊。 | Iroha was caught completely off guard by being asked to speak. |
| 440 | 55128.report.json:402 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下见她那么为难，不禁轻叹一口气。 | Yukinoshita gave a small sigh at her flustered response. |
| 441 | 55128.report.json:523 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 户部紧紧搂住叶山，他的情绪之激动，感觉随时会说出「喔，我的挚友——（注38　《多啦A梦》中胖虎的知名台词，经常用于对自己好的人。原文为「心の友… | Tobe clung tightly to Hayama, so overwhelmed with emotion that he looke… |
| 442 | 55188.report.json:296 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「过奖了。」 | "Flattery will get you nowhere." |
| 443 | 55254.report.json:130 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下已经不知是第几次按住太阳穴。 | Yukinoshita pressed her temple for what had to be the umpteenth time. |
| 444 | 55274.report.json:103 | NON_1TO1 | 1:0 | realigned | regression | 「在所有赠送礼物的人中，这两个人是最聪明的。」 |  |
| 445 | 55274.report.json:105 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 「无论在世界上的哪个角落，这样的人都是最有智慧的贤者。」 | "Everywhere they are wisest." / "They are the magi." |
| 446 | 55274.report.json:135 | NON_1TO1 | 1:2 | realigned | correction | 今天的这个舞台，我是不会忘记的（注46　出自偶像大师剧场版「迈向闪耀的彼端」制作人台词。）！ | I will never forget this stage today! / ×　×　× |
| 447 | 55274.report.json:219 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 结局之后的发展，现在的我仍未知晓。 / 因此，我势必会持续追寻下去。 | What comes after the ending, I still don't know. And so, I will inevita… |
| 448 | 60021.report.json:91 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 天啊，这样也能傲娇……这么廉价的傲娇，简直跟Portopia的凶手有得比。凶手是阿康（注4　出自PC与任天堂红白机著名推理游戏《Portopi… | God, even her tsundere act... Such a cheap tsundere it's practically on… |
| 449 | 60021.report.json:156 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 一般而言，即使要约其他人一同参拜，也会选择同一间学校的朋友才对。不过，我国中时没有朋友，所以不知道实际情况如何……对啦，一定是妖怪的错。这就是… | Normally, if you were going to invite someone to go shrine-visiting tog… |
| 450 | 60021.report.json:321 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「仿冒品（注9　原文为「パチモン」，发音与八幡相似。）？好像听过这个名字……是不是叫比、比企……」 | "Knockoff [Note 9: The original term "パチモン" sounds similar to "Hachiman… |
| 451 | 60157.report.json:63 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 到底送什么才好…… | What was I supposed to give her? |
| 452 | 60157.report.json:181 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 听到由比滨赞美，反而换我不知该做何反应。 | Being complimented by Yuigahama threw me off even more. |
| 453 | 60157.report.json:262 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 你真的知道吗……就是「美乐斯开始跑了……美乐斯跟塞里努丢斯……永远都是好碰友……！（注16　「原文为「メロスゎ走った……メロスとセリヌンゎ……… | Do you actually know it... It's the one where "Melos ran... Melos and S… |
| 454 | 60198.report.json:8 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 不过，撑过精神上的强大负担，才能成为真正的强者或无职者。所谓的无职者和轻小说作者，总是要等到火烧眉毛，才会说：「我要认真啰！」由此可知，无职者… | But only those who endure that heavy mental burden can become true stro… |
| 455 | 60198.report.json:200 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下叹一口气，一旁的由比滨也陪着苦笑。真拿这个家伙没办法……我们三个人完全被打败，唯有一色本人一派轻松，轻松到我想把她摆到药局门口当吉祥物（… | Yukinoshita sighed, and Yui let out a wry laugh beside her. We were com… |
| 456 | 60198.report.json:235 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 原来是这个意思。仔细想想，我好像没听过任何跟叶山有关的绯闻。虽然一部分的原因出在我对这类八卦没兴趣，也没有人会告诉我消息。正因为如此，才向雪之… | So that's what she meant. Come to think of it, I'd never heard any rumo… |
| 457 | 60555.report.json:163 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 由此滨还没说完，便被海老名激动地打断。 | Yui started, but Ebina interrupted her with fervor. |
| 458 | 60555.report.json:232 | NON_1TO1 | 1:2 | realigned | regression | 「啪」的一声，客厅恢复光明。 | *Click.* / The living room came back to life. |
| 459 | 64862.report.json:202 | NON_1TO1 | 1:0 | realigned | regression | 异世界转生系作品，甚至是轻小说本身，只要能让喜欢的人开心就行了。 |  |
| 460 | 64863.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # 第10.5卷 ② 一色伊吕波一定是用糖和香料以及一切美好事物所构成的 | # Volume 10.5 ② / Iroha Isshiki Is Surely Made of Sugar and Spice and E… |
| 461 | 64863.report.json:67 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 一色听了，装模作样地鼓起脸颊。 | Iroha puffed out her cheeks in an exaggerated show of displeasure. |
| 462 | 64863.report.json:259 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「我要发球啰。」 | "I'm serving now." |
| 463 | 64864.report.json:112 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 一色做了个调皮的笑容，嘴里说出的话却是再糟不过。什么「哗啦哗啦」，你是某社群游戏的员工吗……（注25　「哗啦哗啦」原文为「じゃぶじゃぶ」，影射… | Iroha made a mischievous grin, but the words coming out of her mouth we… |
| 464 | 64864.report.json:710 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「唉，是吗？」 | "Oh... if you say so." |
| 465 | 64864.report.json:889 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 真是的，老是说别人太天真，到底是谁比较天真（注37　此处为双关语，原文「甘い」除了「天真」以外，另有「对人温柔」之意。）呢。 / 我不否认自己… | Honestly, she always says others are too naive—but who's really the nai… |
| 466 | 64865.report.json:77 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「你要我怎么生给你。」 | "What am I supposed to do, conjure it out of thin air?" |
| 467 | 67211.report.json:1 | NON_1TO1 | 5:0 | preserved_exactly | preserved_structure | 台版 转自 轻之国度 / 扫图：任雷劈 / 录入：任雷劈 / 初校：任雷劈 / 修图：零食 |  |
| 468 | 67551.report.json:83 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 一色和三浦的无声战斗没有停歇，让身为男生的我自觉没有容身之处，甚至怀疑美国都市传说中的瘦形魔（注7　Slender man。据说出没在树林里的… | Iroha and Miura's silent battle showed no signs of stopping, and as a g… |
| 469 | 67551.report.json:145 | NON_1TO1 | 0:1 | realigned | correction |  | "Huh?" |
| 470 | 67551.report.json:147 | NON_1TO1 | 1:0 | realigned | correction | 「怎样？」 |  |
| 471 | 67551.report.json:175 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「是啊。炖芋球和猫打滚听起来有点像（注8　炖芋球原文为「里芋の煮ころがし」，猫打滚则为「ねつころがし」。），感觉满可爱的。」 | "Yes. Stewed taro balls and cat-rolling sound kind of similar (Note 8: … |
| 472 | 67558.report.json:193 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 这部分我不是很懂，所以还是不要随便插嘴比较好。要说我有多不懂，大概就是会把萨赫蛋糕说成萨鲁蛋糕的地步吧（注14　出自《俺物语》之桥段。主角猛男… | I wasn't very knowledgeable in this area, so it was best not to butt in… |
| 473 | 67559.report.json:261 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 不过，一色为了投入学生会预算，想必也动了不少脑筋吧。制作那些海报，八成就是为了证明真的办过活动，只要有实际品项支出，请款的时候也很方便！她居然… | Still, Iroha must have racked her brains quite a bit to secure the stud… |
| 474 | 67559.report.json:312 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 巡学姐口中的名字，不可能是指在某温泉旅馆上班的女服务生（注22　巡对阳乃的称呼原文为「はるさん」。此指美少女游戏《美少女万华镜》登场角色「稻森… | The name Senpai mentioned couldn't possibly refer to a certain waitress… |
| 475 | 67559.report.json:326 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 比起温柔，她给人的感觉更像是「突击！（注23　原文为「ヤシャシーン」，《亚尔斯兰战记》中军队突击时的呐喊声，音近「温柔（やさしい）」。）」一般… | Rather than kindness, it felt more like a "CHARGE!! (Note 23: The origi… |
| 476 | 68077.report.json:219 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 材木座装模作样地干咳两声。 | Zaimokuza gave a theatrical little cough. |
| 477 | 68461.report.json:227 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「啊，对了，小雪乃。」 | “Oh, that reminds me,小雪乃.” |
| 478 | 68461.report.json:234 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 听到由比滨害羞地这么说，雪之下轻轻摇头，要她别放在心上，然后露出无力的微笑。 | At Yukinoshita’s shy remark, 雪之下 gave a small shake of her head, signal… |
| 479 | 68461.report.json:236 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下的表情带有一抹寂寞与不甘。如果自己的母亲和姐姐也像她们家那样，就算不是雪之下，恐怕也很难好好相处。我和由比滨不由得闭口不语。 | There was a trace of loneliness and regret in that expression. If her o… |
| 480 | 68461.report.json:237 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注意到这阵沉默，雪之下赶紧转换话题。 | Noticing the silence, 雪之下 hastened to change the subject. |
| 481 | 68461.report.json:242 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 突如其来的提议让雪之下感到困惑，稍微犹豫了一下。她的视线游移不定，还伦偷瞄了我一眼，似乎正在大伤脑筋，呃……就算你看我，我也没办法给你意见…… | The sudden offer left 雪之下 uncertain, and she hesitated for a moment. He… |
| 482 | 68461.report.json:243 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 不过，从稍早雪之下跟阳乃的对话看来，即使让她在这种状况下回家，显然也只会重演同样的事。再说，从由比滨的语气听起来，她好像也有自己的打算。我偷偷… | But from the conversation between 雪之下 and 阳乃 earlier, sending her home … |
| 483 | 68461.report.json:247 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨也同意我说的话，雪之下抱着膝盖想了一会儿，最后终于轻轻点头。 | Yukinoshita agreed with me, and 雪之下 hugged her knees in thought for a w… |
| 484 | 68461.report.json:249 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 她从书包拿出手机，开始拨打电话。对方八成是阳乃吧。电话响了几声后，对方总算接起电话。雪之下抬起低着的头，开口说道： | She took out her phone from her school bag and started dialing. It was … |
| 485 | 68461.report.json:252 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我看向声音的主人，由比滨一脸讶异地交互看着我和雪之下。正要问她发生什么事时，电话另一端的人先发出兴致缺缺的笑声。 | I turned to the source of the voice. Yukinoshita looked between me and … |
| 486 | 68461.report.json:253 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 『是吗……我知道了。比企谷肯定也在那边对吧？叫他来听。』 | ‘Is that so… I see. 比企谷’s there too, right? Put him on.’ |
| 487 | 68461.report.json:254 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 在安静的房间里，就算隔着电话，我还是能听见这句挑衅的话语。阳乃的要求让雪之下犹豫了一下。电话的另一端又传来『快点』的冰冷催促，她轻轻叹了口气，… | In the quiet room, even over the phone, I could hear that provocative r… |
| 488 | 68461.report.json:261 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我吞一口口水，下意识地看向雪之下。 | I swallowed and instinctively looked at 雪之下. |
| 489 | 68461.report.json:266 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 阳乃只说了一句话，便迳自挂断电话，为我们的对话划下休止符。 | 阳乃 said only one line, then hung up on her own initiative, drawing our … |
| 490 | 68461.report.json:267 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我用手帕把手机的荧幕擦拭干净，再还给雪之下。下一刻，疲劳感顿时涌了上来。我这才注意到，时间已经不早了。 | I wiped the phone screen with my handkerchief and handed it back to 雪之下… |
| 491 | 68461.report.json:270 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我抓起书包站起来后，由比滨跟着起身，比我们慢半拍的雪之下也站起来。看来她们想送我离开。 | I grabbed my school bag and stood up. Yukinoshita rose after me, and 雪之… |
| 492 | 68461.report.json:274 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 那是由比滨的爱犬，酥饼。酥饼就这样往我的身体撞过来。 | It was Yukinoshita’s dog, 酥饼. The dog plowed straight into me. |
| 493 | 68461.report.json:277 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨喝斥一声，抱起四脚朝天躺在我脚边的酥饼。雪之下看到这个生物，吓到动都不敢动。啊，糟糕，我记得这家伙怕狗。 | Yukinoshita scolded it and scooped up the dog, which had flipped onto i… |
| 494 | 68461.report.json:278 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 在走向家门口的途中，雪之下始终落在由比滨身后三步的距离，尽量不去接触酥饼。另一方面，酥饼则是在由比滨的怀里汪汪叫，活力十足地动个不停。嗯……这… | On the way to the front door, 雪之下 stayed three steps behind Yukinoshita… |
| 495 | 68461.report.json:280 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「由比滨，既然今天雪之下在这里过夜，酥饼……」 | “Yukinoshita, since 雪之下’s staying over tonight, 酥饼…” |
| 496 | 68461.report.json:282 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下用严厉的语气打断我的话。她微微噘起嘴唇，交抱双臂瞪视着我。原来如此，她这么不想说出自己怕狗啊……算了，对于朋友爱到不行的动物，她大概也不… | 雪之下 interrupted me in a stern tone. She pouted slightly, crossed her ar… |
| 497 | 68461.report.json:285 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「那个……酥饼怎么了吗？」 | “Um… what about 酥饼?” |
| 498 | 68461.report.json:287 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「呃……酥饼可能会觉得寂寞，但偶尔也该让它学习忍耐。尤其是这个家伙。」 | “Uh… 酥饼 might get lonely, but it’s good for it to learn patience someti… |
| 499 | 68461.report.json:290 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「……因为在家人之中，酥饼比较黏妈妈。」 | “…Because out of the whole family, 酥饼 likes Mom best.” |
| 500 | 68461.report.json:292 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 狗狗的阶级意识很强，由比滨这种人八成会被酥饼踩在脚下。既然这样，它应该就不太会接近雪之下了吧。这也是个让她习惯狗的好机会。 | Dogs have strong pack instincts, and someone like Yukinoshita would pro… |
| 501 | 68461.report.json:294 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 说完，我轻轻抚摸酥饼的头。 | I said, gently stroking 酥饼’s head. |
| 502 | 68461.report.json:297 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我在她们的目送下走出大门。即使来到外廊，还是听得到酥饼寂寞的叫声。我怀着有些挂念的心情，踏上回家的路。 | I stepped out of the house, with them seeing me off. Even out in the en… |
| 503 | 68461.report.json:300 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 难得提早回家的父母已经就寝，客厅里只有我和小雪。只不过，小雪一直在暖被桌的棉被上缩着身体睡觉，只有我还保持清醒。 | My parents, who had come home early for a change, were already asleep, … |
| 504 | 68461.report.json:301 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 客厅门突然打开，穿着睡衣和睡帽的小町走了进来。 | The living room door slid open, and 小町 walked in wearing pajamas and a … |
| 505 | 68461.report.json:304 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町直接转进厨房。 | 小町 disappeared into the kitchen. |
| 506 | 68461.report.json:308 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我还以为她要做什么料理，但随后又是一阵在橱柜找东西的声音。难道她是肚子饿睡不着吗？正当我这么想时，小町走来暖被桌这里。 | I thought she was making some kind of snack, but then came the sound of… |
| 507 | 68461.report.json:313 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町踢开我的脚，钻进暖被桌，两人开始享用热呼呼的M罐。 | 小町 kicked my feet aside and crawled under the kotatsu, and the two of u… |
| 508 | 68461.report.json:318 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 但是，小町想说的似乎不是这个。 | But that wasn’t what 小町 meant. |
| 509 | 68461.report.json:326 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我轻摇M罐，意有所指地说道，小町立刻发出不屑的笑声……等等，她刚才是不是随口说了什么很过分的话？ | I gave the can a little shake and made my point, and 小町 let out a dismi… |
| 510 | 68461.report.json:330 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町用下巴指向M罐。 | 小町 gestured with her chin at the MAX can. |
| 511 | 68461.report.json:332 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「……小町，你喜欢哥哥吗？」 | “…小町, do you love your brother?” |
| 512 | 68461.report.json:334 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町毫不考虑，露出满不在乎的笑容秒答。我不禁呜咽一声。 | 小町 answered in less than a second, with a carefree grin. I let out a ch… |
| 513 | 68461.report.json:337 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我和小町共度的十五年并没有白费。 | The fifteen years I’d spent with 小町 hadn’t been wasted. |
| 514 | 68461.report.json:340 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我们兄妹的关系，是因为有小町才得以成立。我必须感谢她的地方，实在太多太多了。 | My relationship with my sister worked because of 小町 herself. There was … |
| 515 | 68461.report.json:343 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我一秒泪崩，手指头不断在桌上画圈圈。小町不耐烦地叹了口气，然后钻出暖被桌，跑了出去。 | I burst into tears in a second, drawing circles on the table with my fi… |
| 516 | 68461.report.json:344 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 终于被妹妹抛弃了……当我绝望地趴倒在桌上时，小町又跑回来了。 | So I’d finally been abandoned by my sister… When I slumped face-first o… |
| 517 | 68461.report.json:350 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町不知为何有些不高兴地这么说。我将巧克力拥入怀中，泪眼汪汪地不断说着「我好高兴、我好高兴……」原来她早就特地为我准备好了，真是个好妹妹呀…… | 小町 sounded a little grumpy for some reason. I hugged the chocolate to m… |
| 518 | 68461.report.json:351 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我静静啜泣，小町无奈地苦笑。 | As I sobbed quietly, 小町 gave a helpless wry smile. |
| 519 | 68461.report.json:354 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 才刚说完，小町立刻自我一眼。 | The moment I finished, 小町 shot me a sharp look. |
| 520 | 68461.report.json:355 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「照哥哥这样说，不就表示小町给的巧克力没什么价值……」 | “By that logic, it means the chocolate 小町 gave you has no value…” |
| 521 | 68461.report.json:356 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「……嗯？啊，不……不是这样的。小町的巧克力是特别的。小町最棒最可爱，小町小町得第一。」 | “…Huh? Ah, no—that’s not it. 小町’s chocolate is special. She’s the best,… |
| 522 | 68461.report.json:358 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町受不了似的深深叹气。 | 小町 let out a long-suffering sigh. |
| 523 | 68461.report.json:360 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 说完，小町露出远比平时成熟的微笑。她把手撑在桌上，托住脸颊偏向一边，抬起眼睛看过来，眼神既直率又温暖。 | With that, 小町 smiled far more maturely than usual. She propped her elbo… |
| 524 | 68461.report.json:361 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 那视线让我有些难为情，猛然吐出一口气，别开视线。小町好像也有些害羞，故意咧嘴一笑。 | That look made me a little shy, and I let out a breath, looking away. 小… |
| 525 | 68461.report.json:365 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小町也一口气喝完咖啡，「嘿咻」一声站起身。 | 小町 also chugged her coffee, then stood up with a “heave-ho.” |
| 526 | 68461.report.json:366 | NON_1TO1 | 1:0 | realigned | correction | 「好啦，差不多该睡了。」 |  |
| 527 | 68461.report.json:368 | NON_1TO1 | 0:1 | realigned | correction |  | “Yeah, go on.” |
| 528 | 68461.report.json:369 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 她晃着空罐，丢进厨房的垃圾桶。当她走到客厅门口时，小雪突然醒来，跟了上去。 | She swung the empty can and tossed it into the kitchen trash. When she … |
| 529 | 68461.report.json:370 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「喔，小雪。要一起睡吗？」 | “Oh, 小雪. Wanna sleep together?” |
| 530 | 68461.report.json:371 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 小雪没有用叫声回答，而是用头在小町的腿上磨蹭。小町露出满足的微笑，抱起小雪，将手伸向门把。 | 小雪 didn’t answer with a bark, instead rubbing her head against 小町’s leg… |
| 531 | 68461.report.json:377 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「嗯，谢谢。小町会加油。晚安。」 | “Mm, thanks. 小町’ll do her best. Good night.” |
| 532 | 68461.report.json:378 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 虽然小町仅简短回应，她脸上的笑容相当沉着。小町重新抱好小雪，走回自己的房间。 | She answered briefly, but the smile on her face was calm. 小町 reposition… |
| 533 | 68461.report.json:381 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 虽然小町这么描述我，现在的我却无法怀着自信加以肯定。 | That was how 小町 described me, but right now I couldn’t proudly confirm … |
| 534 | 68461.report.json:388 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 你这样还算是比企谷八幡吗？ | Is this any way for 比企谷八幡 to act? |
| 535 | 68561.report.json:46 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「虽然有些失败就是了……」 | "I mean, they didn't come out perfect…" |
| 536 | 107651.report.json:640 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 听我这么一说，一色发起火来。 | At my words, Iroha got huffy. |
| 537 | 107651.report.json:689 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 没有把一色说到一半的话听到最后，雪之下露出了温柔的笑容。 | Yukinoshita didn't wait for Iroha to finish. She just wore a gentle smi… |
| 538 | 107651.report.json:898 | NON_1TO1 | 1:0 | realigned | correction | “啊？” |  |
| 539 | 107651.report.json:900 | NON_1TO1 | 0:1 | realigned | correction |  | “Huh?” |
| 540 | 107651.report.json:1551 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 雪之下倒也是走近了京华身边，但她的手正有些纠结的伸过去，又缩回来，这么往复着。看 / 来她应该在担心是不是能摸上去吧，真实笨拙啊。 | Yukinoshita also approached Kyouka's side, but her hand hovered hesitan… |
| 541 | 107651.report.json:1621 | NON_1TO1 | 1:0 | realigned | regression | 手忙脚乱，满脸通红的由比滨， |  |
| 542 | 107651.report.json:1714 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “真怀念呐” | "Those were the days." |
| 543 | 107651.report.json:2091 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 我能做到的事就到此为止了。接下来应该是你上场的时候了。 |  |
| 544 | 107651.report.json:2093 | NON_1TO1 | 2:1 | realigned | regression | 这个时候， / 我回想起了我和她最初的谈话。 | That was when I recalled my very first conversation with her. |
| 545 | 107651.report.json:2095 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 说了我们以外不管是谁， / 就连他都不会知道的事。 | We talked about things that no one else—not even him—would ever know. |
| 546 | 107651.report.json:2096 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 不过，她还是和当时一样， / 用有些不安的表情看着我。 | But she was still looking at me with that uneasy expression, just like … |
| 547 | 76223.report.json:56 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | “那兼职也……” / 一边随意的问着，加紧了步伐。 | "What about part-time work..." I asked casually, picking up the pace. |
| 548 | 76223.report.json:227 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这怎么行啊？ | This won't do at all. |
| 549 | 76223.report.json:235 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | “仔细想想感觉没那么冷，对，不冷。所以，拜托了，哥” / 大志挠了挠鼻子，笑着掩饰自己的尴尬。 | “Come to think of it, it's not actually that cold. Yeah, not cold at al… |
| 550 | 76223.report.json:261 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | “笨蛋哥哥，学校，这里是学校啦老哥！有义务教育人的啦！” / 小町用手在我面前挥挥，无语的看着我。 | “Idiot brother—school, it's school, bro! They're obligated to teach you… |
| 551 | 76224.report.json:2 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 翻译：新海Makoto | Translation: 新海Makoto |
| 552 | 76224.report.json:62 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨又怎么会听不懂呢。 | There was no way Yuigahama couldn't see through them. |
| 553 | 76224.report.json:263 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 雪之下和由比滨眨了眨眼。咋了？很奇怪吗？ | Yukinoshita and Yuigahama blinked. / What? Is that weird? |
| 554 | 76225.report.json:2 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 翻译：新海Makoto | Translation: 新海Makoto |
| 555 | 76225.report.json:316 | NON_1TO1 | 1:2 | realigned | regression | 平冢老师和她聊天的时候也是。 | when Hiratsuka-sensei chatted with her— / all the same. |
| 556 | 76225.report.json:403 | NON_1TO1 | 2:0 | realigned | regression | 估计， / 我永远都无法理解她吧。 |  |
| 557 | 76225.report.json:624 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “那还说个头” | "Then why'd you bring it up?" |
| 558 | 76225.report.json:755 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | “总之！还是不要去在意啦” / 由比滨像是对雪之下不放心，说出了这句话。 | "Anyway! Just try not to worry about it," Yukinoshita said, as if check… |
| 559 | 76225.report.json:907 | NON_1TO1 | 1:0 | realigned | regression | “不是假命题的否命题不一定为真吗……” |  |
| 560 | 76225.report.json:908 | NON_1TO1 | 1:2 | realigned | regression | 那个逻辑很奇怪吧。”反对的反对就是赞成！” 什么的，你又不是笨蛋波恩的爸爸……我正打算这么争论下去，雪之下和由比滨都已经死死盯着我，等待着我的… | "That logic's weird, isn't it? 'The opposition of opposition is agreeme… |
| 561 | 76225.report.json:921 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 只见雪之下短短地叹了口气道： | Yukinoshita let out a short sigh. |
| 562 | 76225.report.json:975 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 八幡照旧不知所措， | Hachiman, as usual, at a loss for words. |
| 563 | 76226.report.json:69 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 仔细看看，三浦的眼睛已经渗出了泪水。 |  |
| 564 | 76226.report.json:200 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 那不是雪之下就是由比滨了。 | That leaves Yukinoshita or Yuigahama. |
| 565 | 76227.report.json:2 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 翻译：新海Makoto | Translation: 新海Makoto |
| 566 | 76227.report.json:66 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 丑陋，可耻。 | It's ugly. / Shameful. |
| 567 | 76227.report.json:223 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | “叶、山、的、联、系、方、式、发、给、我” | "Send me Hayama's contact info." |
| 568 | 76227.report.json:404 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 冷嘲热讽地说完，雪之下无语地笑道。 | After that jab, Yukino gave a dry laugh. |
| 569 | 85063.report.json:65 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下按著太阳穴，一副无奈的样子。 | Yukinoshita pressed a hand to her temple, looking exasperated. |
| 570 | 85076.report.json:153 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不过，雪之下探出身子打断她的话。 | But Yukinoshita leaned forward, cutting off the conversation. |
| 571 | 85131.report.json:136 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 京华被骂未免太可怜，我决定先打个圆场。当避雷针和当平井坚都是我的专长【注】。不对，我的五官才没有那么深邃。【注20：避雷针（ひらいしん）与平井… | It would be too pitiful for Kekone to get scolded, so I decided to step… |
| 572 | 85131.report.json:370 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 莫名其妙。唉～搞不懂搞不懂……我感觉到沙帕里妖精【注】在旁边飞来飞去。小町不理会我，径自站起来。【注29：出自《咕噜咕噜魔法阵》，拿著扇子不断… | Ridiculous. Ugh—I don't get it, I don't get it… I could feel a Sappari … |
| 573 | 85831.report.json:296 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 然而，雪之下并非如此。 | But Yukinoshita was different. |
| 574 | 85832.report.json:442 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 至于活动流程，以声势浩大的乾杯仪式为开场，接著由学生会长及各社团社长致词。炒热气氛后会放舞曲，开始跳舞，其中再穿插摇滚乐团的现场表演，不定时的… | As for the program: it opens with a rousing toast, followed by speeches… |
| 575 | 85833.report.json:202 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 没错，成为传说中的甜品师‧光之美少女【注61：出自《KiraKira☆光之美少女 A La Mode》】…… | That's right, becoming the legendary patissier, Pretty Cure... [^61] / … |
| 576 | 85833.report.json:295 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这时，一色探出身子。 | It was then that Iroha leaned forward. |
| 577 | 85835.report.json:7 | NON_1TO1 | 1:0 | realigned | regression | 如果我的朋友遇到困难或烦恼，他一定会去帮忙。因为他是我的英雄。 |  |
| 578 | 94999.report.json:264 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 接著换成雪之下回答不出来，看似有点难为情。 | This time it was Yukinoshita's turn to hesitate, looking somewhat embar… |
| 579 | 95003.report.json:260 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我先跟户冢他们知会一声。 | I said to Hikitani and the others. |
| 580 | 95004.report.json:148 | NON_1TO1 | 2:1 | realigned | correction | 我信心十足地说，结果吓到材木座。由比滨则已经习惯了，被我吓到后立刻冷静地将话题拉回来。可是，秦野和相模依然处于惊恐状态……本以为是因为我，他们… | I spoke with total confidence, which startled Zaimokuza. Yuigahama, on … |
| 581 | 95004.report.json:150 | NON_1TO1 | 0:1 | realigned | correction |  | "Iroha..." |
| 582 | 95004.report.json:169 | NON_1TO1 | 1:0 | realigned | correction | 「有道理。」 |  |
| 583 | 95004.report.json:171 | NON_1TO1 | 0:1 | realigned | correction |  | "I can relate." |
| 584 | 95004.report.json:417 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 夕阳沉入海平面前，只有短短一瞬间，充满夕阳余晖的那个房间。 / 我看过好几次，绝对称不上特别，随处可见的黄昏。 | The brief moment before the sun sank into the horizon—the room filled w… |
| 585 | 95008.report.json:19 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 什么男人的坚持，亏我讲得出这种大话。 | What a joke, calling it "a man's conviction." |
| 586 | 95008.report.json:643 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 老实说，想起前几天的对话，我觉得在逻辑和魔法少女奈叶【注47：「逻辑（ﾛジｶﾙ）」与日本动画《魔法少女奈叶（魔法少女ﾘﾘｶﾙなのは）》部分音近… | Honestly, recalling the other day’s conversation, I felt I couldn’t bea… |
| 587 | 103223.report.json:2 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 录入：深夜读书会 | Digitized by Yoru Shokudōkai |
| 588 | 103226.report.json:144 | NON_1TO1 | 1:0 | realigned | correction | 「这样啊。」 |  |
| 589 | 103226.report.json:146 | NON_1TO1 | 0:1 | realigned | correction |  | "Glad to hear it." |
| 590 | 103226.report.json:201 | NON_1TO1 | 0:1 | realigned | regression |  | \*6: Otaku slang abbreviations: "penlight" becomes "penli," and "psylli… |
| 591 | 103226.report.json:218 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 脱口而出的，却是这样的话语。 | That's what came out instead. |
| 592 | 103228.report.json:575 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 刚才的味道跟密宝岛杀人事件（注）一样支离破碎，新的水果塔则是由巧克力温柔地包覆酥脆的塔皮与新鲜的桃子，仿佛听得见风声…… | While the earlier taste had been as fractured as the murder case on Tre… |
| 593 | 103228.report.json:576 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注： 《金田一少年之事件簿》中的分尸案。 | 注: Reference to a dismemberment case in "The Case Files of Young Kindai… |
| 594 | 103228.report.json:585 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨一副「那我就懂了」的模样，立刻动手在塔皮上涂巧克力。此情此景令我有点感动。说给他听，做给他看，让他实际操作，给予称赞，如此方能使人动手去… | Yuigahama, seeming to think she'd gotten it, immediately started spread… |
| 595 | 103228.report.json:586 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注： 日本军人山本五十六的名言。 | 注: A famous aphorism from Japanese military figure Yamamoto Isoroku. |
| 596 | 103228.report.json:681 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「我说，可以停了吗？比起Corocoro我更喜欢BomBom啊（注）。啊！啊，喂，不要，真的不要……」 | "Hey, can we stop now? I prefer BomBom over Corocoro(注). Ah! Hey, no, r… |
| 597 | 103228.report.json:682 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注： 日本漫画杂志名。「滚滚棒」日文为Corocoro。 | 注: Reference to Japanese manga magazine names. "Corocoro" also sounds l… |
| 598 | 103228.report.json:709 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「当妈妈的就是这样……我们家也是，每次回老家都会被塞一堆食物。跟Stamina太郎（注）一样。」 | "That's just how moms are... Same at my place. Every time I go back hom… |
| 599 | 103228.report.json:710 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注： 日本连锁吃到饱店家。 | 注: Reference to a Japanese all-you-can-eat chain restaurant. |
| 600 | 103228.report.json:712 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨惊恐地说，我点头表示所言不假。啊，我并不讨厌喔。因为奶奶煮的饭跟Stamina太郎都很好吃！最喜欢Stamina太郎了♥喜欢到会一屁股坐… | Yuigahama said in alarm, and I nodded in confirmation. Although, I didn… |
| 601 | 103228.report.json:713 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注： 改自Hazuki眼镜式放大镜的广告。广告中为了彰显眼镜之坚固，让人直接坐到眼镜上，最后说「最喜欢Hazuki放大镜了」。 | 注: Parody of a Hazuki magnifying glass commercial, where the narrator s… |
| 602 | 103230.report.json:19 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 一定，也许，恐怕。 |  |
| 603 | 103230.report.json:159 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 伤脑筋的是，宅男是感动感动果实能力者，随便都会被感动。 | The trouble was, otaku were users of the Moving-Moving Fruit, easily mo… |
| 604 | 103230.report.json:541 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 雪之下不是会看气氛的人，甚至可以说她不懂如何看气氛。或者该说是，她从未生活在需要看人脸色的环境。 / 在跟我和由比滨相处的近一年中，她似乎逐渐… | Yukinoshita isn't the type to read the room—you might even say she's in… |
| 605 | 103232.report.json:245 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「那我走啦。」 | "See you, then." |
| 606 | 103233.report.json:97 | NON_1TO1+MIX | 0:1 | preserved_exactly | preserved_structure |  | Note 2: The Japanese term "ぼっち" (botchi), referring to someone who is a… |
| 607 | 103233.report.json:223 | NON_1TO1 | 0:1 | realigned | regression |  | Note 4: A reference to a song played over park speakers at closing time… |
| 608 | 103236.report.json:325 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我为了赶上她，一次跨两层阶梯，奋力推着吱嘎作响的脚踏车。在顶端驻足的雪之下瞄了我一眼。 | She paused there, glancing back at me. |
| 609 | 103237.report.json:305 | NON_1TO1 | 1:0 | realigned | correction | 「一色……」 |  |
| 610 | 103237.report.json:308 | NON_1TO1 | 0:1 | realigned | correction |  | "Iroha..." |
| 611 | 103237.report.json:555 | NON_1TO1 | 0:1 | preserved_exactly | preserved_structure |  | Note: "Bikkuri Donkey" is a Japanese family restaurant chain known for … |
| 612 | 103237.report.json:560 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 注：「吓一跳驴子」为日本以汉堡排餐点为主的连锁家庭餐厅。「咖喱是饮料」、「炸猪排是饮料」分别为日本的咖喱、炸猪排店。 | Note: See above. |
| 613 | 106689.report.json:2 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 翻译&校对： @花祈梦🌸 @MOR-MAU | Translation & Proofreading: @花祈梦🌸 @MOR-MAU |
| 614 | 106689.report.json:3 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 图源：@\_os这样 | Image Source: @\_os这样 |
| 615 | 106690.report.json:62 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 秒答了。不过即便如此我还是没有把话说死。为了不吃最强宝具——政确棒，我以和叶山的相性太差为理由拒绝了。（注：原文是ポリコレ棒，是由ポリ（Pol… | I answered instantly. But even so, I hadn't completely closed the door.… |
| 616 | 110129.report.json:273 | NON_1TO1 | 2:1 | realigned | correction | 「啊～对喔。好吧，那就来吧。」 / 「嗯，就这么办。」 | "Oh, right. Well, let's just do it." |
| 617 | 110129.report.json:274 | NON_1TO1 | 0:1 | realigned | correction |  | "Yeah, let's." |
| 618 | 110130.report.json:196 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪乃看得一头雾水。 | Yukino was completely lost. |
| 619 | 110131.report.json:320 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「「下台一鞠躬。」」 | "Thank you very much!" |
| 620 | 110131.report.json:343 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「「下台一鞠躬。」」 | "Thank you very much!" |
| 621 | 110131.report.json:473 | NON_1TO1 | 2:0 | preserved_exactly | preserved_structure | 14注  指日本搞笑艺人「Desuyo。」。 / 15注  「梗」及「馅料」日文皆为Neta。 |  |
| 622 | 110132.report.json:158 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不行，吐槽不完。 | There's no end to the things I could point out. |
| 623 | 110132.report.json:265 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 一色偏偏就是在这种时候没来。 | And wouldn't you know it, Iroha chose today of all days not to show up. |
| 624 | 110132.report.json:499 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下面色凝重地思考着。 | Yukinoshita mulled it over with a serious expression. |
| 625 | 110133.report.json:404 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 语气温和。这家伙果然很宠弓滨。 | Her tone is gentle. As I thought, that girl is soft on Bowhama. |
| 626 | 110134.report.json:346 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 26注   日文的「严格（厳しい）」另有严峻、严重之意。 | Note 26: The Japanese word for "strict" (厳しい) also carries meanings of … |
| 627 | 110135.report.json:16 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下雪乃这个女人，到底在想什么？ | What exactly is going on inside Yukinoshita Yukino's head? |
| 628 | 110135.report.json:81 | NON_1TO1 | 0:1 | realigned | regression |  | 30 note: "Thank you, typhoon of gratitude" [arigatou arashi] is a playf… |
| 629 | 110188.report.json:36 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 还没穿过闸门，我就看到车站里全是足球。 / 车站的墙壁上装饰着写满留言的队旗，到处都是足球队的代表色黄色、绿色、红色。 | Even before I passed through the gate, I could see the station was cove… |
| 630 | 110188.report.json:47 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 离总武高中最近的稻毛海岸站，跟苏我站只有两站的距离。 / 苏我又只要五分钟就能到千叶站，离东京站约四十分钟，跟大都市圈也靠得很近，是内房线、外… | Inage Kaigan Station, the closest to Sōbu High, is only two stops from … |
| 631 | 110188.report.json:71 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 事情的起因是我和户冢在讨论假日要不要出去玩时，叶山不知为何跑来插嘴。 / 我有免费的入场券，一起去看足球吧，离学校也很近，一点都不可怕啦……我… | The whole thing started when me and Totsuka were discussing whether to … |
| 632 | 110188.report.json:374 | NON_1TO1 | 1:0 | realigned | correction | 「试过了……」 |  |
| 633 | 110188.report.json:376 | NON_1TO1 | 0:1 | realigned | correction |  | "That was tried too, huh..." |
| 634 | 110188.report.json:387 | NON_1TO1 | 1:0 | realigned | correction | 「试过了……」 |  |
| 635 | 110188.report.json:389 | NON_1TO1 | 0:1 | realigned | correction |  | "That was tried as well..." |
| 636 | 110191.report.json:160 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「是说这个队伍真壮观。」 | "This line is something, huh." |
| 637 | 110191.report.json:408 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「比企谷，你会跟我那些亲戚一样，说『有时间迷上一个人吃辣味拉面，不如去更容易认识男人的地方』、『「辣」字左边的辛，真不知道是在指辛辣还是辛酸呢… | 「Hikigaya, would you say what my relatives say—things like 『Instead of … |
| 638 | 110193.report.json:7 | NON_1TO1 | 1:0 | realigned | regression | 考虑到考试的话，现在开始准备别说太慢，甚至有可能太迟。 |  |
| 639 | 110193.report.json:49 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 小町拼命阻止伸手去拿热水壶的一色。 | Komachi desperately tried to stop Isshiki, who was reaching for the ket… |
| 640 | 110303.report.json:55 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 她不知为何有点脸红，移开目光。 |  |
| 641 | 110303.report.json:104 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 酥饼朝那里猛冲。 | Sable dashed straight for it. |
| 642 | 110303.report.json:312 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 好不容易带着酥饼回去找优美子。 | We finally managed to bring Sable back to Yumiko. |
| 643 | 110303.report.json:562 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 换成姬菜八成会昏倒。 | If it had been Hina, she'd probably have passed out. |
| 644 | 110303.report.json:622 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不知道在流什么口水的姬菜。 | Hina, who's always drooling for some reason. |
| 645 | 110304.report.json:8 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 一个是雪之下雪乃。 | The other is Yukino Yukinoshita. |
| 646 | 110304.report.json:99 | NON_1TO1 | 0:1 | realigned | correction |  | "……Sigh." |
| 647 | 110304.report.json:494 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 这是先到社办看书的雪之下的说法。 | That was Yukino's assessment, who had already arrived at the clubroom a… |
| 648 | 131703.report.json:39 | NON_1TO1 | 1:3 | preserved_exactly | preserved_structure | 是啦，天下一品在拉面店中属于比较独特的，听说也有人觉得它「粉粉的」，不喜欢。虽说只有一小盘，雪之下可是不小心尝到了那家店——而且还是总本店的拉… | Right, Tenka Ippin is fairly distinctive among ramen shops—I've heard s… |
| 649 | 131704.report.json:291 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 由比滨一副难以启齿的样子，支吾其词。 | Yui looked like she was struggling to find the words. |
| 650 | 131705.report.json:9 | NON_1TO1 | 0:1 | realigned | correction |  | Wait. No. That's wrong. I mixed up the names. It's Yuigahama Yui who's … |
| 651 | 131705.report.json:10 | NON_1TO1 | 1:2 | realigned | correction | 放学后，我跟平常一样前往侍奉社社办。 | — / After school, I headed to the Service Club room as usual. |
| 652 | 131705.report.json:143 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | 嗯——要从哪个地方讲起呢……啊，从头讲起就行？那就这样吧。 | — / Hmm—where should I start...? Ah, from the beginning is fine? Okay, … |
| 653 | 131705.report.json:152 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 不愧是小雪乃，懂得真多。 | Smart as always, Yukino-chan. |
| 654 | 131705.report.json:163 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 自闭男害话题扯远了。 | The recluse got me off track. |
| 655 | 131705.report.json:216 | NON_1TO1 | 0:1 | realigned | regression |  | — |
| 656 | 131706.report.json:159 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 雪之下手指抵着太阳穴，无奈地说。 | Yukinoshita presses a finger to her temple, exasperated. |
| 657 | 131706.report.json:480 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 18注  「八幡」的日文为「Hachiman」。 | 18 Note: "Hachiman" is the Japanese reading of 八幡. |
| 658 | 131707.report.json:372 | NON_1TO1 | 1:2 | realigned | regression | 等电车到的期间，我传LINE告诉妻子「我快到家啰」，将手机收进公事包。然后碰到冰冰凉凉的物体，拿出来一看，是胡子先生请的MAX咖啡。上次喝是什… | While waiting for the train, I send a LINE to my wife: "Almost home," t… |
| 659 | 110307.report.json:243 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「白看了。」 | "Reading it was a waste of time." |
| 660 | 131713.report.json:2 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我在家里的客厅耍废陪小雪玩时，待在厨房的小町「啊！」了一声。 | I was lounging in the living room playing with小雪 when Komachi, who was … |
| 661 | 131713.report.json:34 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「而且这样还能营造出反差呀。『那个八幡，对这种事一窍不通的八幡竟然为我买来这样的礼物。好高兴！』」 | "And besides, it creates a nice反差. 'That Hachiman—that Hachiman who kno… |
| 662 | 131713.report.json:384 | NON_1TO1 | 1:0 | realigned | regression | 「这样啊。加油。你妹一定也会很高兴。要在生日那天送给她对吧？」 |  |
| 663 | 131713.report.json:463 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 16注  拉法叶、米迦勒的名字皆为el结尾。 |  |
| 664 | 113474.report.json:35 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 海老名姬菜。 | Ebina Hina. |
| 665 | 113477.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # DB特典 高三篇 新1 3 前略，路途中，从千叶引以为豪的车窗看世界。 | # DB Bonus: Third Year Arc, New 1-3 / Skipping the preliminaries—on the… |
| 666 | 113477.report.json:117 | NON_1TO1 | 0:1 | preserved_exactly | preserved_structure |  | Note: A play on the common job-hunting phrase calling oneself "a cog in… |
| 667 | 115159.report.json:110 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 头疼了啊。 | This is a problem. |
| 668 | 115160.report.json:39 | NON_1TO1+MIX | 0:1 | realigned | regression |  | \*Translator's note: In Japanese, "annoying idiot" (あいてれい) can be abbre… |
| 669 | 115160.report.json:40 | MIX | 1:1 | realigned | regression | 注：Tabelog「食べログ」为日本最大的美食评论网站 | \*Translator's note: Tabelog (食べログ) is Japan's largest restaurant revie… |
| 670 | 115160.report.json:41 | NON_1TO1 | 1:0 | realigned | regression | 注：在日语中「自以为是的傻子」的罗马音可缩写成AI |  |
| 671 | 115160.report.json:77 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：咖啡店名 | \*Translator's note: KouMeiDa (口美達) is a fictional coffee shop in the s… |
| 672 | 115160.report.json:132 | NON_1TO1 | 0:1 | preserved_exactly | preserved_structure |  | \*Translator's note: A play on "Kamakura Komachi," a specialty sweet; "… |
| 673 | 115160.report.json:141 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：「口美达特制黑咖啡」和「雪屋」发音接近，分别是komekuro和kamakura | \*Translator's note: The original komekuro (口美達特製黒) and kamakura (雪屋) s… |
| 674 | 115160.report.json:200 | NON_1TO1 | 1:2 | realigned | correction | 看来我也终于迎来引入LINE的时候了……我可以用『光美』和『偶活』的表情实行表情包轰炸了吗……『甜梦猫』的表情包怎么还没出来啊…… | It looked like the time had finally come for me to get on LINE... Would… |
| 675 | 115161.report.json:236 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：neta『公主连结』佩可莉姆的口头禅，「法式酱糜（テリーヌ）」和佩可莉姆（ぺコリーヌ）发音相近 | Note: Reference to Pecorine's catchphrase from *Princess Connect! Re:Di… |
| 676 | 115161.report.json:258 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：「业」，佛教用词 | Note: "Karma" (業), a Buddhist term. |
| 677 | 115162.report.json:6 | NON_1TO1 | 1:0 | realigned | correction | 搞砸了。 |  |
| 678 | 115162.report.json:8 | NON_1TO1 | 0:1 | realigned | correction |  | I got it wrong. |
| 679 | 115162.report.json:14 | NON_1TO1 | 1:0 | realigned | correction | 搞砸了。 |  |
| 680 | 115162.report.json:16 | NON_1TO1 | 0:1 | realigned | correction |  | I got it wrong. |
| 681 | 117092.report.json:11 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：此处应该是双关，原文为「新米」，日语中一个意思为「新收的大米」，另一意思为「菜鸟、新人」 | Translator's note: This is likely a pun. The original text is "新米," whi… |
| 682 | 117092.report.json:33 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：「接连不断」的原文为「目白押し」，目白站位于东京丰岛区，目黑站位于东京目黑区，相对来说更靠近涩谷 | Translator's note: "One after another" in the original is "目白押し" (Mejir… |
| 683 | 117092.report.json:147 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：此处渡航玩了个冷笑话。原文为「スマホでスマスマ调べながら」，スマホ指智能手机，スマスマ指一档名为「SMAP×SMAP」的综艺节目，这个句… | Translator's note: Here the author makes a pun. The original is "スマホでスマ… |
| 684 | 117093.report.json:167 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 一不留神说出了声。 | It slipped out before I could stop it. |
| 685 | 117095.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # DB特典 高三篇 新4 8 随之，太阳不断地下沉着。 | # Drama CD Bonus — Third Year Arc: New 4-8 / And so, the sun kept sinki… |
| 686 | 117095.report.json:110 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 译注：双关的冷笑话，由比滨说的「放松」原文为「息抜き」，既有「休息」又有「换气」的意思。 |  |
| 687 | 117095.report.json:113 | NON_1TO1 | 2:1 | realigned | correction | 从她半张着的嘴中一起出来的，除了呆愣地呼出的气似乎还有问号。看见这跟空也上人像note一样的表情，有种强烈的冷场的感觉。 / 译注：镰仓时代的… | From her half-open mouth came not just a blank exhale but what seemed t… |
| 688 | 117095.report.json:118 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 译注：此处由比滨在模仿雪之下雪乃的说话方式 |  |
| 689 | 118463.report.json:29 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：此处原文为「迷惑！めんどい！目が离せない！」都是以「め」开头 | Translator's note: Here the original is "*迷惑！めんどい！目が離せない！*" — all start… |
| 690 | 118463.report.json:56 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：此处原文为「ぺこり」，表示点头 | Translator's note: The original here is "*ぺこり*," meaning a little bow. |
| 691 | 118464.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # DB特典 高三篇 新5 1 如此这般，侍奉部的新活动开幕了。 | # DB Special: Third Year Arc, New 5 1 / And so, with that, the Service … |
| 692 | 118464.report.json:42 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：原文为「おとみ」，富冈的正确念法是「とみおか」 | Translator's note: The text reads "おとみ" (Otomi), but Fumioka's correct … |
| 693 | 118465.report.json:0 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | # DB特典 高三篇 新5 2 出乎意料地，紧张和沉默悄然而至。 | # DB Special 高三篇 新5 2 Unexpectedly, the tension and silence crept in. |
| 694 | 118465.report.json:124 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 译注：此处原文为「真矢みき张り」，前文「附和」的原文为「贴って」，「张る」和「贴る」的读音均为はる。真矢美季是一个演员，曾写过一本书名为《只要… | Translator's note: The original line references Miki Maya, an actress w… |
| 695 | 118467.report.json:0 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | # DB特典 高三篇 新5 3 如果那距离和时间对他与她是必要的话。 | # DB Special 高三篇 新5 3 If That Distance and Time Were Necessary for Him … |
| 696 | 118468.report.json:0 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | # DB特典 高三篇 新5 4 又及，在嘲讽与喧闹中，箱子得以开启。 | # DB Bonus 高三篇 新5 4 — And in the midst of mockery and racket, the box o… |
| 697 | 118468.report.json:28 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 译注：此处原文为「ふふふ、现ナマはええのう……」，是模仿老人的口气 |  |
| 698 | 118468.report.json:37 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 「这个我好像也明白啊。」 / 我对叶山地发言点头表示赞同。这恐怕不是理解，而是共鸣吧，那确实是我可能做出来的。 | "That, I think I get," I say, nodding along with Hayama's remark. This … |
| 699 | 118468.report.json:73 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 译注：请查询「汤木佐知子」 |  |
| 700 | 119295.report.json:191 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「又没什么关系。」 | "What's the harm?" |
| 701 | 119295.report.json:205 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「这样啊，抛光。」 | "I see... Polish." |
| 702 | 126203.report.json:19 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 我根本不知道海老名的地雷区在哪里，她忽然沉默的话，会忍不住担心「咦咦……我说错话了吗……」。只有这种时候会希望「叶山同学！快来！」。 / 好吧… | I have no idea where Ebina's landmines are. If she suddenly goes quiet,… |
| 703 | 126203.report.json:457 | NON_1TO1 | 0:1 | realigned | correction |  | "Oh." |
| 704 | 126203.report.json:459 | NON_1TO1 | 1:0 | realigned | correction | 「啊。」 |  |
| 705 | 126203.report.json:1016 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 结衣学姊不解地歪著头。这还用说吗？ / 像你们那样难搞得要命、复杂得要命、满是错误的关系，哪能轻易建立。不如说并不想。我再怎么刻意兜圈子，都会… | Yui-senpai tilted her head in confusion. Was that really a question? A … |
| 706 | 126203.report.json:1106 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「原来不是呀……」 | "Oh, you're not?" |
| 707 | 126203.report.json:1158 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 动画《果然我的青春恋爱喜剧搞错了。》 / Blu－ray BOX Encore Press特典 | Anime *My Teen Romantic Comedy SNAFU* Blu-ray BOX Encore Press Bonus |
| 708 | 127901.report.json:0 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | # 结1 Yui's story Prelude | # 結1 Yui's story Prelude |
| 709 | 127904.report.json:1 | NON_1TO1 | 0:1 | realigned | correction |  | Yukino Shizuka's quiet voice reached her. |
| 710 | 127905.report.json:63 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：獾的日文汉字写成「穴熊」。 | \*Note: The Japanese kanji for badger is written "穴熊" (hole-bear). |
| 711 | 127906.report.json:124 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 双方的脸瞬间靠得那么近，对心脏是相当大的负担。 |  |
| 712 | 127907.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # 结1 Yui's story 5 某种意义上，川崎大志是个大人物。 | # Chapter 1 Yui's story 5 / In a sense, Kawasaki Taishi was a big deal. |
| 713 | 127907.report.json:16 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 应该是特地等小町回来的吧。 | So he'd waited specifically for Komachi, then. |
| 714 | 127907.report.json:216 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 好不容易咳完，我瞪了大智一眼。 | Once I'd finally stopped coughing, I glared at Taishi. |
| 715 | 127908.report.json:14 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 注：恶搞自日本偶像男子团体苦柿队的歌曲〈NAI-NAI 16〉的歌词「别慌啊世纪末要来了」。 / 注：日本摇滚乐团圣饥魔Ⅱ的歌曲〈蜡像馆〉的歌… | Note: A parody of the lyrics "Don't panic, the century's end is coming"… |
| 716 | 127908.report.json:30 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我走进客厅，不出所料，小町窝在暖桌里摸著小雪看电视。似乎是念书念到一半在休息。 | I stepped into the living room, and sure enough, Komachi was tucked und… |
| 717 | 127908.report.json:77 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 注：日本广播主持人兼恐怖主义作家。 / 注：梗出自经典的落语段子。一名男子表示自己最怕馒头，众人便找来一堆馒头吓他，馒头却被男子吃完了。其他人… | Note: A Japanese radio host and writer of horror stories. Note: A class… |
| 718 | 127908.report.json:147 | NON_1TO1 | 1:0 | realigned | correction | 可、可以理解吗……？ |  |
| 719 | 127909.report.json:158 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 通通烂到不行。 | All of it was painfully terrible. |
| 720 | 127912.report.json:177 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「雪之下同学要喝什么？」 | "What would you like, Yukinoshita?" |
| 721 | 151492.report.json:103 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 注：日文「8寸」写成「8号」，《怪兽8号》为日本漫画家松本直也的作品。 | Note: The Japanese for "8 inches" is "8号," which is the same as the tit… |
| 722 | 151494.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # 结2 Yui's story 3 在一个不巧的时机，比企谷八幡向叶山隼人攀谈。 | # Volume 2 Yui's story 3 / At an awkward moment, Hachiman Hikigaya stru… |
| 723 | 151495.report.json:315 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 我终于亲身体会到了。 | So this is what it feels like. |
| 724 | 151496.report.json:0 | NON_1TO1+MIX | 1:2 | preserved_exactly | preserved_structure | # 结2 Yui's story 5 这么说来，确实有这么一个菁英意识过剩的男人。 | # 結2 Yui's story 5 / Come to think of it, there really is a man with an… |
| 725 | 151497.report.json:0 | NON_1TO1 | 1:2 | preserved_exactly | preserved_structure | # 结2 Yui's story 6 想当然耳，平冢静也有十七岁的时候。 | # Chapter 2 Yui's story 6 / Needless to say, Hiratsuka Shizuka was also… |
| 726 | 151498.report.json:126 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「那我就恭敬不如从命了……」 | "Then I'll take you up on that..." |
| 727 | 151499.report.json:271 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 我没有跟她交谈，只是任凭摆布，看着她的一举一动。在她缠绷带的期间，粉嫩的嘴唇轻快地哼着歌。水汪汪的大眼散发光彩，不晓得在高兴什么，但她突然不安… | I didn't talk to her, just let her do her thing and watched her every m… |
| 728 | 151499.report.json:473 | NON_1TO1 | 1:0 | preserved_exactly | preserved_structure | 那人立刻放开我的手。 |  |
| 729 | 107326.report.json:81 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 千岁笑逐颜开地紧抱住真昼。 | Chitose beamed and hugged Mahiru tightly. |
| 730 | 118309.report.json:270 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 周心里觉得好险。 | Amane thought, that was close. |
| 731 | 129453.report.json:21 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「是真昼的话可以哦」 | "If it's you, Mahiru, then that's fine." |
| 732 | 128476.report.json:81 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 换句话说，只要周忍一忍就好了。 | In other words, all Amane had to do was endure. |
| 733 | 130648.report.json:210 | NON_1TO1 | 1:0 | realigned | correction | 些生硬，看得出来她分外地在意著周。 |  |
| 734 | 147106.report.json:99 | NON_1TO1 | 1:0 | realigned | ambiguous | 「物行。」 |  |
| 735 | 147273.report.json:55 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「毕竟周判若两人嘛。」 | "After all, Amane is a completely different person now." |
| 736 | 147273.report.json:66 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 而对于周来说，他的契机就是真昼罢了。 | And for Amane, that push had been Mahiru. |
| 737 | 147273.report.json:153 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「有、有什么办法嘛。」 | "I-It can't be helped, alright?" |
| 738 | 147724.report.json:254 | NON_1TO1 | 2:1 | realigned | regression | 他的确想买款式相同的筷子，但如果连尺寸都一样的话，其中一方用起来就会不顺手，所 / 以没必要讲究到这种程度。 | He did want to buy chopsticks with the same design, but if even the siz… |
| 739 | 151717.report.json:325 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 安，于是正式向本人申请进行可疑行动的许可。真昼听了以后，觉得很好玩似地笑了出来。 | Mahiru found it amusing and laughed. |
| 740 | 174912.report.json:202 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「我就恭敬不如从命了。」 | "I'll gladly accept." |
| 741 | 174914.report.json:149 | NON_1TO1 | 1:0 | realigned | regression | 「好恶。」 |  |
| 742 | 118232.report.json:190 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 政近也自觉格格不入，多多少少感觉不太自在。 | Masachika was well aware he stuck out like a sore thumb, and he felt a … |
| 743 | 118232.report.json:275 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「不用特地送我没关系的。」 | "You don't have to go out of your way to walk me home." |
| 744 | 123836.report.json:139 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「有希同学……你对久世同学……」 | "Yuki-san... what do you think of Kuse-kun...?" |
| 745 | 129260.report.json:218 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「这边才要请你多多指教。」 | I'm the one who should be asking you to take care of me. |
| 746 | 134553.report.json:108 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 居然是绫乃。 | It was Ayano, of all people. |
| 747 | 140235.report.json:249 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 政近怀着不知道是佩服还是傻眼的感想，不上不下地点了点头。 | With a mix of admiration and exasperation, Masachika nodded ambiguously. |
| 748 | 147593.report.json:128 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 政近俯视大口喘气的雄翔告知。 | Masachika looked down at Yuto, who was gasping for breath, and told him. |
| 749 | 147678.report.json:131 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「你这家伙相当不知天高地厚耶。」 | "You're quite the cheeky one, aren't you?" |
| 750 | 147929.report.json:235 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「并没有啊？」 | "No, they won't!" |
| 751 | 148995.report.json:169 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「那个，久世学弟……」 | Um, Kuse-kun... |
| 752 | 157947.report.json:91 | NON_1TO1 | 2:1 | realigned | regression | 政近不禁结巴，不过全力展现大小姐样貌的 / 堇就是这么厉害。 | Masachika stammered involuntarily, but Sumire, fully displaying her ojo… |
| 753 | 157947.report.json:119 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 毫不犹豫命令跑腿，而且还递出空玻璃杯说 / 「和这个一样的」，这是会让居酒屋店员在内心暴怒的点餐方式。雄翔对此也不禁抽动嘴角，语气稍微颤抖。 | Ordering him around without hesitation, and even handing over empty gla… |
| 754 | 157947.report.json:131 | NON_1TO1 | 2:1 | preserved_exactly | preserved_structure | 政近一边思考这种失礼的事，一边不经意转 / 身看向刚才向雄翔点饮料的另一人…… | While thinking such rude thoughts, Masachika casually turned to look at… |
| 755 | 166078.report.json:54 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 四目相对了。和肤色成分多到不行的九条同学四目相对。 | Our eyes met. I met eyes with Kujo, who was showing way too much skin. |
| 756 | 165632.report.json:260 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「可是你不觉得‘正’字很色情吗？」 | "But don't you think the character '正' is erotic?" |
| 757 | 165632.report.json:261 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 「‘正’字真的很色情吧？」 | "'正' is really erotic, isn't it?" |
| 758 | 165632.report.json:263 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | 听着兄妹抱在一起谈论「正字」的热烈话题，两位纯真的少女面面相觑，满脸困惑。 | Listening to the siblings hugging each other and having a heated discus… |
| 759 | 169477.report.json:53 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 「那我就恭敬不如从命了……」 | "Then I'll take you up on that..." |
| 760 | 167806.report.json:217 | LOW_SCORE | 1:1 | preserved_exactly | preserved_nonstructural | 政近藐视着不知何时换成死库水的有希。 | Masachika looked contemptuously at Yuki, who had somehow changed into a… |
| 761 | 171178.report.json:1 | MIX | 1:1 | preserved_exactly | preserved_nonstructural | [标题为：曲者出揃う，「曲者」有可以之人和不好惹的人等意思，此处个人理解为后者] | [The title reads: 曲者出揃う, where "曲者" can mean a skilled person or a trou… |

## 六、主要反例

- 原子覆盖仍会把同主题译注、漏译回应和相邻叙述吸入正文；
- 单个目标行同时覆盖台词和说话人归属时，原子 MDL 常错误地把归属行设为 gap；
- 源文本的排版换行会被误判为可省略尾行；
- 组合 leave-one-out 大多抑制错误吸收，但当一行同时包含必要续句和译注时会误伤；
- 当前语法无法表达“第一、第三源句共同对应目标，而中间问句漏译”的非连续关系。

机器可复核的全文、新旧操作和审阅标签保存在同名 reviewed JSON 中。
