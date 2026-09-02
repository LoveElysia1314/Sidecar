"""
Dualign — AiRepairAgent: Tool-Calling 智能校订代理

设计原则:
  - 两层文本模型：初始文本（对齐器原始）+ 当前拟修复（待审校）
  - AI 只需要判断「当前文本每对 src/tgt 语义对应吗？」
  - 工具以稳定关系 ID 绑定初始关系，在同一拟修复状态上确定性重放
  - 无 auto_note、无 would_*、无策略名暴露给 AI

用法:
  from dualign.services.ai_repair_agent import AiRepairAgent, ChapterContext
  agent = AiRepairAgent(backend="deepseek")
  # initial_state 必须是构造 context 时的同一份拟修复状态。
  result = agent.run(chapter_context, initial_state=state)
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

from dualign.models.action import RepairAction
from dualign.models.state import AlignmentSnapshot
from dualign.models.relation_status import (
    RelationStatus,
    RelationReviewInfo,
    project_relation_statuses,
    relation_status_to_info,
    build_context_windows,
    _parse_type,
)
from dualign.services.repair_policy import choose_auto_repair, strategy_for_ai_review
from dualign.services.cancellation import CancellationError, CancellationToken

logger = logging.getLogger(__name__)


# ── DeepSeek 定价（$ / token）──
DEEPSEEK_PRICES = {
    "prompt": 0.14 / 1e6,
    "completion": 0.28 / 1e6,
    "cache": 0.0028 / 1e6,
}


def compute_cost(
    prompt_tokens: int, cache_tokens: int, completion_tokens: int
) -> float:
    """计算 DeepSeek API 调用费用。"""
    prices = DEEPSEEK_PRICES
    return (
        (prompt_tokens - cache_tokens) * prices["prompt"]
        + cache_tokens * prices["cache"]
        + completion_tokens * prices["completion"]
    )


# ═══════════════════════════════════════════════════════════════
# 1. 数据结构
# ═══════════════════════════════════════════════════════════════


@dataclass
class AgentRunResult:
    """One review conversation's explicit completion state."""

    status: str
    actions: List[RepairAction] = field(default_factory=list)
    reviewed_ids: tuple[int, ...] = ()
    pending_ids: tuple[int, ...] = ()
    turns: int = 0
    forced: bool = False
    note: str = ""
    model_name: str = ""
    prompt_sha256: str = ""
    elapsed_seconds: float = 0.0

    @property
    def is_complete(self) -> bool:
        return self.status == "completed" and not self.pending_ids


@dataclass
class AgentEvent:
    turn: int
    type: str
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_result: str = ""
    usage: dict = field(default_factory=dict)
    actions: List[RepairAction] = field(default_factory=list)
    messages: List[dict] = field(default_factory=list)
    turn_log: List[dict] = field(default_factory=list)
    review_action: Optional[RepairAction] = None
    run_result: Optional[AgentRunResult] = None
    error: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class ChapterContext:
    chapter_id: str
    chapter_title: str
    total_pairs: int
    snapshot: AlignmentSnapshot
    strategy: str = "src"
    relation_statuses: List[RelationStatus] = field(default_factory=list)
    relation_infos: List[RelationReviewInfo] = field(default_factory=list)
    reviewable_ids: List[int] = field(default_factory=list)

    def get_relation_info(self, ordinal: int) -> Optional[RelationReviewInfo]:
        if 0 <= ordinal < len(self.relation_infos):
            return self.relation_infos[ordinal]
        return None

    def get_relation_status(self, ordinal: int) -> Optional[RelationStatus]:
        if 0 <= ordinal < len(self.relation_statuses):
            return self.relation_statuses[ordinal]
        return None

    @property
    def reviewable_infos(self) -> List[RelationReviewInfo]:
        """返回需要审校的关系视图。"""
        return [
            self.relation_infos[ordinal]
            for ordinal in self.reviewable_ids
            if 0 <= ordinal < len(self.relation_infos)
        ]

    @classmethod
    def from_repair_state(
        cls,
        state,
        chapter_id="",
        chapter_title="",
        strategy="src",
        model=None,
        skip_auto_repair=False,
    ) -> "ChapterContext":
        """从 RepairState 构造 ChapterContext。

        当前文本始终设置为 auto-repair 后的结果（无论传入的 state 是否已修复）。
        初始文本保持原始对齐输出。AI 只需判断「当前文本正确吗？」。
        当前结果来源与异常信号分别提供给 AI，作为可信度先验和核查线索。

        Args:
            model: 嵌入模型，用于有多个边界方案的局部归一化。不传时，
                无新边界的 N:1 / 1:N 仍会自然合并为 1:1。
            skip_auto_repair: 为 True 时跳过内部 auto_repair（调用方已构造拟修复）。
        """
        from dualign.services.repair import RepairService

        strategy = strategy_for_ai_review(strategy)

        snapshot = state.snapshot
        total = len(snapshot.original_ops)

        if skip_auto_repair:
            repaired = state
        else:
            # 始终用 auto-repair 后的状态作为「当前文本」
            repaired = RepairService.auto_repair(
                state,
                strategy=strategy,
                model=model,
                unresolved_only=True,
            )
        ch = repaired.current

        relation_statuses = project_relation_statuses(repaired)

        relation_infos: List[RelationReviewInfo] = []
        for si in range(total):
            g = ch.group(si)
            src = (
                "\n".join(r.src_text for r in g.rows if r.src_text)
                if g is not None
                else ""
            )
            tgt = (
                "\n".join(r.tgt_text for r in g.rows if r.tgt_text)
                if g is not None
                else ""
            )
            info = relation_status_to_info(relation_statuses[si], si, src, tgt)
            # 初始文本
            s_idx, t_idx, _ = snapshot.original_ops[si]
            info.initial_src_text = (
                "\n".join(snapshot.src_text(i) for i in s_idx) if s_idx else ""
            )
            info.initial_tgt_text = (
                "\n".join(snapshot.tgt_text(j) for j in t_idx) if t_idx else ""
            )
            info.initial_n_src = len(s_idx)
            info.initial_n_tgt = len(t_idx)
            relation_infos.append(info)
        reviewable_ids = [
            si for si, info in enumerate(relation_infos) if info.is_reviewable
        ]
        return cls(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            total_pairs=total,
            snapshot=snapshot,
            strategy=strategy,
            relation_statuses=relation_statuses,
            relation_infos=relation_infos,
            reviewable_ids=reviewable_ids,
        )

    def append_reviewable(self, ordinal: int) -> bool:
        if ordinal in self.reviewable_ids:
            return False
        if not self.get_relation_info(ordinal):
            return False
        self.reviewable_ids.append(ordinal)
        self.reviewable_ids.sort()
        return True

    def select_reviewable(self, ordinals: Iterable[int]) -> None:
        """以调用方显式指定的文本对替换天然异常集合。"""
        self.reviewable_ids = []
        for ordinal in sorted(set(ordinals)):
            self.append_reviewable(ordinal)


@dataclass(frozen=True)
class AgentReviewSession:
    """Agent 一次审核所需的不可分割输入。

    ``context`` 是 AI 看到的拟修复文本，``proposed_state`` 是工具执行器
    用来解释 ``ok`` 的同一份状态。调用方不应分别构造二者。
    """

    context: ChapterContext
    proposed_state: object


# ═══════════════════════════════════════════════════════════════
# 公共构造器 — 确保嵌入模型就绪
# ═══════════════════════════════════════════════════════════════


def build_agent_review_session(
    state,
    strategy: str = "src",
    model=None,
    chapter_id: str = "",
    chapter_title: str = "",
    reviewable_ids: Iterable[int] | None = None,
) -> AgentReviewSession:
    """同时构造 Agent 上下文和与之完全一致的拟修复状态。

    该函数不自动加载嵌入模型；调用方可显式传入 model。
    返回的 ``proposed_state`` 必须原样传给 ``AiRepairAgent.run``。
    """
    from dualign.services.repair import RepairService

    strategy = strategy_for_ai_review(strategy)

    proposed_state = RepairService.auto_repair(
        state,
        strategy=strategy,
        model=model,
        unresolved_only=True,
    )
    context = ChapterContext.from_repair_state(
        proposed_state,
        chapter_id=chapter_id,
        chapter_title=chapter_title,
        strategy=strategy,
        model=model,
        skip_auto_repair=True,
    )
    if reviewable_ids is not None:
        context.select_reviewable(reviewable_ids)
    return AgentReviewSession(context=context, proposed_state=proposed_state)


