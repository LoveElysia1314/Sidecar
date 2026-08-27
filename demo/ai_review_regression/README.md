# AI 审校回归语料

这是一份与生产文档隔离的、300×300 逻辑行双语语料。`manifest.json` 固定了对齐快照、预置状态、待审区域和验收条件，目前覆盖 22 类结构、语义、上下文和误报场景。

语料由脚本生成；修改案例后请重新生成，并将脚本与三个输出文件一起提交：

```powershell
.venv\Scripts\python.exe scripts\generate_ai_review_regression_fixture.py
```

普通测试只验证语料与契约的一致性，不会请求 AI。实时评测会使用当前配置的 AI 审校服务，可能产生费用，因此必须显式运行：

```powershell
.venv\Scripts\python.exe scripts\evaluate_ai_review_prompt.py
```

可使用 `--prompt` 测试候选提示词，使用可重复的 `--case` 只测指定案例。完整 JSON 报告默认写入 `.artifacts/ai-prompt-eval/latest.json`。

若要用内置《与天使相遇》真实文本检查旧有的 6 个人工验收点，运行：

```powershell
.venv\Scripts\python.exe scripts\evaluate_ai_review_demo.py
```
