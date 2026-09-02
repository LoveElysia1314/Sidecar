import json

from dualign.models.action import RepairAction
from dualign.models.relation_status import project_relation_statuses
from dualign.models.source import SOURCE_AI, SOURCE_USER
from dualign.models.state import AlignmentSnapshot, MISSING
from dualign.services.ai_repair_agent import (
    AiRepairAgent,
    ChapterContext,
    DeepSeekNativeBackend,
    LLMBackend,
    LLMResponse,
    ToolCall,
    _get_tools_openai,
    _load_system_prompt,
    build_agent_review_session,
)
from dualign.services.ai_review_regions import (
    RegionReviewExecutor,
    build_review_regions,
)
from dualign.services.repair import (
    RepairState,
    review_flags_for_uncertain_regions,
)


def _composition_state():
    operations = [
        ((0,), (0,), 0.9),
        ((1,), (), 0.4),
        ((2,), (1,), 0.9),
    ]
    alternative = [
        ((0, 1), (0,), 0.8),
        ((2,), (1,), 0.9),
    ]
    snapshot = AlignmentSnapshot.from_alignment(
        operations,
        ["姓名", "雪之下  雪乃", "年龄"],
        ["Name: Yukinoshita Yukino", "Age: 17"],
    )
    proposal = RepairAction.make_edit(
        "L000002",
        source="auto",
        new_tgt_lines=["Yukinoshita Yukino"],
    )
    flags = review_flags_for_uncertain_regions(
        operations,
        (((0, 0), (2, 1)),),
        alternative_operations=alternative,
        relation_ids=snapshot.relation_ids,
    )
    return RepairState(snapshot, [proposal, *flags])


def test_composition_flag_becomes_one_region_with_exact_alternative_candidate():
    state = _composition_state()

    regions = build_review_regions(state, [1], strategy="tgt")

    assert len(regions) == 1
    region = regions[0]
    assert region.ordinals == (0, 1)
    assert region.trigger_ordinals == (1,)
    assert region.evidence["current_structure"] == "1:1+1:0"
    assert region.evidence["alternative_structure"] == "2:1"
    assert "结构选择尚未确定" in region.evidence["note"]
    assert "请人工复核" not in region.evidence["note"]
    assert region.flagged_ordinals == (1,)
    assert region.initial_rows[1]["tgt"] == []
    assert region.current_rows[1]["tgt"] == ["Yukinoshita Yukino"]
    by_id = {candidate.candidate_id: candidate for candidate in region.candidates}
    current_payload = by_id["current"].to_payload()
    assert current_payload["operations"] == ["edit"]
    assert "review_focus" not in current_payload
    assert "strategy_fit" not in current_payload
    assert not by_id["current"].validation_issues
    assert by_id["current"].strategy_fit == "changes_document_b_structure"
    alternative = by_id["alignment-alternative"]
    alternative_payload = alternative.to_payload()
    assert alternative_payload["operations"] == ["merge"]
    assert "review_focus" not in alternative_payload
    assert alternative.origin == "auto"
    assert alternative.actions[0].kind == "merge"
    assert alternative.strategy_fit == "preserves_document_b_structure"
    assert alternative.after_rows == (
        {
            "relation": 0,
            "src": ["姓名", "雪之下  雪乃"],
            "tgt": ["Name: Yukinoshita Yukino"],
        },
    )
    assert not alternative.validation_issues

    source_first = build_review_regions(state, [1], strategy="src")[0]
    source_candidates = {
        candidate.candidate_id: candidate for candidate in source_first.candidates
    }
    assert source_candidates["current"].strategy_fit == (
        "preserves_document_a_structure"
    )
    assert "alignment-alternative" not in source_candidates

    minimal = build_review_regions(state, [1], strategy="minimal")[0]
    minimal_candidates = {
        candidate.candidate_id: candidate for candidate in minimal.candidates
    }
    assert minimal_candidates["alignment-alternative"].strategy_fit == (
        "changed_structure_sides:1"
    )