def build_chapter_context(
    state,
    strategy: str = "src",
    model=None,
    chapter_id: str = "",
    chapter_title: str = "",
    skip_auto_repair: bool = False,
    reviewable_ids: Iterable[int] | None = None,
) -> ChapterContext:
    """从 RepairState 构建 ChapterContext，自动确保嵌入模型就绪。

    GUI 和 Demo 共用此入口，保证 auto_repair 内部对 N:1 / 1:M 等
    场景的 split/merge 行为一致。

    当 model 为 None 时自动尝试加载嵌入模型。若加载失败，
    需要语义边界选择的关系保持不变；唯一的无 gap 合并解仍可直接产生。

    Args:
        skip_auto_repair: 为 True 时跳过内部 auto_repair（调用方已构造拟修复）。
        reviewable_ids: 用户显式指定的待审文本对；提供后不再受异常判定限制。
    """
    strategy = strategy_for_ai_review(strategy)
    if model is None:
        try:
            from dualign.services.embedding import _try_lazy_load_model

            model = _try_lazy_load_model()
        except Exception as e:
            logger.warning(
                "嵌入模型加载失败: %s（需要语义边界选择的关系将保持不变）",
                e,
            )
    if skip_auto_repair:
        context = ChapterContext.from_repair_state(
            state,
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            strategy=strategy,
            model=model,
            skip_auto_repair=True,
        )
        if reviewable_ids is not None:
            context.select_reviewable(reviewable_ids)
        return context
    return build_agent_review_session(
        state,
        strategy=strategy,
        model=model,
        chapter_id=chapter_id,
        chapter_title=chapter_title,
        reviewable_ids=reviewable_ids,
    ).context


# ═══════════════════════════════════════════════════════════════
# 2. 工具定义 — 从外部 JSON 加载（懒加载）
# ═══════════════════════════════════════════════════════════════

_prompts_dir_cache: str | None = None


def _get_prompts_dir() -> str:
    """定位 prompts/ 目录（懒加载 + 缓存，支持 PyInstaller 打包和开发模式）。"""
    global _prompts_dir_cache
    if _prompts_dir_cache is not None:
        return _prompts_dir_cache

    # 开发模式：__file__ = .../src/dualign/services/ai_repair_agent.py
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "prompts")
    if os.path.isdir(candidate):
        _prompts_dir_cache = candidate
        return candidate

    # PyInstaller 打包：sys._MEIPASS/dualign/services/prompts
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, "dualign", "services", "prompts")
        if os.path.isdir(candidate):
            _prompts_dir_cache = candidate
            return candidate

    raise FileNotFoundError(
        f"找不到 prompts/ 目录。尝试过:\n"
        f"  1. {os.path.join(here, 'prompts')}\n"
        f"  2. {os.path.join(getattr(sys, '_MEIPASS', ''), 'dualign', 'services', 'prompts') if getattr(sys, '_MEIPASS', None) else '(无 _MEIPASS)'}"
    )


_tool_definitions_cache: list[dict] | None = None
_region_tool_definitions_cache: list[dict] | None = None
_region_tools_cache: list[dict] | None = None


def _load_tool_definitions() -> list[dict]:
    """Load the provider-neutral tool contract once."""
    global _tool_definitions_cache
    if _tool_definitions_cache is not None:
        return _tool_definitions_cache
    tools_path = os.path.join(_get_prompts_dir(), "tools.json")
    with open(tools_path, "r", encoding="utf-8") as handle:
        definitions = json.load(handle)
    for tool in definitions:
        tool.setdefault("parameters", {}).setdefault("additionalProperties", False)
    _tool_definitions_cache = definitions
    return definitions


def _get_tools_openai() -> list[dict]:
    """Load the region-oriented production Agent contract."""

    global _region_tool_definitions_cache, _region_tools_cache
    if _region_tools_cache is not None:
        return _region_tools_cache
    path = os.path.join(_get_prompts_dir(), "region-tools.json")
    with open(path, "r", encoding="utf-8") as handle:
        definitions = json.load(handle)
    for tool in definitions:
        tool.setdefault("parameters", {}).setdefault("additionalProperties", False)
    _region_tool_definitions_cache = definitions
    _region_tools_cache = [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "strict": bool(tool.get("strict", False)),
        }
        for tool in definitions
    ]
    return _region_tools_cache


def agent_contract_fingerprint(strategy: str = "src") -> str:
    """Return a stable fingerprint of the prompt and tool contract."""
    tools = _get_tools_openai()
    payload = {
        "prompt": _load_system_prompt(strategy_for_ai_review(strategy)),
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
                "strict": tool["strict"],
            }
            for tool in tools
        ],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════
# 3. 系统提示词
# ═══════════════════════════════════════════════════════════════

# 策略标签
_STRATEGY_LABEL = {
    "src": "文档 A 为准 (src)",
    "tgt": "文档 B 为准 (tgt)",
    "minimal": "最小结构修改 (minimal)",
}


def _load_system_prompt(strategy="src") -> str:
    """从 agent-prompt.md 加载系统提示词。"""
    candidate = os.path.join(_get_prompts_dir(), "agent-prompt.md")
    if not os.path.isfile(candidate):
        raise FileNotFoundError(f"agent-prompt.md not found: {candidate}")
    with open(candidate, "r", encoding="utf-8") as f:
        content = f.read()
    parts = content.split("---", 2)
    text = parts[2].strip() if len(parts) >= 3 else content.strip()
    return text


# ═══════════════════════════════════════════════════════════════
# 4. LLM Backend
# ═══════════════════════════════════════════════════════════════


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    reasoning_content: str = ""


class LLMBackend(ABC):
    @abstractmethod
    def chat(
        self, messages: List[dict], thinking: bool = False, tools: list | None = None
    ) -> LLMResponse: ...


