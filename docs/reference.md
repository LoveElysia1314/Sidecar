# 开发参考

## `align_documents`

```python
from dualign.services.cli_pipeline import align_documents

result = align_documents(
    document_a_path,
    document_b_path,
    report_path,
    model=None,
    config=None,
)
```

调用成功结果含 `success`、`ops`、`status`、`reason`、`quality` 和 `report_path`。
`success` 表示报告已生成，不等于对齐已接受；应检查 `status` 的 `aligned`、
`needs_review` 或 `rejected`。缓存命中要求两份文档哈希以及模型、算法、配置来源都完全
一致。默认算法为 `mdl-v1`；`legacy-anchor-v1` 只供 CLI 显式回归。

## 报告

报告顶层 `format` 固定为 `dualign-report/v1`。加载器只接受完全匹配的版本，不迁移旧报告。关键字段：

- `documents.a/b.sha256`：规范化正文哈希；
- `ops`：不可变初始关系，`s` / `t` 是两侧原始块索引；
- `snapshot_fingerprint`：正文、关系、切分方法和来源的规范指纹；
- `repair_log`：以初始关系编号为锚点的操作序列；
- `ai_proposals` / `ai_review` / `scores`：审校状态；
- `history`：固化修改时归档的上一轮操作、策略和实际应用项。

`load_report()` 只接受当前格式。旧 JSON 应删除并重新生成。

## 重放与阅读器物化

```python
from dualign.services.report_io import (
    load_report,
    repair_state_from_report,
    materialize_reader_rows,
)
```

重放前必须验证源文档哈希。`materialize_reader_rows()` 返回两组等长字符串，仅用于兼容逐行阅读器。

## 固化 API

```python
from dualign.services.solidify import SolidifyPolicy, solidify_report

plan, result = solidify_report(
    document_a_path,
    document_b_path,
    report_path,
    SolidifyPolicy.from_preset("line-aligned"),
)
```

GUI 与 CLI 都使用该 API 和 `pair_save` 三文件事务。可用类型为 `merge_a`、`split_a`、`edit_a`、`merge_b`、`split_b`、`edit_b` 和 `delete_pair`；占位不是固化类型。双侧 N:M 结构操作只有在两侧相应类型均启用时才原子应用。报告会对固化后的未来正文重新运行正式对齐；已固化效果进入 `history`，未固化操作、待处理 AI 建议、评分以及 `flag` / `ok` 仅在双侧有序文本关系完全相同且唯一时重锚。程序不创建 `.bak`。

批量调用使用与 CLI 相同的共享计划：

```python
from dualign.services.solidify import (
    SolidifyTarget,
    apply_batch_solidification,
    plan_batch_solidification,
)

batch = plan_batch_solidification(targets, policy)
result = apply_batch_solidification(batch)
```

CLI 对应命令为 `dualign solidify-batch --entries-file chapters.json`，默认只预览，追加 `--apply` 后逐文件对提交独立事务。

详细约束见 [工作报告架构](architecture.md)。