def test_unchanged_non_1to1_relation_is_not_an_approvable_candidate():
    state = RepairState.from_ops(
        [((0, 1), (0,), 0.63)],
        ["句子前半", "句子后半"],
        ["The complete sentence."],
    )

    executor = RegionReviewExecutor(state, (0,), strategy="src")
    region = executor.regions[0]

    assert region.candidates == ()
    assert executor.initial_payload()["review_regions"][0]["candidates"] == []
    assert executor.execute(
        "accept_candidate",
        {
            "region_id": region.region_id,
            "candidate_id": "current",
            "keep_flags": False,
        },
    ).startswith("❌")

    result = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [
                {
                    "src": ["句子前半", "句子后半"],
                    "tgt": ["The complete sentence."],
                }
            ],
            "reason": "将完整对应内容整理为一个发布单元",
            "keep_flags": False,
        },
    )
    assert json.loads(result)["status"] == "applied"
    final = state.apply(executor.unique_actions()[0]).current.group(0)
    assert len(final.rows) == 1
    assert final.rows[0].cur_type == "1:1"
    assert final.rows[0].src_text == "句子前半句子后半"
    assert final.rows[0].tgt_text == "The complete sentence."


def test_unchanged_1to1_relation_can_still_be_approved_for_textual_review():
    state = RepairState.from_ops([((0,), (0,), 0.4)], ["原文"], ["Translation"])

    region = build_review_regions(state, (0,), strategy="src")[0]

    assert [candidate.candidate_id for candidate in region.candidates] == ["current"]
    payload = region.to_payload()
    assert payload["candidate_ids"] == ["current"]
    assert payload["candidates"][0]["operations"] == []


def test_empty_candidate_list_has_no_sentinel_candidate_id():
    state = RepairState.from_ops(
        [((0, 1), (0,), 0.63)],
        ["句子前半", "句子后半"],
        ["The complete sentence."],
    )

    payload = build_review_regions(state, (0,), strategy="src")[0].to_payload()

    assert payload["candidate_ids"] == []
    assert payload["candidates"] == []
    assert all(
        candidate.get("candidate_id") != "none" for candidate in payload["candidates"]
    )


def test_user_flag_note_is_exposed_as_an_explicit_review_requirement():
    state = RepairState.from_ops(
        [((0,), (0,), 0.9)],
        ["润色：黑玉, Accelerator"],
        ["Polish: 黑玉, Accelerator"],
    )
    state = state.apply(state.make_action("flag", 0, source="user", note="{待翻译}"))

    payload = build_review_regions(state, (0,), strategy="src")[0].to_payload()

    assert payload["open_flags"] == [
        {"relation": 0, "source": "user", "note": "{待翻译}"}
    ]
    assert payload["candidate_ids"] == []
    assert payload["candidates"] == []


def test_internal_flag_approval_set_is_not_exposed_to_agent_json():
    state = RepairState.from_ops(
        [((0,), (0,), 0.9)],
        ["原文"],
        ["Translation"],
    )
    flag = state.make_action("flag", 0, source="user", note="检查译名")
    flag.data["approvals"] = {"manual"}
    state = state.apply(flag)

    payload = build_review_regions(state, (0,), strategy="src")[0].to_payload()

    assert payload["evidence"] == {"note": "检查译名"}
    assert payload["open_flags"] == [
        {"relation": 0, "source": "user", "note": "检查译名"}
    ]
    json.dumps(payload, ensure_ascii=False)


def test_automatic_flag_can_still_accept_an_unchanged_correct_candidate():
    state = RepairState.from_ops([((0,), (0,), 0.9)], ["原文"], ["Translation"])
    state = state.apply(state.make_action("flag", 0, source="auto", note="请复核"))

    payload = build_review_regions(state, (0,), strategy="src")[0].to_payload()

    assert payload["open_flags"] == [
        {"relation": 0, "source": "auto", "note": "请复核"}
    ]
    assert payload["candidate_ids"] == ["current"]


def test_user_flag_can_accept_an_existing_content_repair_for_review():
    state = RepairState.from_ops([((0,), (0,), 0.9)], ["润色：黑玉"], ["Polish: 黑玉"])
    state = state.apply(
        state.make_action("edit", 0, source="user", new_tgt_lines=["Polish: Heiyu"])
    )
    state = state.apply(state.make_action("flag", 0, source="user", note="请复核译名"))

    payload = build_review_regions(state, (0,), strategy="src")[0].to_payload()

    assert payload["candidate_ids"] == ["current"]
    assert payload["candidates"][0]["operations"] == ["edit"]


