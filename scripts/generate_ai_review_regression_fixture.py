"""Generate the tracked AI-review prompt regression corpus.

The corpus is intentionally synthetic: each fault is isolated by ordinary
context rows, while the manifest preserves the exact alignment snapshot and
case-level acceptance criteria.  Re-run this script after changing a case and
commit all generated files together.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "demo" / "ai_review_regression"
LINE_COUNT = 300


class CorpusBuilder:
    def __init__(self) -> None:
        self.source: list[str] = []
        self.target: list[str] = []
        self.operations: list[dict] = []
        self.cases: list[dict] = []
        self.pre_actions: list[dict] = []
        self._filler_index = 1

    def _append_operation(
        self, source: list[str], target: list[str], score: float = 0.92
    ) -> int:
        source_indices = list(range(len(self.source), len(self.source) + len(source)))
        target_indices = list(range(len(self.target), len(self.target) + len(target)))
        self.source.extend(source)
        self.target.extend(target)
        ordinal = len(self.operations)
        self.operations.append(
            {"source": source_indices, "target": target_indices, "score": score}
        )
        return ordinal

    def filler(self, count: int = 8) -> None:
        for _ in range(count):
            number = self._filler_index
            self._filler_index += 1
            self._append_operation(
                [f"记录员核对了编号 {number} 的档案，然后把它放回木架。"],
                [
                    f"The clerk checked file number {number} and returned it to the wooden shelf."
                ],
            )

    def case(
        self,
        case_id: str,
        title: str,
        category: str,
        operations: list[tuple[list[str], list[str], float]],
        expected: dict,
        *,
        flag: dict | None = None,
        review_indices: list[int] | None = None,
    ) -> list[int]:
        self.filler()
        ordinals = [
            self._append_operation(source, target, score)
            for source, target, score in operations
        ]
        review_ordinals = (
            [ordinals[index] for index in review_indices]
            if review_indices is not None
            else list(ordinals)
        )
        self.cases.append(
            {
                "id": case_id,
                "title": title,
                "category": category,
                "relations": ordinals,
                "review_relations": review_ordinals,
                "expected": expected,
            }
        )
        if flag:
            self.pre_actions.append(
                {
                    "kind": "flag",
                    "relations": review_ordinals,
                    "source": flag.get("source", "auto"),
                    "data": {
                        "note": flag.get("note", "自动质量检测：请结合上下文核查。"),
                        **flag.get("data", {}),
                    },
                }
            )
        return ordinals

    def composition_flag(
        self,
        ordinals: list[int],
        *,
        current_structure: str = "",
        alternative_structure: str = "",
        note: str = "结构证据存在分歧，请结合上下文判断。",
    ) -> None:
        first = min(ordinals)
        last = max(ordinals)
        start_source = sum(
            len(operation["source"]) for operation in self.operations[:first]
        )
        start_target = sum(
            len(operation["target"]) for operation in self.operations[:first]
        )
        end_source = sum(
            len(operation["source"]) for operation in self.operations[: last + 1]
        )
        end_target = sum(
            len(operation["target"]) for operation in self.operations[: last + 1]
        )
        self.pre_actions.append(
            {
                "kind": "flag",
                "relations": ordinals,
                "source": "auto",
                "data": {
                    "note": note,
                    "reason": "composition_disagreement",
                    "uncertain_region": {
                        "start": {"source": start_source, "target": start_target},
                        "end": {"source": end_source, "target": end_target},
                    },
                    "current_structure": current_structure,
                    "alternative_structure": alternative_structure,
                },
            }
        )


def build_corpus() -> CorpusBuilder:
    b = CorpusBuilder()

    b.case(
        "matrix_split_target",
        "独立原文句应拆分合并译文",
        "strategy_matrix",
        [
            (
                ["雨停了。", "孩子们跑进院子。"],
                ["The rain stopped. The children ran into the yard."],
                0.61,
            )
        ],
        {
            "allowed_kinds": ["split", "edit"],
            "pair_count": 2,
            "target_contains_all": ["rain", "children"],
        },
    )
    b.case(
        "matrix_merge_target",
        "同一原文句的译文断行应合并",
        "strategy_matrix",
        [
            (
                ["她推开窗户，让清晨的凉风吹进房间。"],
                [
                    "She opened the window,",
                    "letting the cool morning air into the room.",
                ],
                0.64,
            )
        ],
        {
            "allowed_kinds": ["merge", "edit"],
            "pair_count": 1,
            "target_contains_all": ["window", "morning air"],
        },
    )
    b.case(
        "matrix_fill_missing",
        "原文独有内容需要补译",
        "strategy_matrix",
        [(["她把备用钥匙藏在花盆下面。"], [], 0.0)],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 1,
            "target_contains_all": ["key", "flower"],
            "target_forbidden": ["MISSING"],
        },
    )
    b.case(
        "matrix_delete_target",
        "A 为准时删除目标侧独有广告",
        "strategy_matrix",
        [([], ["Visit our sponsor for discounted e-books."], 0.0)],
        {"allowed_kinds": ["delete"], "pair_count": 0},
    )
    b.case(
        "matrix_balanced_nm",
        "平衡 N:M 应整理为独立语义单元",
        "strategy_matrix",
        [
            (
                ["灯亮了。", "演出开始了。"],
                ["The lights came on.", "The performance began."],
                0.72,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 2,
            "target_contains_all": ["lights", "performance"],
        },
    )

    b.case(
        "source_accidental_break",
        "原文意外断行不应机械拆译文",
        "boundary_reasoning",
        [
            (
                ["天上覆盖着暗灰色的乌云，阳光照不下来，使得周围", "景色一片昏暗。"],
                [
                    "Dark gray clouds covered the sky, blocking the sunlight. The surroundings lay in gloom."
                ],
                0.55,
            )
        ],
        {
            "allowed_kinds": ["merge", "edit"],
            "pair_count": 1,
            "source_contains_all": ["周围景色"],
            "target_contains_all": ["clouds", "gloom"],
        },
    )
    b.case(
        "target_accidental_break",
        "目标侧意外断行应恢复自然句子",
        "boundary_reasoning",
        [
            (
                ["悠真确认门锁好后，才沿着昏暗的楼梯下楼。"],
                [
                    "Only after checking that the door was locked",
                    "did Yuma descend the dim stairs.",
                ],
                0.58,
            )
        ],
        {
            "allowed_kinds": ["merge", "edit"],
            "pair_count": 1,
            "target_contains_all": ["door", "stairs"],
        },
    )
    shifted = b.case(
        "cross_relation_shift",
        "相邻关系间的信息分配错误",
        "boundary_reasoning",
        [
            (
                ["爱丽丝带来了苹果、梨和一只小铃铛。"],
                ["Alice brought apples and pears. The little bell rang once."],
                0.69,
            ),
            (
                ["铃铛在晚餐前响了一声。"],
                ["Before dinner, it rang."],
                0.69,
            ),
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 2,
            "target_contains_all": ["Alice", "bell", "dinner"],
            "target_occurrences": {"rang": 1},
        },
    )
    b.composition_flag(shifted, current_structure="1:1+1:1")

    sound_shift = b.case(
        "short_sound_shift",
        "简短拟声词造成的隐蔽跨行错位",
        "boundary_reasoning",
        [
            (
                ["门缓缓打开。砰！"],
                ["The door slowly opened."],
                0.67,
            ),
            (
                ["美咲吓得回过头。"],
                ["Bang! Misaki spun around in surprise."],
                0.67,
            ),
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 2,
            "target_contains_all": ["Bang", "Misaki"],
            "target_occurrences": {"Bang": 1},
        },
    )
    b.composition_flag(sound_shift, current_structure="1:1+1:1")

    b.case(
        "context_relocation_from_previous",
        "缺失译文已错放在上一关系末尾",
        "boundary_reasoning",
        [
            (
                ["房间安静了下来。"],
                ["The room fell silent.", "Yuigahama murmured."],
                0.63,
            ),
            (["由比滨喃喃自语。"], [], 0.0),
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 2,
            "target_contains_all": ["room fell silent", "Yuigahama murmured"],
            "target_occurrences": {"Yuigahama murmured": 1},
        },
        flag={"note": "自动质量检测：目标侧存在缺失，请结合邻文核查信息归属。"},
        review_indices=[1],
    )

    b.case(
        "repeated_mixed_name",
        "目标正文连续残留源侧文字仍需转换",
        "translation_quality",
        [
            (
                [
                    "诺拉坂在车站等我们。",
                    "离开诺拉坂后，道路开始变窄。",
                    "地图把诺拉坂标在河流北面。",
                    "当地人说诺拉坂冬天经常封路。",
                    "我们在日落前翻过了诺拉坂。",
                ],
                [
                    "nora坂 was waiting for us at the station.",
                    "After leaving nora坂, the road began to narrow.",
                    "The map placed nora坂 north of the river.",
                    "Locals said nora坂 was often closed in winter.",
                    "We crossed nora坂 before sunset.",
                ],
                0.71,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 5,
            "target_forbidden": ["坂"],
            "target_contains_all": ["nora"],
        },
    )
    b.case(
        "mixed_person_name",
        "目标正文中的源侧文字需要转写",
        "translation_quality",
        [
            (
                ["英文版署名统一采用拼音。", "润色：黑玉，Accelerator"],
                [
                    "Names in the English credits are romanized consistently.",
                    "Polish: 黑玉, Accelerator",
                ],
                0.78,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 2,
            "target_forbidden": ["黑玉"],
            "target_contains_all": ["Heiyu", "Accelerator"],
        },
        flag={"source": "user", "note": "{待翻译}"},
    )
    b.case(
        "mixed_common_word",
        "英文句中的普通中文词残留",
        "translation_quality",
        [
            (
                ["她在体育课上的表现也是顶尖水平。"],
                ["She consistently performed at the top 级别 in physical education."],
                0.76,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 1,
            "target_forbidden": ["级别"],
            "target_contains_all": ["physical education"],
        },
    )
    b.case(
        "hallucinated_detail",
        "目标侧擅自增加事实",
        "translation_quality",
        [
            (
                ["她把杯子放在桌上。"],
                ["She put the cup on the table and smiled at her younger brother."],
                0.81,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 1,
            "target_forbidden": ["younger brother"],
            "target_contains_all": ["cup", "table"],
        },
        flag={"note": "自动质量检测：请核查信息是否完整对应。"},
    )
    b.case(
        "aigc_style_drift",
        "表面对齐但表达机械重复",
        "translation_quality",
        [
            (
                ["安静的房间里，她轻轻推开门。"],
                ["In the quiet room, she quietly opened the door in a quiet manner."],
                0.82,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count": 1,
            "target_forbidden": ["in a quiet manner"],
            "target_forbidden_all": [
                ["quietly", "quiet manner"],
                ["quiet room", "in a quiet manner"],
            ],
        },
        flag={"note": "自动质量检测：请核查文本是否达到可发布质量。"},
    )
    b.case(
        "target_only_stray_content",
        "B 侧多出的无对应正文应移除",
        "contextual_completeness",
        [([], ["She nodded to the guard before leaving."], 0.0)],
        {"allowed_kinds": ["delete"], "pair_count": 0},
    )
    b.case(
        "source_long_note_missing",
        "A 侧正文后的长注释不可在 B 侧遗漏",
        "contextual_completeness",
        [
            (
                [
                    "她把旧钥匙交给了守门人。（译者注：这里的‘旧钥匙’并非真实钥匙，而是北境商会代代相传的银制徽章；后文人物仍沿用这一称呼。）",
                ],
                ["She handed the old key to the gatekeeper."],
                0.57,
            )
        ],
        {
            "allowed_kinds": ["edit"],
            "pair_count_any": [1, 2],
            "target_contains_all": [
                "gatekeeper",
                "translator",
                "silver",
            ],
        },
    )

    b.case(
        "functional_script_note",
        "译注中作为说明对象的外文应保留",
        "false_positive",
        [
            (
                [
                    "译注：「友」和「トモ」发音相同，因此分别译作 old friends 和 new friends。"
                ],
                [
                    "Translator's note: 友 and トモ have the same pronunciation, so they are rendered as old friends and new friends."
                ],
                0.74,
            )
        ],
        {
            "allowed_kinds": ["ok"],
            "pair_count": 1,
            "unchanged": True,
            "target_contains_all": ["友", "トモ"],
        },
    )
    b.case(
        "functional_kaomoji",
        "颜文字是表达内容而非语言杂糅",
        "false_positive",
        [
            (
                ["她在短信末尾加上了「(＾▽＾)」。"],
                ["She ended the message with “(＾▽＾).”"],
                0.08,
            )
        ],
        {
            "allowed_kinds": ["ok"],
            "pair_count": 1,
            "unchanged": True,
            "target_contains_all": ["＾▽＾"],
        },
    )
    b.case(
        "low_score_correct",
        "低分但语义完全对应",
        "false_positive",
        [
            (
                ["「别担心。」她说。"],
                ["“Don't worry,” she said."],
                0.05,
            )
        ],
        {"allowed_kinds": ["ok"], "pair_count": 1, "unchanged": True},
    )
    b.case(
        "established_foreign_title",
        "既定外文标题不应被误译",
        "false_positive",
        [
            (
                ["她把资料夹标成「Girls Side」。"],
                ["She labeled the folder “Girls Side.”"],
                0.07,
            )
        ],
        {
            "allowed_kinds": ["ok"],
            "pair_count": 1,
            "unchanged": True,
            "target_contains_all": ["Girls Side"],
        },
    )

    duplicated = b.case(
        "composition_duplicate_name",
        "分块错误导致相邻关系重复姓名",
        "context_and_flags",
        [
            (
                ["姓名"],
                ["Name: Yukinoshita Yukino"],
                0.82,
            ),
            (["雪之下　雪乃"], [], 0.0),
        ],
        {
            "allowed_kinds": ["merge", "edit"],
            "pair_count_any": [1, 2],
            "target_occurrences": {"Yukinoshita Yukino": 1},
            "target_forbidden": ["MISSING"],
        },
    )
    b.composition_flag(
        duplicated,
        current_structure="1:1+1:0",
        alternative_structure="2:1",
    )

    while len(b.source) < LINE_COUNT and len(b.target) < LINE_COUNT:
        b.filler(1)
    if len(b.source) != LINE_COUNT or len(b.target) != LINE_COUNT:
        raise RuntimeError(
            f"unbalanced corpus: source={len(b.source)}, target={len(b.target)}"
        )
    return b


def write_markdown(path: Path, lines: list[str]) -> None:
    path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    corpus = build_corpus()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_markdown(OUTPUT / "regression.source.md", corpus.source)
    write_markdown(OUTPUT / "regression.target.md", corpus.target)
    manifest = {
        "version": 1,
        "strategy": "src",
        "logical_line_count": LINE_COUNT,
        "operations": corpus.operations,
        "pre_actions": corpus.pre_actions,
        "review_relations": sorted(
            {ordinal for case in corpus.cases for ordinal in case["review_relations"]}
        ),
        "cases": corpus.cases,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"generated {len(corpus.source)} x {len(corpus.target)} logical lines, "
        f"{len(corpus.cases)} cases"
    )


if __name__ == "__main__":
    main()
