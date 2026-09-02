# Dualign 实验资源

本目录统一收纳仍需复现价值、但尚未成为产品契约的实验代码、数据契约、评测报告和证据。
正式行为仍以 `src/`、`tests/` 和 `docs/` 中的产品文档为准；实验结果不能直接解释为部署承诺。

## 当前归档

| 实验 | 状态 | 结论 |
| --- | --- | --- |
| [alignment-judge](alignment-judge/README.md) | 2026-09-01 收口 | 保留 embedding 主干；离线生成式判别采用强制单选提示词，尚不进入生产链 |
| [solidification-integrity](solidification-integrity/README.md) | 2026-08-31 完成 | 当前固化事务会同时安装两侧正文和重建后的报告 |

## 目录约定

- 每条实验线独占一个子目录，协议、报告、工具、测试和证据不再分散到仓库其他位置。
- 可提交文件不得包含语料正文、密钥、权重、checkpoint、缓存或个人绝对路径。
- 需要正文才能复现的资产放在实验自己的 `private/` 下，并由根 `.gitignore` 忽略。
- `MIGRATION.json` 或等价 manifest 记录来源、SHA-256、包含/排除范围和迁移状态。
- 只有经过独立验证和产品接入评审的结论才迁入正式 `docs/` 或 `src/`。