def test_split_candidate_exposes_the_exact_pairwise_result_without_text_warnings():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0, 1), (0,), 0.7)],
        ["雨下得很大，", "视野变得模糊。尽管如此，她仍然很显眼。"],
        ["The rain made the view blurry. Still, she stood out."],
    )
    split = RepairAction.make_split(
        "L000001",
        source="auto",
        side="tgt",
        new_src_lines=["雨下得很大，", "视野变得模糊。尽管如此，她仍然很显眼。"],
        new_tgt_lines=["The rain made the view blurry.", "Still, she stood out."],
    )
    state = RepairState(snapshot, [split])

    candidate = build_review_regions(state, [0], strategy="src")[0].candidates[0]
    payload = candidate.to_payload()

    assert payload["operations"] == ["split"]
    assert payload["after"] == [
        {
            "relation": 0,
            "units": [
                {
                    "src": ["雨下得很大，"],
                    "tgt": ["The rain made the view blurry."],
                },
                {
                    "src": ["视野变得模糊。尽管如此，她仍然很显眼。"],
                    "tgt": ["Still, she stood out."],
                },
            ],
        }
    ]
    assert "warnings" not in payload


def test_merge_candidate_is_one_nm_unit_without_a_fake_empty_pair():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0, 1), 0.7)],
        ["完整的一段原文。"],
        ["The first target line.", "The second target line."],
    )
    state = RepairState(
        snapshot,
        [RepairAction.make_merge("L000001", source="auto", strategy="src")],
    )

    payload = (
        build_review_regions(state, [0], strategy="src")[0].candidates[0].to_payload()
    )

    assert payload["operations"] == ["merge"]
    assert payload["after"] == [
        {
            "relation": 0,
            "units": [
                {
                    "src": ["完整的一段原文。"],
                    "tgt": ["The first target line.", "The second target line."],
                }
            ],
        }
    ]


def test_accept_candidate_is_atomic_and_keeps_origin_separate_from_reviewer():
    state = _composition_state()
    executor = RegionReviewExecutor(state, (1,), strategy="tgt")
    region = executor.regions[0]

    result = executor.execute(
        "accept_candidate",
        {
            "region_id": region.region_id,
            "candidate_id": "alignment-alternative",
            "keep_flags": True,
        },
    )

    payload = json.loads(result)
    assert payload["status"] == "applied"
    assert payload["origin_preserved"] == "auto"
    assert executor.reviewed_ids == {1}
    assert executor.touched_ids == {0, 1}
    actions = executor.unique_actions()
    assert len(actions) == 1
    assert actions[0].kind == "merge"
    assert actions[0].source == "auto"
    assert actions[0].data["reviewed_by"] == ["ai"]
    final = state
    for action in actions:
        final = final.apply(action)
    assert final.flag_for_relation("L000002") is not None


def test_accept_candidate_can_explicitly_resolve_the_region_flag():
    state = _composition_state()
    executor = RegionReviewExecutor(state, (1,), strategy="tgt")
    region = executor.regions[0]

    executor.execute(
        "accept_candidate",
        {
            "region_id": region.region_id,
            "candidate_id": "alignment-alternative",
            "keep_flags": False,
        },
    )

    actions = executor.unique_actions()
    assert [action.kind for action in actions] == ["merge"]
    restored = actions[0].data["resolved_flag_actions"]
    assert restored[0]["data"]["reason"] == "composition_disagreement"
    final = state.apply(actions[0])
    assert final.flag_for_relation("L000002") is None


def test_current_user_candidate_retains_user_approval_after_ai_review():
    state = RepairState.from_ops(
        [((0,), (), 0.4)],
        ["她合上了书。"],
        [],
        log=[
            RepairAction.make_edit(
                "L000001",
                source="user",
                new_tgt_lines=["She closed the book."],
            )
        ],
    )
    executor = RegionReviewExecutor(state, (0,))
    region = executor.regions[0]

    executor.execute(
        "accept_candidate",
        {
            "region_id": region.region_id,
            "candidate_id": "current",
            "keep_flags": True,
        },
    )
    action = executor.unique_actions()[0]
    accepted = RepairState(state.snapshot, [action])

    assert action.source == "user"
    assert action.data["reviewed_by"] == ["ai"]
    assert project_relation_statuses(accepted)[0].effective_source == SOURCE_USER