class DeepSeekNativeBackend(LLMBackend):
    """DeepSeek Responses API 后端（兼容本地 Ollama /v1/responses）。

    协议层：内部将 chat/completions 格式的 messages 转换为 responses API 的
    input items（message / function_call / function_call_output），
    上层 AiRepairAgent 无需感知格式差异。
    """

    def __init__(
        self,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        reasoning_effort: str = "low",
        request_timeout: float = 240.0,
        cancellation_token: CancellationToken | None = None,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.MODEL = model
        self.BASE_URL = base_url
        self.reasoning_effort = reasoning_effort
        self.request_timeout = request_timeout
        self._cancellation_token = cancellation_token
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        # Ollama 本地后端：api_key 用占位符，reasoning_effort 强制 none
        self._is_ollama = "localhost" in base_url or "127.0.0.1" in base_url
        if self._is_ollama and not self._api_key:
            self._api_key = "ollama"

    @staticmethod
    def _to_responses_input(messages: list) -> list:
        """chat/completions 格式 messages -> responses API input items。"""
        items: list = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "") or ""
            if role in ("system", "developer"):
                items.append({"type": "message", "role": "system", "content": content})
            elif role == "user":
                items.append({"type": "message", "role": "user", "content": content})
            elif role == "assistant":
                items.append(
                    {"type": "message", "role": "assistant", "content": content}
                )
                for tc in m.get("tool_calls", []) or []:
                    fn = tc.get("function", {})
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id") or "",
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", "{}"),
                        }
                    )
            elif role == "tool":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": m.get("tool_call_id", ""),
                        "output": content,
                    }
                )
        return items

    def _normalize_tools(self, tools: list) -> list:
        """统一 tools 为 responses API 扁平格式。

        兼容两种输入：
          - chat/completions 嵌套: {"type":"function","function":{name,...}}
          - responses 扁平:       {"type":"function","name",...}

        DeepSeek 的稳定版 Responses 契约尚未声明 ``strict``；其 Beta
        端点和其他兼容端点可继续接收该标准字段。无论服务端能力如何，
        工具执行边界都会在本地验证参数。
        """
        out = []
        for t in tools or []:
            fn = t.get("function") if isinstance(t, dict) else None
            if isinstance(fn, dict):
                # 嵌套格式 → 扁平
                out.append(
                    {
                        "type": "function",
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                        "strict": bool(fn.get("strict", False)),
                    }
                )
            else:
                out.append(dict(t) if isinstance(t, dict) else t)
        base_url = self.BASE_URL.rstrip("/").lower()
        stable_deepseek = "api.deepseek.com" in base_url and not base_url.endswith(
            "/beta"
        )
        if self._is_ollama or stable_deepseek:
            for tool in out:
                if isinstance(tool, dict):
                    tool.pop("strict", None)
        return out

    def _chat_once(self, client, **kwargs):
        """带总时长上限的 API 调用（watchdog）。"""
        import threading

        result_box: dict = {}
        error_box: dict = {}

        def _call():
            try:
                result_box["value"] = client.responses.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                error_box["error"] = e

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        deadline = (
            time.monotonic() + self.request_timeout
            if self.request_timeout > 0
            else None
        )
        while t.is_alive():
            if self._cancellation_token is not None:
                self._cancellation_token.raise_if_cancelled()
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                client.close()
                raise TimeoutError(
                    f"DeepSeek API 调用超过 {self.request_timeout:.0f}s 未完成"
                )
            t.join(0.05 if remaining is None else min(0.05, remaining))
        if self._cancellation_token is not None:
            self._cancellation_token.raise_if_cancelled()
        if "error" in error_box:
            raise error_box["error"]
        if "value" in result_box:
            return result_box["value"]
        raise RuntimeError("DeepSeek API 调用未返回结果")

    def chat(self, messages, thinking=True, tools=None) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 库未安装，无法使用 DeepSeek 后端")
        if not self._api_key:
            raise ValueError(
                "API Key 未设置"
                + chr(10)
                + "   请在设置面板中配置 API Key，或设置环境变量 DEEPSEEK_API_KEY"
            )
        if self._cancellation_token is not None:
            self._cancellation_token.raise_if_cancelled()
        client = OpenAI(api_key=self._api_key, base_url=self.BASE_URL, max_retries=0)
        unregister = (
            self._cancellation_token.register(client.close)
            if self._cancellation_token is not None
            else lambda: None
        )
        kwargs = {
            "model": self.MODEL,
            "input": self._to_responses_input(messages),
            "reasoning": {
                "effort": (
                    self.reasoning_effort
                    if thinking and not self._is_ollama
                    else "none"
                ),
            },
            "max_output_tokens": self.max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = self._normalize_tools(tools)
        if not thinking or self._is_ollama:
            kwargs["temperature"] = self.temperature
        try:
            resp = self._chat_once(client, **kwargs)
        except CancellationError:
            raise
        except Exception as e:
            logger.warning("DeepSeek API 调用失败: %s", e)
            return LLMResponse(content="", usage={"error": str(e)})
        finally:
            unregister()
            client.close()

        # ── Responses 响应解析 ──
        usage_raw = resp.usage
        input_tokens = getattr(usage_raw, "input_tokens", 0) if usage_raw else 0
        output_tokens = getattr(usage_raw, "output_tokens", 0) if usage_raw else 0
        usage = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        if usage_raw and hasattr(usage_raw, "input_tokens_details"):
            details = usage_raw.input_tokens_details
            if details and hasattr(details, "cached_tokens"):
                usage["cached_tokens"] = details.cached_tokens

        tool_calls = []
        content_parts: list = []
        reasoning_text = ""
        for item in resp.output or []:
            itype = getattr(item, "type", "")
            if itype == "function_call":
                try:
                    args = json.loads(item.arguments) if item.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(id=item.call_id or "", name=item.name, arguments=args)
                )
            elif itype == "message":
                for c in getattr(item, "content", []) or []:
                    text = getattr(c, "text", "") or ""
                    if text:
                        content_parts.append(text)
            elif itype == "reasoning":
                for c in getattr(item, "summary", []) or []:
                    t = getattr(c, "text", "") or ""
                    if t:
                        reasoning_text += t + chr(10)
        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            reasoning_content=reasoning_text.strip(),
            usage=usage,
        )


def _coerce_target(v) -> str:
    """归一化 target 参数为字符串（兼容模型传 int / str）。"""
    if isinstance(v, bool):
        raise ValueError(f"target 不能是布尔值: {v!r}")
    return str(v).strip()


def _parse_pair_spec(spec) -> List[int]:
    if isinstance(spec, bool):
        raise ValueError(f"无法解析编号: {spec!r}")
    spec = str(spec).strip()
    indices: set[int] = set()
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if "-" in part:
            try:
                s, e = part.split("-", 1)
                indices.update(range(int(s.strip()), int(e.strip()) + 1))
            except (ValueError, TypeError):
                raise ValueError(f"无法解析范围: {part!r}")
        else:
            try:
                indices.add(int(part))
            except (ValueError, TypeError):
                raise ValueError(f"无法解析编号: {part!r}")
    return sorted(indices)


def _parse_target(target) -> tuple[List[int], bool]:
    """解析 target 字符串: "3" → ([3], False), "10-13" → ([10..13], True)"""
    target = _coerce_target(target)
    if target.isdigit():
        return [int(target)], False
    if re.match(r"^\d+-\d+$", target):
        parts = target.split("-")
        start, end = int(parts[0]), int(parts[1])
        if start > end:
            raise ValueError(f"范围起止颠倒: {target}")
        return list(range(start, end + 1)), True
    raise ValueError(f"无效 target: {target!r}")


def compute_auto_action_kind(relation_status, strategy: str) -> Optional[str]:
    """根据 RelationStatus 的 init_type 和策略推导自动修复操作。

    返回 kind 字符串（merge/split/delete/placeholder_src/placeholder_tgt），
    或 None（无需操作）。
    与 RepairService.auto_repair 的策略矩阵保持一致。
    """
    if relation_status is None:
        return None
    in_s, in_t = _parse_type(relation_status.init_type)
    plan = choose_auto_repair(in_s, in_t, strategy)
    return plan.kind if plan else None


