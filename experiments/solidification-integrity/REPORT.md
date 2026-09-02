# Dualign 文本固化与报告身份审计

日期：2026-08-31
仓库：`${DUALIGN_ROOT}`
结论：`implementation-correct / no-code-change`

## 1. 结论

当前“固化修改”实现没有遗漏正文摘要或报告身份更新。固化不是只覆盖 Markdown 后继续沿用旧报告，而是把：

1. 新正文 A；
2. 新正文 B；
3. 基于两侧新正文重新构建的报告；

作为同一可回滚事务安装。任何一步失败都会回滚。

## 2. 调用链

```text
GUI _on_apply_confirmed_changes
→ build_solidification_plan
→ save_pair_transaction
→ render new documents
→ rebuild/reconcile alignment
→ build_report with new document bytes and blocks
→ transactional install of A + B + report
→ clear GUI snapshot/score cache and reload
```

关键实现：

- `src/dualign/gui/window_actions.py`：固化入口、成功后的缓存清理与重载；
- `src/dualign/services/solidify.py`：构建固化计划，固化前通过 `report_matches_documents` 拒绝外部漂移；
- `src/dualign/services/pair_save.py`：两侧正文与报告的事务保存；
- `src/dualign/services/report_io.py`：`build_report` 重建全部持久身份字段。

## 3. 固化后重建的字段

`build_report` 使用新正文摘要、新 blocks 和新 provenance 重建：

- `documents.a.sha256`；
- `documents.b.sha256`；
- 顶层 `src_hash` / `tgt_hash`；
- `relation_identity`；
- `snapshot_fingerprint`；
- `alignment_key`。

GUI 内部 `_src_hash/_tgt_hash` 是分行 embedding/cache key，不是另一套持久化正文权威；固化成功重载时也会重算。

## 4. 外部改文语义

如果正文在 Dualign 固化事务之外被编辑，旧报告不会被视为仍然有效：`report_matches_documents` 会失败，消费和
下一次固化必须重新对齐。因此历史库里报告与当前正文不匹配，不足以推出“固化漏写 hash”；还可能来自外部编辑、
旧版本流程或只复制正文未复制报告等历史操作。

## 5. 审计边界

报告 `history` 保留 repair log、policy、applied repairs 和 reconciliation 信息，但没有嵌入整份旧报告，也没有
单独记录显式 before/after document hash 对。这是历史审计粒度的增强空间，不影响当前报告与当前正文的一致性。

## 6. 验证

- 固化/保存相关目标测试：46 passed；
- Dualign 全套测试：599 passed；
- 审计前后 Git 工作树均干净；
- 未修改任何 Dualign 文件。