def test_current_auto_candidate_projects_agent_approval_without_rewriting_origin():
    state = RepairState.from_ops(
        [((0,), (), 0.4)],
        ["她点了点头。"],
        [],
        log=[
            RepairAction.make_edit(
                "L000001", source="auto", new_tgt_lines=["She nodded."]
            )
        ],
    )
    executor = RegionReviewExecutor(state, (0,))
    region = executor.regions[0]

    executor.execute(
        "accept_candidate",
        {
            "region_id": region.region_id,
            "candidate_id": "current",
            "keep_flags": True,
        },
    )
    action = executor.unique_actions()[0]
    accepted = RepairState(state.snapshot, [action])

    assert action.source == "auto"
    assert project_relation_statuses(accepted)[0].effective_source == SOURCE_AI


def test_edit_region_emits_one_multi_relation_edit_and_validates_units():
    state = _composition_state()
    executor = RegionReviewExecutor(state, (1,))
    region = executor.regions[0]

    rejected = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [{"src": ["姓名"], "tgt": [MISSING]}],
            "reason": "bad",
            "keep_flags": True,
        },
    )
    assert rejected.startswith("❌")
    assert not executor.actions

    result = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [
                {"src": ["姓名"], "tgt": ["Name:"]},
                {"src": ["雪之下  雪乃"], "tgt": ["Yukinoshita Yukino"]},
            ],
            "reason": "保留字段粒度并消除重复",
            "keep_flags": False,
        },
    )
    assert json.loads(result)["status"] == "applied"
    actions = executor.unique_actions()
    assert [action.kind for action in actions] == ["edit"]
    action = actions[0]
    assert action.kind == "edit"
    assert action.source == "ai"
    assert action.relation_ids == ("L000001",)
    assert action.data["new_tgt_lines"] == ["Name:"]
    assert action.data["resolved_flag_actions"][0]["kind"] == "flag"
    final = state.apply(action)
    assert final.current.group(0).rows[0].tgt_text == "Name:"
    assert final.current.group(1).rows[0].tgt_text == "Yukinoshita Yukino"
    assert final.flag_for_relation("L000002") is None


def test_edit_region_can_expand_into_context_to_relocate_misassigned_text():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0, 1), 0.63), ((1,), (), 0.0)],
        ["房间安静了下来。", "由比滨喃喃自语。"],
        ["The room fell silent.", "Yuigahama murmured."],
    )
    state = RepairState(snapshot)
    executor = RegionReviewExecutor(state, (1,), strategy="src")
    region = executor.regions[0]

    assert region.ordinals == (1,)
    assert 0 in executor.initial_payload()["review_regions"][0]["context_relations"]

    result = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "relations": [0, 1],
            "units": [
                {
                    "src": ["房间安静了下来。"],
                    "tgt": ["The room fell silent."],
                },
                {
                    "src": ["由比滨喃喃自语。"],
                    "tgt": ["Yuigahama murmured."],
                },
            ],
            "reason": "将错放在上一关系的译文移回对应语义单元",
            "keep_flags": False,
        },
    )

    assert json.loads(result)["status"] == "applied"
    action = executor.unique_actions()[0]
    assert action.kind == "edit"
    assert action.relation_ids == ("L000001", "L000002")
    assert action.data["new_src_lines"] == ["房间安静了下来。", "由比滨喃喃自语。"]
    assert action.data["new_tgt_lines"] == [
        "The room fell silent.",
        "Yuigahama murmured.",
    ]
    assert executor.touched_ids == {0, 1}
    final_rows = state.apply(action).current.group(0).rows
    assert [(row.src_text, row.tgt_text) for row in final_rows] == [
        ("房间安静了下来。", "The room fell silent."),
        ("由比滨喃喃自语。", "Yuigahama murmured."),
    ]


def test_edit_region_rejects_invalid_context_expansions():
    state = RepairState.from_ops(
        [((index,), (index,), 0.5) for index in range(4)],
        [f"A{index}" for index in range(4)],
        [f"B{index}" for index in range(4)],
    )
    executor = RegionReviewExecutor(state, (1, 3), strategy="src")
    region = executor.regions[0]
    base_args = {
        "region_id": region.region_id,
        "units": [{"src": ["A1"], "tgt": ["B1 revised"]}],
        "reason": "test",
        "keep_flags": True,
    }

    assert "contiguous" in executor.execute(
        "edit_region", {**base_args, "relations": [0, 2]}
    )
    assert "complete review region" in executor.execute(
        "edit_region", {**base_args, "relations": [0]}
    )
    assert "overlap another review region" in executor.execute(
        "edit_region", {**base_args, "relations": [0, 1, 2, 3]}
    )
    assert not executor.actions