class ToolExecutor:
    def __init__(
        self, ctx: ChapterContext, model=None, initial_state=None, strategy="src"
    ):
        self.ctx = ctx
        self._model = model
        self._state = initial_state
        self._strategy = strategy_for_ai_review(strategy)
        self.reviewed_ids: set[int] = set()
        self.reviewed_actions: Dict[int, RepairAction] = {}

    def execute(self, tool_call: ToolCall) -> str:
        handlers = {
            "view": self._handle_view,
            "ok": self._handle_ok,
            "edit": self._handle_edit,
            "merge": self._handle_merge,
            "delete": self._handle_delete,
            "flag": self._handle_flag,
            "append": self._handle_append,
            "done": self._handle_done,
        }
        handler = handlers.get(tool_call.name)
        if handler is None:
            return json.dumps(
                {"error": f"未知工具: {tool_call.name}"}, ensure_ascii=False
            )
        allowed = {
            tool["name"]: set(tool.get("parameters", {}).get("properties", {}))
            for tool in _load_tool_definitions()
        }.get(tool_call.name, set())
        unknown = sorted(set(tool_call.arguments) - allowed)
        if unknown:
            return json.dumps(
                {"error": f"工具 {tool_call.name} 包含未知参数: {unknown}"},
                ensure_ascii=False,
            )
        try:
            result = handler(tool_call.arguments)
            return (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
        except Exception as e:
            return json.dumps({"error": f"工具执行异常: {e}"}, ensure_ascii=False)

    @staticmethod
    def _get_target(args: dict) -> object | None:
        """Read the sole relation-target parameter exposed by current tools."""

        return args.get("target")

    def _make_action(
        self,
        kind: str,
        ordinals: list[int],
        *,
        source: str = "ai",
        **data,
    ) -> RepairAction:
        relation_ids = tuple(
            self.ctx.snapshot.relation_id(ordinal) for ordinal in ordinals
        )
        return RepairAction(
            kind=kind,
            source=source,
            data=data,
            relation_ids=relation_ids,
        )

    def _progress(self) -> str:
        total = len(self.ctx.reviewable_ids)
        done = len(self.reviewed_ids)
        pending = [i for i in self.ctx.reviewable_ids if i not in self.reviewed_ids]
        ps = (
            str(pending[:10]) + ("..." if len(pending) > 10 else "")
            if pending
            else "无"
        )
        return (
            f"**进度**: {done}/{total} 剩余 {len(pending)}: {ps}"
            if pending
            else f"**进度**: {done}/{total} ✅ 全部完成"
        )

    def _record_review(self, ordinals: List[int], action: RepairAction) -> None:
        for si in ordinals:
            self.reviewed_ids.add(si)
            self.reviewed_actions[si] = action

    def _unique_reviewed_actions(self) -> List[RepairAction]:
        """Return range actions once even though every ordinal indexes them."""
        actions: List[RepairAction] = []
        seen: set[int] = set()
        for action in self.reviewed_actions.values():
            identity = id(action)
            if identity not in seen:
                seen.add(identity)
                actions.append(action)
        return actions

    def _replay_reviewed_actions(self):
        """Apply reviewed actions to the initial state in insertion order."""
        state = self._state
        for action in self._unique_reviewed_actions():
            state = state.apply(action)
        return state

    def _handle_view(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ view 缺少必填参数 target (如 '1-3,5,11')。请重试。"
        try:
            ordinals = _parse_pair_spec(tgt)
        except ValueError as e:
            return f"❌ view 无法解析 target: {e}"

        # 用最新状态构建关系信息
        relation_infos = self._build_current_relation_infos()

        ordinals = [i for i in ordinals if 0 <= i < len(relation_infos)]
        if not ordinals:
            return "❌ 所有指定的文本对均不存在"
        lines = [
            str(relation_infos[sid])
            for sid in ordinals[:20]
            if relation_infos[sid] is not None
        ]
        return "\n".join(lines)

    def _build_current_relation_infos(self) -> List[RelationReviewInfo]:
        """如果有 initial_state，投影最新关系审阅视图。"""
        if self._state is None:
            return self.ctx.relation_infos
        state = self._replay_reviewed_actions()
        fresh_ctx = ChapterContext.from_repair_state(
            state,
            strategy=self._strategy,
            model=self._model,
            skip_auto_repair=True,
        )
        return fresh_ctx.relation_infos

    def _get_current_relation_action(self, ordinal: int) -> Optional[RepairAction]:
        """获取该关系当前已有的修复操作（不含 ok/flag 元操作）。

        结合 self._state（含拟修复）和 self.reviewed_actions（Agent 已执行操作），
        返回该关系的最近一次非元操作。若无修复操作（原始状态），返回 None。
        """
        if self._state is None:
            return None
        state = self._replay_reviewed_actions()
        META_KINDS = {"ok", "flag"}
        for a in reversed(state.repair_log):
            if state.action_ordinal(a) == ordinal and a.kind not in META_KINDS:
                return a
        return None

    def _handle_ok(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ ok 缺少必填参数 target (如 '7')。请重试。"
        try:
            ordinals, is_range = _parse_target(tgt)
        except ValueError as e:
            return f"❌ ok 无法解析 target: {e}"
        if is_range or len(ordinals) != 1:
            return "❌ ok 只接受单个关系，请用 target='7' 指定一个编号。"
        ordinal = ordinals[0]
        anchor = ordinal

        relation_infos = self._build_current_relation_infos()
        if not 0 <= ordinal < len(relation_infos):
            return f"❌ ok 指定的关系 {ordinal} 不存在。"
        if relation_infos[ordinal].has_missing:
            return (
                "❌ **ok 拒绝**: 该关系仍包含 ⟢MISSING⟣，不能标记为通过。\n\n"
                "请用 edit 补入真实文本，或用 flag 交由人工处理。"
            )

        # 统一语义：若关系已有拟修复，AI 的 ok 等同于审核通过该方案。
        existing = self._get_current_relation_action(ordinal)
        if existing:
            # 复制原操作的数据（split/edit 需要 new_src_lines 等）
            ra = self._make_action(existing.kind, [anchor], **existing.data)
            decision = f"通过拟修复 {existing.kind}"
        else:
            # 无拟修复 → 确认原始对齐关系，不虚构修改。
            ra = self._make_action("ok", [anchor])
            decision = "确认原始对齐关系（无修改）"

        self._record_review(ordinals, ra)
        return f"### ✅ {decision} — 关系 {ordinal}\n\n{self._progress()}"

    def _handle_edit(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ edit 缺少必填参数 target (如 '7' 或 '10-13')。请重试。"
        try:
            ordinals, is_range = _parse_target(tgt)
        except ValueError as e:
            return f"❌ edit 无法解析 target: {e}"
        already = [si for si in ordinals if si in self.reviewed_ids]
        new_src = args.get("new_src", [])
        new_tgt = args.get("new_tgt", [])
        if isinstance(new_src, str):
            new_src = [new_src]
        if isinstance(new_tgt, str):
            new_tgt = [new_tgt]

        # ── 占位符防线：新文本不得包含 ⟢MISSING⟣ 占位符 ──
        # 该符号只表示「译文缺失」，不是可固化的文本。若 AI 输出它，
        # 拒绝并提示补译，避免占位符经 edit 固化进正文。
        from dualign.models.state import MISSING as _MISSING

        offending = [
            line
            for line in (*new_src, *new_tgt)
            if isinstance(line, str) and line.strip() == _MISSING
        ]
        if offending:
            return (
                "❌ **edit 拒绝**: 新文本包含 ⟢MISSING⟣ 占位符，这不是可固化的文本。\n\n"
                "该符号只表示『译文缺失』。请提供真实译文/原文，"
                "若确实无法翻译请用 flag 标记该关系交由人工处理。"
            )

        # ── 范围编辑行数校验：范围含 N 个关系时，任一侧行数必须等于 N ──
        if is_range and (new_src or new_tgt):
            n = len(ordinals)
            if new_src and len(new_src) != n:
                return (
                    f"❌ **edit 拒绝**: 范围 {tgt} 含 {n} 个关系，"
                    f"但 new_src 提供了 {len(new_src)} 行。\n\n"
                    f"请为范围内每个关系提供一行（或改为单个 target 编辑一个关系）。"
                )
            if new_tgt and len(new_tgt) != n:
                return (
                    f"❌ **edit 拒绝**: 范围 {tgt} 含 {n} 个关系，"
                    f"但 new_tgt 提供了 {len(new_tgt)} 行。\n\n"
                    f"请为范围内每个关系提供一行（或改为单个 target 编辑一个关系）。"
                )

        # ── 行数校验：当 AI 同时传入两侧时，长度必须相等 ──
        if new_src and new_tgt and len(new_src) != len(new_tgt):
            return (
                f"❌ **edit 拒绝**: new_src ({len(new_src)} 行) 和 new_tgt ({len(new_tgt)} 行) "
                f"行数不等，无法配对。\n\n"
                f"此关系的初始文档 A 有 "
                f"{len(self.ctx.snapshot.original_ops[ordinals[0]][0])} 行。\n\n"
                f"edit 要求同时传入两侧时每行一一配对——确保两侧行数相等，"
                f"或只传需要修改的一侧。"
            )

        # ── 语义校验：当只传一侧，但原始另一侧行数多于修改侧时，结果可能不符合预期 ──
        anchor = ordinals[0]
        if not is_range:
            s_idx, t_idx, _ = self.ctx.snapshot.original_ops[anchor]
            n_orig_src = len(s_idx)
            n_orig_tgt = len(t_idx)
            if not new_src and new_tgt and n_orig_src > 1 and len(new_tgt) < n_orig_src:
                return (
                    f"⚠️ **edit 提示**: 你只提供了 {len(new_tgt)} 行新译文，"
                    f"但该关系的初始文档 A 有 {n_orig_src} 行。\n"
                    f"edit 只传 new_tgt 时原文侧保留全部初始原文——"
                    f"结果将是 {n_orig_src}:{len(new_tgt)} 而非 1:1。\n\n"
                    f"如需产出 1:1：提供 {n_orig_src} 行新译文（每行对应一段原文），"
                    f"或 edit 同时传两侧明确配对。"
                )
            if not new_tgt and new_src and n_orig_tgt > 1 and len(new_src) < n_orig_tgt:
                return (
                    f"⚠️ **edit 提示**: 你只提供了 {len(new_src)} 行新原文，"
                    f"但该关系的初始文档 B 有 {n_orig_tgt} 行。\n"
                    f"edit 只传 new_src 时译文侧保留全部初始译文——"
                    f"结果将是 {len(new_src)}:{n_orig_tgt} 而非 1:1。\n\n"
                    f"如需产出 1:1：提供 {n_orig_tgt} 行新原文（每行对应一段译文），"
                    f"或 edit 同时传两侧明确配对。"
                )

        if is_range:
            for i, si in enumerate(ordinals):
                if si in self.reviewed_ids:
                    continue
                _src = [new_src[i]] if i < len(new_src) and new_src[i] else []
                _tgt = [new_tgt[i]] if i < len(new_tgt) and new_tgt[i] else []
                ra = self._make_action(
                    "edit", [si], new_src_lines=_src, new_tgt_lines=_tgt
                )
                self.reviewed_ids.add(si)
                self.reviewed_actions[si] = ra
        else:
            # ── 填充缺失侧：AI 只传一侧时，从当前上下文补充另一侧（保留自动修复结果）──
            if (not new_src or not new_tgt) and not is_range:
                info = self.ctx.get_relation_info(anchor)
                if info:
                    if not new_src:
                        new_src = [s for s in info.src_text.split("\n") if s]
                    if not new_tgt:
                        new_tgt = [t for t in info.tgt_text.split("\n") if t]
            ra = self._make_action(
                "edit",
                [anchor],
                new_src_lines=new_src,
                new_tgt_lines=new_tgt,
            )
            self._record_review(ordinals, ra)

        suffix = " (已覆盖之前的审校决定)" if already else ""
        return f"### ✏️ 编辑 — 关系 {ordinals}{suffix}\n\n{self._progress()}"

    def _handle_merge(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ merge 缺少必填参数 target (如 '7' 或 '10-13')。请重试。"
        try:
            ordinals, _ = _parse_target(tgt)
        except ValueError as e:
            return f"❌ merge 无法解析 target: {e}"
        already = [si for si in ordinals if si in self.reviewed_ids]
        anchor = ordinals[0]
        if len(ordinals) > 1:
            ra = self._make_action("merge", ordinals)
            self.reviewed_ids.update(ordinals)
            self.reviewed_actions[anchor] = ra
        else:
            ra = self._make_action("merge", [anchor])
            self._record_review(ordinals, ra)
        suffix = " (已覆盖之前的审校决定)" if already else ""
        return f"### 🔗 合并 — 关系 {ordinals}{suffix}\n\n{self._progress()}"

    def _handle_delete(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ delete 缺少必填参数 target (如 '7' 或 '10-13')。请重试。"
        try:
            ordinals, _ = _parse_target(tgt)
        except ValueError as e:
            return f"❌ delete 无法解析 target: {e}"
        already = [si for si in ordinals if si in self.reviewed_ids]
        anchor = ordinals[0]
        if len(ordinals) > 1:
            ra = self._make_action("delete", ordinals)
            self.reviewed_ids.update(ordinals)
            self.reviewed_actions[anchor] = ra
        else:
            ra = self._make_action("delete", [anchor])
            self._record_review(ordinals, ra)
        suffix = " (已覆盖之前的审校决定)" if already else ""
        return f"### 🗑️ 删除 — 关系 {ordinals}{suffix}\n\n{self._progress()}"

    def _handle_flag(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ flag 缺少必填参数 target (如 '7')。请重试。"
        try:
            ordinals, is_range = _parse_target(tgt)
        except ValueError as e:
            return f"❌ flag 无法解析 target: {e}"
        if is_range or len(ordinals) != 1:
            return "❌ flag 只接受单个关系，请用 target='7' 指定一个编号。"
        already = [si for si in ordinals if si in self.reviewed_ids]
        note = args.get("note", "")
        ra = self._make_action("flag", ordinals, note=note)
        self._record_review(ordinals, ra)
        suffix = " (已覆盖之前的审校决定)" if already else ""
        return f"### 🚩 标记 — 关系 {ordinals}{suffix}\n\n{self._progress()}"

    def _handle_append(self, args: dict) -> str:
        tgt = self._get_target(args)
        if tgt is None:
            return "❌ append 缺少必填参数 target (如 '7')。请重试。"
        try:
            ordinals, is_range = _parse_target(tgt)
        except ValueError as e:
            return f"❌ append 无法解析 target: {e}"
        if is_range or len(ordinals) != 1:
            return "❌ append 只接受单个关系，请用 target='7' 指定一个编号。"
        ordinal = ordinals[0]
        ok = self.ctx.append_reviewable(ordinal)
        if ok:
            info = self.ctx.get_relation_info(ordinal)
            return f"✅ 已追加关系 {ordinal} ({info.n_src_rows}:{info.n_tgt_rows}) 到待审列表"
        return f"❌ **追加失败**: 关系 {ordinal} 不存在或已在待审列表中"

    def _handle_done(self, args: dict) -> str:
        remaining = [i for i in self.ctx.reviewable_ids if i not in self.reviewed_ids]
        _f = args.get("force", False)
        force = (
            _f.strip().lower() in ("true", "1", "yes")
            if isinstance(_f, str)
            else bool(_f)
        )
        note = args.get("note", "")
        if remaining and not force:
            return (
                f"❌ **done 拒绝**: 仍有 {len(remaining)} 个待审关系未处理: "
                f"{remaining[:15]}{'...' if len(remaining) > 15 else ''}\n\n"
                f"请逐一审查这些关系后再调用 done。"
                f"如确有合理原因需要跳过，请改用 `done` 并设置 force=true，说明理由。"
            )
        suffix = " (force)" if (force and remaining) else ""
        return f"✅ done{suffix}" + (f": {note}" if note else "")


class AgentToolExecutor:
    """Production region tools with a non-advertised legacy compatibility path.

    The legacy executor remains available for old scripted callers and direct
    unit tests, but the model only receives ``region-tools.json``.  Once a run
    uses one contract it cannot mix contracts, keeping completion semantics
    deterministic.
    """

    def __init__(self, ctx, *, model=None, initial_state=None, strategy="src"):
        from dualign.services.ai_review_regions import RegionReviewExecutor

        self.ctx = ctx
        self._mode = "region"
        self._region = (
            RegionReviewExecutor(
                initial_state,
                tuple(ctx.reviewable_ids),
                strategy=strategy_for_ai_review(strategy),
            )
            if initial_state is not None
            else None
        )
        self._legacy = ToolExecutor(
            ctx,
            model=model,
            initial_state=initial_state,
            strategy=strategy,
        )

    @property
    def region_executor(self):
        return self._region

    @property
    def reviewed_ids(self) -> set[int]:
        if self._mode == "legacy" or self._region is None:
            return self._legacy.reviewed_ids
        return self._region.reviewed_ids

    def execute(self, tool_call: ToolCall) -> str:
        from dualign.services.ai_review_regions import region_tool_names

        if tool_call.name in region_tool_names():
            if self._mode == "legacy":
                return "❌ cannot mix legacy relation tools with region tools"
            if self._region is None:
                return "❌ region tools require an initial repair state"
            return self._region.execute(tool_call.name, tool_call.arguments)
        if (
            self._mode == "region"
            and self._region is not None
            and (self._region.actions or self._region.resolved_regions)
        ):
            return "❌ cannot mix region tools with legacy relation tools"
        self._mode = "legacy"
        return self._legacy.execute(tool_call)

    def _unique_reviewed_actions(self) -> List[RepairAction]:
        if self._mode == "legacy" or self._region is None:
            return self._legacy._unique_reviewed_actions()
        return self._region.unique_actions()

    def initial_payload(self) -> dict | None:
        if self._region is None:
            return None
        return self._region.initial_payload()


# ═══════════════════════════════════════════════════════════════
# 6. AiRepairAgent
# ═══════════════════════════════════════════════════════════════


class MaxTurnsExceeded(Exception):
    """Legacy exception retained for import compatibility."""


class AiRepairAgent:
    """Tool-Calling AI 校订代理。

    生产工具按区域检查、接受、编辑、延后和完成；关系级工具仅保留脚本兼容。
    使用 Responses API 后端，支持 DeepSeek 与本地 Ollama 工具调用。
    """

    def __init__(
        self,
        backend="deepseek",
        llm_backend: LLMBackend | None = None,
        temperature=0.0,
        max_turns=20,
        verbose=True,
        model=None,
        strategy="src",
        thinking=True,
        model_name: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        reasoning_effort: str = "low",
        max_tokens: int = 8192,
        request_timeout: float = 240.0,
        cancellation_token: CancellationToken | None = None,
    ):
        self.max_turns = max_turns
        self.verbose = verbose
        self._model = model
        self._model_name = model_name
        self._strategy = strategy_for_ai_review(strategy)
        self._thinking = thinking
        self._cancellation_token = cancellation_token or CancellationToken()
        if llm_backend is not None:
            self._llm = llm_backend
        elif not isinstance(backend, str) and hasattr(backend, "chat"):
            self._llm = backend
        elif backend == "deepseek":
            self._llm = DeepSeekNativeBackend(
                temperature=temperature,
                max_tokens=max_tokens,
                model=model_name,
                base_url=base_url,
                api_key=api_key,
                reasoning_effort=reasoning_effort,
                request_timeout=request_timeout,
                cancellation_token=self._cancellation_token,
            )
        else:
            raise ValueError(
                f"不支持的 AI 审校后端: {backend}；"
                "请传入 llm_backend 或使用 deepseek"
            )
        cancel_backend = getattr(self._llm, "cancel", None)
        self._unregister_backend_cancel = (
            self._cancellation_token.register(cancel_backend)
            if callable(cancel_backend)
            else lambda: None
        )
        self._idle_turns = 0

    def close(self) -> None:
        self._unregister_backend_cancel()
        close_backend = getattr(self._llm, "close", None)
        if callable(close_backend):
            close_backend()

    def run(
        self,
        ctx: ChapterContext,
        on_event: Callable[[AgentEvent], None] | None = None,
        initial_state=None,
    ) -> AgentRunResult:
        """initial_state: 启动时的 RepairState，view 用它重放已审校操作生成最新状态。"""
        run_started = time.perf_counter()
        self._cancellation_token.raise_if_cancelled()
        executor = AgentToolExecutor(
            ctx, model=self._model, initial_state=initial_state, strategy=self._strategy
        )
        messages = self._build_initial_messages(
            ctx, region_payload=executor.initial_payload()
        )
        turn_log: List[dict] = []

        def _emit(evt_type, **kw):
            if on_event:
                on_event(AgentEvent(type=evt_type, turn=kw.pop("turn", 0), **kw))

        def _finish(
            status: str,
            *,
            turn: int,
            note: str = "",
            forced: bool = False,
        ) -> AgentRunResult:
            pending = tuple(
                ordinal
                for ordinal in ctx.reviewable_ids
                if ordinal not in executor.reviewed_ids
            )
            if status == "completed" and pending:
                status = "partial"
            result = AgentRunResult(
                status=status,
                actions=executor._unique_reviewed_actions(),
                reviewed_ids=tuple(sorted(executor.reviewed_ids)),
                pending_ids=pending,
                turns=turn,
                forced=forced,
                note=note,
                model_name=self._model_name,
                prompt_sha256=agent_contract_fingerprint(self._strategy),
                elapsed_seconds=time.perf_counter() - run_started,
            )
            _emit(
                "done",
                turn=turn,
                actions=result.actions,
                messages=messages,
                turn_log=turn_log,
                run_result=result,
                elapsed_seconds=result.elapsed_seconds,
            )
            return result

        if self.verbose:
            logger.info(
                "Agent 启动: %s | %d 对 | 待审 %d",
                ctx.chapter_id,
                ctx.total_pairs,
                len(ctx.reviewable_ids),
            )

        for turn in range(1, self.max_turns + 1):
            if self._cancellation_token.is_cancelled:
                return _finish("cancelled", turn=turn - 1, note="用户已取消")
            turn_started = time.perf_counter()
            tool_seconds = 0.0
            tools = _get_tools_openai()

            def _record_turn_timing(record: dict) -> None:
                timing = record["timing"]
                timing["tool_seconds"] = round(tool_seconds, 6)
                timing["total_seconds"] = round(time.perf_counter() - turn_started, 6)

            remaining = [
                i for i in ctx.reviewable_ids if i not in executor.reviewed_ids
            ]
            # ── 更新/追加进度消息（用显式标记识别，避免脆弱的字符串匹配）──
            if remaining:
                _new_progress = (
                    f"### 待审进度: {len(executor.reviewed_ids)}/"
                    f"{len(ctx.reviewable_ids)} | 剩余: {remaining}\n"
                    "继续解决剩余审阅区域。完成后调用 finish_review。"
                )
            else:
                _new_progress = (
                    "### ✅ 待审入口已全部解决\n\n" "调用 finish_review 完成本轮审校。"
                )
            if messages[-1]["role"] == "user" and "### 待审" in messages[-1]["content"]:
                messages[-1] = {"role": "user", "content": _new_progress}
            else:
                messages.append({"role": "user", "content": _new_progress})

            _emit("llm_call", turn=turn)
            llm_started = time.perf_counter()
            try:
                response = self._llm.chat(
                    messages, thinking=self._thinking, tools=tools
                )
            except CancellationError:
                return _finish("cancelled", turn=turn, note="用户已取消")
            llm_seconds = time.perf_counter() - llm_started

            turn_record = {
                "turn": turn,
                "request_messages": json.loads(
                    json.dumps(messages, ensure_ascii=False, default=str)
                ),
                "response": {
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                    "reasoning_content": response.reasoning_content,
                    "usage": response.usage,
                },
                "tool_results": [],
                "timing": {
                    "llm_seconds": round(llm_seconds, 6),
                    "tool_seconds": 0.0,
                    "total_seconds": 0.0,
                },
            }
            turn_log.append(turn_record)

            # ── LLM 调用失败 → 立即上报错误 ──
            if response.usage and response.usage.get("error"):
                _record_turn_timing(turn_record)
                err_msg = response.usage["error"]
                logger.error("LLM 调用失败 (Turn %d): %s", turn, err_msg)
                if on_event:
                    on_event(AgentEvent(type="error", turn=turn, error=err_msg))
                return _finish("failed", turn=turn, note=err_msg)

            if self.verbose and response.usage:
                logger.info(
                    "[Turn %d] %d->%d tokens | 模型 %.2fs",
                    turn,
                    response.usage.get("prompt_tokens", 0),
                    response.usage.get("completion_tokens", 0),
                    llm_seconds,
                )

            _emit(
                "llm_response",
                turn=turn,
                usage=response.usage,
                elapsed_seconds=llm_seconds,
            )

            if not response.tool_calls:
                self._idle_turns += 1
                remaining = [
                    i for i in ctx.reviewable_ids if i not in executor.reviewed_ids
                ]

                if self._idle_turns >= 3 or (self._idle_turns >= 2 and not remaining):
                    _record_turn_timing(turn_record)
                    # 连续 3 轮空闲 → 强制退出；或 2 轮空闲且已全部完成 → 正常退出
                    if self.verbose:
                        logger.info(
                            "连续 %d 轮无工具调用，%s于 Turn %d",
                            self._idle_turns,
                            "强制退出" if remaining else "审校完成",
                            turn,
                        )
                    if remaining:
                        logger.warning(
                            "审校强制退出，仍有 %d 个待审关系未处理: %s",
                            len(remaining),
                            remaining,
                        )
                    return _finish(
                        "partial" if remaining else "completed",
                        turn=turn,
                        note=(
                            f"连续 {self._idle_turns} 轮无工具调用" if remaining else ""
                        ),
                    )

                # 空闲提示：第 1 轮温和提醒，第 2 轮强调 done(force=true) 选项
                if remaining:
                    if self._idle_turns >= 2:
                        _idle_prompt = (
                            f"### ⏳ 审校尚未完成\n\n"
                            f"**进度**: {len(executor.reviewed_ids)}/{len(ctx.reviewable_ids)}\n"
                            f"剩余 {len(remaining)} 个: {remaining[:10]}\n\n"
                            f"你已经连续 {self._idle_turns} 轮没有操作。"
                            f"请继续审查；无法可靠解决的区域应调用 defer_region。"
                        )
                    else:
                        _idle_prompt = (
                            f"### ⏳ 审校尚未完成\n\n"
                            f"**进度**: {len(executor.reviewed_ids)}/{len(ctx.reviewable_ids)}\n"
                            f"继续审校剩余 {len(remaining)} 个: {remaining[:10]}"
                        )
                else:
                    _idle_prompt = (
                        "### ✅ 待审列表已清空\n\n" "调用 finish_review 完成本轮审校。"
                    )
                if (
                    messages[-1]["role"] == "user"
                    and "### 待审" in messages[-1]["content"]
                ):
                    messages[-1] = {"role": "user", "content": _idle_prompt}
                else:
                    messages.append({"role": "user", "content": _idle_prompt})
                _record_turn_timing(turn_record)
                continue

            self._idle_turns = 0

            tc_list = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ]
            tc_msg = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": tc_list,
            }
            if getattr(response, "reasoning_content", ""):
                tc_msg["reasoning_content"] = response.reasoning_content
            messages.append(tc_msg)

            done_result = None
            done_force = False
            done_note = ""
            for tc in response.tool_calls:
                if self._cancellation_token.is_cancelled:
                    _record_turn_timing(turn_record)
                    return _finish("cancelled", turn=turn, note="用户已取消")
                _emit(
                    "tool_start", turn=turn, tool_name=tc.name, tool_args=tc.arguments
                )
                tool_started = time.perf_counter()
                result = executor.execute(tc)
                tool_elapsed = time.perf_counter() - tool_started
                tool_seconds += tool_elapsed
                if self.verbose:
                    rp = result[:120] + "..." if len(result) > 120 else result
                    logger.info(
                        "    -> %s(%s) [%.3fs] = %s",
                        tc.name,
                        tc.arguments,
                        tool_elapsed,
                        rp,
                    )
                turn_record["tool_results"].append(
                    {
                        "tool_name": tc.name,
                        "arguments": tc.arguments,
                        "result": result,
                        "elapsed_seconds": round(tool_elapsed, 6),
                    }
                )
                _emit(
                    "tool_result",
                    turn=turn,
                    tool_name=tc.name,
                    tool_args=tc.arguments,
                    tool_result=result,
                    elapsed_seconds=tool_elapsed,
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
                if tc.name in {"done", "finish_review"}:
                    done_result = result
                    raw_force = (
                        tc.arguments.get("force", False) if tc.name == "done" else False
                    )
                    done_force = (
                        raw_force.strip().lower() in ("true", "1", "yes")
                        if isinstance(raw_force, str)
                        else bool(raw_force)
                    )
                    done_note = str(tc.arguments.get("note", ""))

            _record_turn_timing(turn_record)

            # done 被接受才退出；被拒绝则继续让模型修复剩余关系。
            if done_result is not None:
                if done_result.startswith("❌"):
                    if self.verbose:
                        n_remain = len(
                            [
                                i
                                for i in ctx.reviewable_ids
                                if i not in executor.reviewed_ids
                            ]
                        )
                        logger.info("done 被拒绝（剩余 %d 个待审），继续审校", n_remain)
                    continue
                if self.verbose:
                    logger.info("AI 完成区域审校于 Turn %d", turn)
                return _finish(
                    "forced" if done_force else "completed",
                    turn=turn,
                    note=done_note,
                    forced=done_force,
                )

            region_executor = executor.region_executor
            if region_executor is not None and not region_executor.pending_region_ids:
                if self.verbose:
                    logger.info("AI 完成全部区域，自动结束于 Turn %d", turn)
                return _finish("completed", turn=turn)

        # ── 审校后校验 ──
        unreviewed = [i for i in ctx.reviewable_ids if i not in executor.reviewed_ids]
        if unreviewed:
            logger.warning(
                "审校完成但仍有 %d 个待审关系未处理: %s。请检查。",
                len(unreviewed),
                unreviewed,
            )
        return _finish(
            "partial" if unreviewed else "completed",
            turn=self.max_turns,
            note=(f"达到最大轮数 {self.max_turns}" if unreviewed else ""),
        )

    def _build_initial_messages(
        self, ctx: ChapterContext, region_payload: dict | None = None
    ) -> List[dict]:
        prompt = _load_system_prompt(self._strategy)
        user_message = (
            self._build_region_user_message(ctx, region_payload)
            if region_payload is not None
            else self._build_initial_user_message(ctx)
        )
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]

    def _build_region_user_message(self, ctx: ChapterContext, payload: dict) -> str:
        task = {
            "chapter": ctx.chapter_title or ctx.chapter_id,
            "strategy": _STRATEGY_LABEL.get(self._strategy, "原文优先"),
            **payload,
        }
        return json.dumps(task, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════════════════
    # 6. AiRepairAgent (cont.)

    def _build_initial_user_message(self, ctx: ChapterContext) -> str:
        n_reviewable = len(ctx.reviewable_ids)
        review_set = set(ctx.reviewable_ids)
        total = ctx.total_pairs

        scores = [
            float(ctx.snapshot.original_ops[si][2])
            for si in range(len(ctx.snapshot.original_ops))
        ]
        score_line = ""
        if scores:
            avg = sum(scores) / len(scores)
            # 展示待审关系的个体评分（不分桶，AI 可以自己判断）
            review_scores = [
                scores[si] for si in ctx.reviewable_ids if si < len(scores)
            ]
            if review_scores:
                score_line = (
                    f"评分 avg={avg:.0%} | 待审评级: "
                    + ", ".join(
                        f"[{si}]{scores[si]:.0%}"
                        for si in ctx.reviewable_ids[:10]
                        if si < len(scores)
                    )
                    + ("…" if len(ctx.reviewable_ids) > 10 else "")
                )
            else:
                score_line = f"评分 avg={avg:.0%}"

        merged_windows = build_context_windows(
            ctx.reviewable_ids, total, window_size=3, merge_gap_threshold=1
        )

        strategy_label = _STRATEGY_LABEL.get(self._strategy, "原文优先")
        lines = [
            f"**章节**: {ctx.chapter_title or ctx.chapter_id}"
            f" | 策略: {strategy_label}"
            f" | 共 {total} 对 | 待审 {n_reviewable} 对"
        ]
        if score_line:
            lines.append(f"**{score_line}**")
        lines.append("")
        lines.append("待审区域（>> 标记待审文本对，±3 上下文一并展示）：")
        lines.append("")

        for start, end in merged_windows:
            for si in range(start, end + 1):
                info = ctx.get_relation_info(si)
                if info is None:
                    continue
                if si not in review_set:
                    lines.append(f"   [{si}] {info.n_src_rows}:{info.n_tgt_rows}")
                    lines.append(f"    src: {info.src_text}")
                    lines.append(f"    tgt: {info.tgt_text}")
                else:
                    lines.append(f">> {info}")

        lines.append("")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 7. 操作格式化工具函数
# ═══════════════════════════════════════════════════════════════

_ACTION_ICON = {
    "ok": "✅",
    "edit": "✏️",
    "merge": "🔗",
    "split": "❓",
    "delete": "🗑️",
    "flag": "🚩",
    "view": "📖",
    "placeholder_src": "📄",
    "placeholder_tgt": "📄",
}


def format_action(a, ctx=None) -> str:
    """格式化一条操作为人类可读字符串。"""
    kind = a.kind
    icon = _ACTION_ICON.get(kind, "❓")
    ordinals: tuple[int, ...] = (
        ctx.snapshot.operation_indices(a.relation_ids) if ctx is not None else ()
    )
    anchor = ordinals[0] if ordinals else a.relation_ids[0]
    targets = list(ordinals) if ordinals else list(a.relation_ids)

    if kind == "ok" and ctx is not None:
        ss = ctx.get_relation_status(ordinals[0])
        resolved = (
            compute_auto_action_kind(ss, getattr(ctx, "strategy", "src"))
            if ss
            else None
        )
        if resolved:
            resolved_icon = _ACTION_ICON.get(resolved, "❓")
            return f"  {resolved_icon} 关系[{anchor}]  ok \u2192 {resolved}"
        return f"  {icon} 关系[{anchor}] {kind}"

    detail = ""
    if kind == "edit":
        new_src = a.data.get("new_src_lines", [])
        new_tgt = a.data.get("new_tgt_lines", [])
        sides = []
        if new_src:
            sides.append("src")
        if new_tgt:
            sides.append("tgt")
        side_label = "+".join(sides) if sides else "?"
        if new_tgt:
            detail += f" {side_label}={new_tgt[0]}"
        elif new_src:
            detail += f" {side_label}={new_src[0]}"
    elif kind == "merge":
        detail += f" {'合并' + str(targets) if len(targets) > 1 else '单关系'}"
    elif kind == "delete":
        detail += " 批量" if len(a.relation_ids) > 1 else ""
    elif kind == "flag":
        detail += f" note={a.data.get('note', '')}"

    return f"  {icon} 关系[{anchor}] {kind}{detail}"


# ═══════════════════════════════════════════════════════════════
# 8. Debug 日志导出
# ═══════════════════════════════════════════════════════════════


def _summarize_agent_timing(turn_log: list, elapsed: float) -> dict:
    """Aggregate stable timing fields without depending on a specific backend."""
    llm_seconds = sum(
        float(tr.get("timing", {}).get("llm_seconds", 0.0) or 0.0) for tr in turn_log
    )
    tool_seconds = sum(
        float(tr.get("timing", {}).get("tool_seconds", 0.0) or 0.0) for tr in turn_log
    )
    total_seconds = max(float(elapsed or 0.0), llm_seconds + tool_seconds)
    return {
        "total_seconds": round(total_seconds, 3),
        "llm_seconds": round(llm_seconds, 3),
        "tool_seconds": round(tool_seconds, 3),
        "other_seconds": round(max(0.0, total_seconds - llm_seconds - tool_seconds), 3),
    }


def dump_agent_debug(
    ctx: ChapterContext,
    actions: list,
    turn_log: list,
    path: str,
    *,
    prompt_tokens: int = 0,
    cache_tokens: int = 0,
    completion_tokens: int = 0,
    elapsed: float = 0.0,
    extra_info: str = "",
):
    """将 Agent 交互过程导出为人类可读的 Markdown 日志。

    Args:
        ctx: ChapterContext — 章节上下文
        actions: 最终操作列表
        turn_log: 每轮交互记录（由 AiRepairAgent.run 内部收集）
        path: 输出 .md 文件路径
        prompt_tokens/cache_tokens/completion_tokens: token 统计
        elapsed: 耗时（秒）
        extra_info: 额外信息（如标准答案命中率），附加在文件头
    """
    lines: list[str] = []
    timing_summary = _summarize_agent_timing(turn_log, elapsed)

    # ── 文件头统计 ──
    lines.append("# AI 审校 Debug 日志\n")
    lines.append(f"- **章节**: {ctx.chapter_id} | {ctx.chapter_title}")
    lines.append(
        f"- **总文本对数**: {ctx.total_pairs} | **待审数**: {len(ctx.reviewable_infos)}"
    )
    done = len([a for a in actions if a.kind != "ok"])
    lines.append(f"- **审校完成**: {done}/{len(ctx.reviewable_infos)}")
    lines.append(
        f"- **轮次**: {len(turn_log)} | **总耗时**: "
        f"{timing_summary['total_seconds']:.2f}s"
    )
    lines.append(
        f"- **耗时分解**: 模型等待 {timing_summary['llm_seconds']:.2f}s | "
        f"工具执行 {timing_summary['tool_seconds']:.3f}s | "
        f"准备与调度 {timing_summary['other_seconds']:.2f}s"
    )
    lines.append(
        f"- **Token**: 输入 {prompt_tokens} (缓存 {cache_tokens}) -> 输出 {completion_tokens}"
    )
    if extra_info:
        lines.append(f"- **额外**: {extra_info}")
    lines.append("")

    # ── 逐轮记录 ──
    for tr in turn_log:
        turn_n = tr.get("turn", "?")
        lines.append("---")
        lines.append(f"## Turn {turn_n}\n")

        resp = tr.get("response", {})
        usage = resp.get("usage", {})
        if usage:
            lines.append(
                f"**Token**: {usage.get('prompt_tokens', '?')} -> {usage.get('completion_tokens', '?')}\n"
            )
        turn_timing = tr.get("timing", {})
        if turn_timing:
            lines.append(
                f"**耗时**: 模型 {float(turn_timing.get('llm_seconds', 0.0)):.2f}s | "
                f"工具 {float(turn_timing.get('tool_seconds', 0.0)):.3f}s | "
                f"本轮 {float(turn_timing.get('total_seconds', 0.0)):.2f}s\n"
            )

        # 推理过程
        rc = resp.get("reasoning_content", "")
        if rc:
            lines.append("### 推理过程 (reasoning)\n")
            lines.append("```markdown")
            lines.append(rc)
            lines.append("```\n")

        # 模型回答
        cc = resp.get("content", "")
        if cc:
            lines.append("### 响应\n")
            lines.append("```markdown")
            lines.append(cc)
            lines.append("```\n")

        # 工具调用
        has_tool_results = bool(tr.get("tool_results"))
        for tc in resp.get("tool_calls", []):
            args_str = tc.get("arguments", "")
            if isinstance(args_str, dict):
                args_str = json.dumps(args_str, ensure_ascii=False)
            name = tc.get("name", "?")
            lines.append(f"**Tool:** `{name}({args_str})`\n")

        # 工具结果（inline 在对应工具调用下方）
        if has_tool_results:
            lines.append("### 工具执行结果\n")
            for trr in tr.get("tool_results", []):
                tname = trr.get("tool_name", "?")
                targs = trr.get("arguments", {})
                tres = str(trr.get("result", ""))
                tool_elapsed = float(trr.get("elapsed_seconds", 0.0) or 0.0)
                lines.append(f"**{tname}**({targs}) · {tool_elapsed:.3f}s:")
                lines.append("```")
                lines.append(tres[:500])  # 截断防止文件过大
                lines.append("```\n")

    # ── 最终操作列表 ──
    lines.append("---")
    lines.append("## 最终操作\n")
    if actions:
        for a in actions:
            lines.append(format_action(a, ctx))
    else:
        lines.append("（无操作）")
    lines.append("")

    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def dump_agent_raw(
    ctx: ChapterContext,
    actions: list,
    turn_log: list,
    path: str,
    *,
    prompt_tokens: int = 0,
    cache_tokens: int = 0,
    completion_tokens: int = 0,
    elapsed: float = 0.0,
):
    """将 Agent 交互过程导出为完整的 JSON 文件（供自动化分析）。

    JSON 结构:
    {
        "chapter_id": "...",
        "strategy": "...",
        "total_pairs": N,
        "reviewable_count": N,
        "turns": N,
        "elapsed_seconds": N.N,
        "token_usage": {...},
        "final_actions": [...],
        "turn_log": [...]    // 包含完整的 request_messages + response + tool_results
    }
    """
    timing_summary = _summarize_agent_timing(turn_log, elapsed)
    data = {
        "chapter_id": ctx.chapter_id,
        "strategy": getattr(ctx, "_strategy", ""),
        "total_pairs": ctx.total_pairs,
        "reviewable_count": len(ctx.reviewable_infos),
        "turns": len(turn_log),
        "elapsed_seconds": timing_summary["total_seconds"],
        "timing": timing_summary,
        "token_usage": {
            "prompt": prompt_tokens,
            "cache": cache_tokens,
            "completion": completion_tokens,
        },
        "final_actions": [
            {
                "relation_ids": list(a.relation_ids),
                "kind": a.kind,
                "source": a.source,
                "data": a.data,
            }
            for a in actions
        ],
        "turn_log": turn_log,
    }

    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
