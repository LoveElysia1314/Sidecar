"""
Dualign — 轻量级 .env 加载器

从项目根目录的 .env 文件中读取环境变量配置。
设计原则：
  - 零外部依赖（纯标准库实现）
  - 支持 # 注释
  - 支持 KEY=VALUE 和 KEY="VALUE" 两种格式
  - 已存在的环境变量不会被覆盖（可用 os.environ 预设）

用法:
    from scripts.env_loader import load_env
    load_env()
    iscc = os.environ.get("ISCC_PATH", "")
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def load_env(env_path: str | None = None) -> None:
    """加载 .env 文件到 os.environ（不覆盖已有变量）。

    Args:
        env_path: .env 文件路径。默认为项目根目录下的 .env。
    """
    if env_path is None:
        env_path = str(Path(__file__).resolve().parent.parent / ".env")

    env_file = Path(env_path)
    if not env_file.is_file():
        return

    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")

    with env_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = pattern.match(line)
            if match is None:
                continue
            key = match.group(1)
            value = match.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key not in os.environ:
                os.environ[key] = value