def test_region_edit_trims_an_unchanged_neighbor_from_the_compiled_action():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8), ((1,), (), 0.0)],
        ["标题", "来源说明"],
        ["Title"],
    )
    placeholder = RepairAction.make_placeholder_tgt("L000002", source="auto")
    flag = RepairAction.make_flag(
        "L000002",
        source="auto",
        reason="composition_disagreement",
        note="结构选择尚未确定",
        uncertain_region={
            "start": {"source": 0, "target": 0},
            "end": {"source": 2, "target": 1},
        },
        current_structure="1:1+1:0",
        alternative_structure="2:1",
    )
    state = RepairState(snapshot, [placeholder, flag])
    executor = RegionReviewExecutor(state, (1,), strategy="src")
    region = executor.regions[0]

    executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [
                {"src": ["标题"], "tgt": ["Title"]},
                {"src": ["来源说明"], "tgt": ["Source note"]},
            ],
            "reason": "补足缺失译文",
            "keep_flags": False,
        },
    )

    edit = executor.unique_actions()[0]
    assert edit.kind == "edit"
    assert edit.relation_ids == ("L000002",)
    assert edit.data["new_src_lines"] == ["来源说明"]
    assert edit.data["new_tgt_lines"] == ["Source note"]


def test_region_edit_compiles_one_nm_unit_without_serializing_the_arrays():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0, 1), (0,), 0.7)],
        ["雨下得很大，", "视野变得模糊。"],
        ["The rain made the view blurry."],
    )
    split = RepairAction.make_split(
        "L000001",
        source="auto",
        side="tgt",
        new_src_lines=["雨下得很大，", "视野变得模糊。"],
        new_tgt_lines=["The rain was heavy.", "The view became blurry."],
    )
    state = RepairState(snapshot, [split])
    executor = RegionReviewExecutor(state, (0,), strategy="src")
    region = executor.regions[0]

    result = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [
                {
                    "src": ["雨下得很大，", "视野变得模糊。"],
                    "tgt": ["The rain made the view blurry."],
                }
            ],
            "reason": "保留完整语义单元",
            "keep_flags": True,
        },
    )

    payload = json.loads(result)
    assert payload["final_units"][0]["src"] == ["雨下得很大，", "视野变得模糊。"]
    action = executor.unique_actions()[0]
    assert action.data["new_src_lines"] == ["雨下得很大，视野变得模糊。"]
    assert action.data["new_tgt_lines"] == ["The rain made the view blurry."]
    assert "['" not in action.data["new_src_lines"][0]


def test_region_edit_rejects_scalar_or_nested_non_string_unit_values():
    state = RepairState.from_ops([((0,), (0,), 0.2)], ["A"], ["B"])
    executor = RegionReviewExecutor(state, (0,), strategy="src")
    region = executor.regions[0]
    common = {
        "region_id": region.region_id,
        "reason": "invalid contract",
        "keep_flags": True,
    }

    scalar = executor.execute(
        "edit_region",
        {**common, "units": [{"src": "A", "tgt": ["B+"]}]},
    )
    nested = executor.execute(
        "edit_region",
        {**common, "units": [{"src": [["A"]], "tgt": ["B+"]}]},
    )

    assert scalar == "❌ units[0].src must be a non-empty string array"
    assert nested == "❌ units[0].src[0] must be a string"
    assert not executor.actions


def test_region_edit_preserves_quotes_and_backslashes_as_text():
    state = RepairState.from_ops([((0,), (0,), 0.2)], ["路径说明"], ["Old"])
    executor = RegionReviewExecutor(state, (0,), strategy="src")
    region = executor.regions[0]
    target = 'He said, "open C:\\Books".'

    result = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [{"src": ["路径说明"], "tgt": [target]}],
            "reason": "replace text",
            "keep_flags": True,
        },
    )

    assert json.loads(result)["final_units"][0]["tgt"] == [target]
    assert executor.unique_actions()[0].data["new_tgt_lines"] == [target]


