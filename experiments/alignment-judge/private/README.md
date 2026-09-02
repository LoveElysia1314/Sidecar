# Private alignment-judge assets

本目录除本说明外均被根 `.gitignore` 忽略，包含正文或本机逐题结果，不得提交。

本机迁移后的布局：

```text
private/
├── sources/
│   ├── internal-v1/{candidate-groups.private.jsonl,split.json}
│   ├── reader-natural/cases.jsonl
│   └── validation-v4/development.cases.jsonl
└── runs/
    ├── observer-mcq-v1/
    ├── observer-wrong-union-v1/
    ├── observer-architecture-prompt-v1/
    ├── observer-expert-prompt-styles-v1/
    └── observer-bakeoff-v1/
```

文件级 SHA-256、字节数和逻辑来源记录在上级 `MIGRATION.json`。迁移只复制了可重放 observer 实验所需的数据
和输出；模型权重、缓存、LoRA/checkpoint 与其他训练资产没有进入 Dualign。

不要通过 `git add -f` 绕过忽略规则。需要共享私有资产时，应使用独立受控归档，并在恢复后核对 manifest。