def test_delete_region_emits_a_delete_action():
    state = RepairState.from_ops([((0,), (0,), 0.2)], ["A"], ["B"])
    executor = RegionReviewExecutor(state, (0,), strategy="src")
    region = executor.regions[0]

    result = executor.execute(
        "delete_region",
        {
            "region_id": region.region_id,
            "reason": "文档 A 为准时删除仅 B 的重复内容",
            "keep_flags": True,
        },
    )

    assert json.loads(result)["status"] == "deleted"
    action = executor.unique_actions()[0]
    assert action.kind == "delete"
    assert action.relation_ids == ("L000001",)


def test_finish_is_rejected_until_every_region_is_resolved():
    state = _composition_state()
    executor = RegionReviewExecutor(state, (1,))

    assert executor.execute("finish_review", {}).startswith("❌")
    region = executor.regions[0]
    executor.execute(
        "defer_region",
        {"region_id": region.region_id, "reason": "需要核对专名"},
    )
    assert json.loads(executor.execute("finish_review", {}))["status"] == "finished"


def test_production_tool_contract_exposes_only_region_level_operations():
    tools = _get_tools_openai()
    names = {tool["name"] for tool in tools}

    assert names == {
        "inspect_region",
        "accept_candidate",
        "edit_region",
        "delete_region",
        "defer_region",
        "finish_review",
    }
    assert all(tool["strict"] is True for tool in tools)

    edit = next(tool for tool in tools if tool["name"] == "edit_region")
    unit = edit["parameters"]["properties"]["units"]["items"]
    assert unit["properties"]["src"]["type"] == "array"
    assert unit["properties"]["tgt"]["type"] == "array"
    assert edit["parameters"]["properties"]["relations"]["type"] == "array"
    assert "relations" not in edit["parameters"]["required"]
    for name in ("accept_candidate", "edit_region", "delete_region"):
        tool = next(item for item in tools if item["name"] == name)
        assert "keep_flags" in tool["parameters"]["properties"]
        assert "keep_flags" in tool["parameters"]["required"]
        assert "resolve_flags" not in tool["parameters"]["properties"]

    prompt = _load_system_prompt("src")
    assert "可靠解决 `[F]` 时清除" in prompt
    assert "仍有实质疑义时保留或延后" in prompt


def test_provider_adapter_only_sends_strict_when_the_endpoint_supports_it():
    tools = _get_tools_openai()
    stable = DeepSeekNativeBackend(base_url="https://api.deepseek.com", api_key="x")
    beta = DeepSeekNativeBackend(base_url="https://api.deepseek.com/beta", api_key="x")

    assert "strict" not in stable._normalize_tools(tools)[0]
    assert beta._normalize_tools(tools)[0]["strict"] is True
    assert tools[0]["strict"] is True


def test_prompt_judges_cross_language_text_by_function_not_entity_class():
    prompt = _load_system_prompt("src")
    edit_tool = next(
        tool for tool in _get_tools_openai() if tool["name"] == "edit_region"
    )

    assert "本侧读者通常可读" in prompt
    assert "没有按实体类别“原样保留”的豁免" in prompt
    assert "原字形本身正被引用或说明" in prompt
    assert "异常状态、初始结构和候选只是核查线索" in prompt
    assert "不能替代文本判断" in prompt
    assert "语言杂糅都说明" not in prompt
    assert "颜文字" not in prompt
    assert "用户注释是必须解决的验收问题" in prompt
    assert "naturally readable in its language" in edit_tool["description"]
    assert "需翻译" not in prompt
    assert "verbatim" not in edit_tool["description"].lower()


def test_region_payload_separates_current_anomalies_from_result_source():
    state = RepairState.from_ops(
        [((0,), (0,), 0.9)],
        ["黑玉登场。"],
        ["Heiyu appears."],
    )
    state = state.apply(
        state.make_action(
            "edit",
            0,
            source="auto",
            new_tgt_lines=["黑玉 appears."],
        )
    )

    payload = RegionReviewExecutor(state, (0,), strategy="src").initial_payload()

    assert payload["review_regions"][0]["relation_states"] == [
        {
            "relation": 0,
            "source": "auto",
            "current": ["语言杂糅"],
            "initial": [],
        }
    ]


def test_initial_payload_deduplicates_shared_context_rows():
    state = RepairState.from_ops(
        [((index,), (index,), 0.5) for index in range(5)],
        [f"A{index}" for index in range(5)],
        [f"B{index}" for index in range(5)],
    )
    executor = RegionReviewExecutor(state, (1, 3), strategy="src")

    payload = executor.initial_payload(context_window=2)

    assert [row["relation"] for row in payload["context_rows"]] == [0, 1, 2, 3, 4]
    first, second = payload["review_regions"]
    assert first["context_relations"] == [0, 2, 3]
    assert second["context_relations"] == [1, 2, 4]
    assert "context" not in first


def test_minimal_strategy_is_injected_without_deleting_an_unmatched_relation():
    raw = RepairState.from_ops([((0,), (), 0.2)], ["需要补译"], [])

    session = build_agent_review_session(raw, strategy="minimal")
    executor = RegionReviewExecutor(
        session.proposed_state,
        tuple(session.context.reviewable_ids),
        strategy="minimal",
    )
    agent = AiRepairAgent(llm_backend=_ScriptedBackend([]), strategy="minimal")
    messages = agent._build_initial_messages(
        session.context, region_payload=executor.initial_payload()
    )
    request = json.loads(messages[1]["content"])

    assert session.context.strategy == "minimal"
    assert [action.kind for action in session.proposed_state.repair_log] == [
        "placeholder_tgt"
    ]
    assert session.context.reviewable_ids == [0]
    assert request["strategy"] == "最小结构修改 (minimal)"


def test_edit_region_can_supply_a_missing_translation():
    raw = RepairState.from_ops([((0,), (), 0.2)], ["需要补译"], [])
    session = build_agent_review_session(raw, strategy="minimal")
    executor = RegionReviewExecutor(session.proposed_state, (0,), strategy="minimal")
    region = executor.regions[0]

    result = executor.execute(
        "edit_region",
        {
            "region_id": region.region_id,
            "units": [{"src": ["需要补译"], "tgt": ["Translation required."]}],
            "reason": "补充缺失译文",
            "keep_flags": True,
        },
    )

    assert json.loads(result)["status"] == "applied"
    action = executor.unique_actions()[0]
    assert action.kind == "edit"
    assert action.data["new_tgt_lines"] == ["Translation required."]


def test_defer_preserves_the_original_flag_evidence_and_origin():
    state = RepairState.from_ops(
        [((0,), (0,), 0.4)],
        ["原文"],
        ["Translation"],
        log=[
            RepairAction.make_flag(
                "L000001",
                source="user",
                note="专名来源尚未确认",
                reason="terminology_uncertain",
            )
        ],
    )
    executor = RegionReviewExecutor(state, (0,))
    region = executor.regions[0]
    assert region.evidence["note"] == "专名来源尚未确认"

    executor.execute(
        "defer_region",
        {"region_id": region.region_id, "reason": "现有上下文不足"},
    )
    flag = executor.unique_actions()[0]

    assert flag.kind == "flag"
    assert flag.source == "user"
    assert flag.data["note"] == "专名来源尚未确认"
    assert flag.data["reviewed_by"] == ["ai"]
    assert flag.data["ai_review_note"] == "现有上下文不足"


class _ScriptedBackend(LLMBackend):
    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, thinking=False, tools=None):
        return self.script.pop(0)


def test_agent_region_flow_returns_origin_preserving_action():
    state = _composition_state()
    context = ChapterContext.from_repair_state(state, skip_auto_repair=True)
    context.select_reviewable([1])
    region_id = build_review_regions(state, [1], strategy="tgt")[0].region_id
    backend = _ScriptedBackend(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "accept",
                        "accept_candidate",
                        {
                            "region_id": region_id,
                            "candidate_id": "alignment-alternative",
                            "keep_flags": True,
                        },
                    )
                ]
            )
        ]
    )
    agent = AiRepairAgent(llm_backend=backend, verbose=False, strategy="tgt")

    result = agent.run(context, initial_state=state)

    assert result.is_complete
    assert result.turns == 1
    assert result.reviewed_ids == (1,)
    assert len(result.actions) == 1
    assert result.actions[0].kind == "merge"
    assert result.actions[0].source == "auto"
    assert result.actions[0].data["reviewed_by"] == ["ai"]
