# scripts/tests/test_logic_writer.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from operations.logic_writer import parse_logic_block


def test_parse_radio_text_option():
    """单选题文本选项"""
    lines = ['源题 Q16 选项 "组队开黑" → 显示 Q17,Q18']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["source"] == "Q16"
    assert result[0]["options"] == ["组队开黑"]
    assert result[0]["targets"] == ["Q17", "Q18"]
    assert result[0]["sub_questions"] is None
    assert result[0]["sub_options"] is None


def test_parse_star_numeric_option():
    """量表题数值评分"""
    lines = ['源题 Q1 选项 1,2 → 显示 Q2']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["source"] == "Q1"
    assert result[0]["options"] == ["1", "2"]
    assert result[0]["targets"] == ["Q2"]


def test_parse_multiple_text_options():
    """多个文本选项"""
    lines = ['源题 Q24 选项 "非常困难","有点困难" → 显示 Q25']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["options"] == ["非常困难", "有点困难"]
    assert result[0]["targets"] == ["Q25"]


def test_parse_rect_star_sub_questions():
    """矩阵量表题子问题+子选项"""
    lines = ['源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["source"] == "Q28"
    assert result[0]["sub_questions"] == [1, 2, 3]
    assert result[0]["sub_options"] == ["1", "2", "3"]
    assert result[0]["targets"] == ["Q29"]
    assert result[0]["options"] is None


def test_parse_long_text_with_parens():
    """含括号的长文本选项"""
    lines = ['源题 Q3 选项 "QQ（如QQ群、QQ空间、QQ游戏中心、兴趣部落等）" → 显示 Q4']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["options"] == ["QQ（如QQ群、QQ空间、QQ游戏中心、兴趣部落等）"]


def test_parse_multiple_rules():
    """多条规则"""
    lines = [
        '源题 Q1 选项 1,2 → 显示 Q2',
        '源题 Q16 选项 "组队开黑" → 显示 Q17,Q18',
        '源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29',
    ]
    result = parse_logic_block(lines)
    assert len(result) == 3


def test_parse_skip_invalid_lines():
    """跳过无效行"""
    lines = ['这不是逻辑规则', '', '源题 Q1 选项 1,2 → 显示 Q2']
    result = parse_logic_block(lines)
    assert len(result) == 1


# ─── resolve_logic_rules 测试 ────────────────────────────────────────────

from operations.logic_writer import resolve_logic_rules


def _make_mock_questions():
    """构造模拟问卷数据，覆盖三种题型"""
    return [
        # Q1: star 量表题 (idx=0)
        {
            "id": "q-001", "type": "star", "title": "<p>满意度评分</p>",
            "options": [
                {"id": "a-s1", "text": "1"}, {"id": "a-s2", "text": "2"},
                {"id": "a-s3", "text": "3"}, {"id": "a-s4", "text": "4"},
                {"id": "a-s5", "text": "5"},
            ],
            "subQuestions": [], "logic": [],
        },
        # Q2: blank 填空题 (idx=1)
        {
            "id": "q-002", "type": "blank", "title": "<p>不满意原因</p>",
            "options": [], "subQuestions": [], "logic": [],
        },
        # Q3: radio 单选题 (idx=2)
        {
            "id": "q-003", "type": "radio", "title": "<p>和谁一起玩</p>",
            "options": [
                {"id": "a-r1", "text": "自己一个人玩"},
                {"id": "a-r2", "text": "组队开黑"},
            ],
            "subQuestions": [], "logic": [],
        },
        # Q4: blank (idx=3)
        {"id": "q-004", "type": "blank", "title": "<p>队友</p>",
         "options": [], "subQuestions": [], "logic": []},
        # Q5: blank (idx=4)
        {"id": "q-005", "type": "blank", "title": "<p>场景</p>",
         "options": [], "subQuestions": [], "logic": []},
        # Q6: rect-star 矩阵量表 (idx=5)
        {
            "id": "q-006", "type": "rect-star", "title": "<p>活动评价</p>",
            "options": [
                {"id": "a-c1", "text": "1"}, {"id": "a-c2", "text": "2"},
                {"id": "a-c3", "text": "3"}, {"id": "a-c4", "text": "4"},
                {"id": "a-c5", "text": "5"},
            ],
            "subQuestions": [
                {"id": "a-sq1", "title": "资讯传递"},
                {"id": "a-sq2", "title": "任务难度"},
                {"id": "a-sq3", "title": "流程时长"},
                {"id": "a-sq4", "title": "界面清晰"},
                {"id": "a-sq5", "title": "目标明确"},
            ],
            "logic": [],
        },
        # Q7: radio (idx=6)
        {"id": "q-007", "type": "radio", "title": "<p>UI感受</p>",
         "options": [], "subQuestions": [], "logic": []},
    ]


def test_resolve_star_numeric():
    """量表题评分→选项ID"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q1", "options": ["1", "2"], "targets": ["Q2"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(errors) == 0
    assert len(resolved) == 1
    assert resolved[0]["src_idx"] == 0
    assert resolved[0]["option_ids"] == ["a-s1", "a-s2"]
    assert resolved[0]["target_ids"] == ["q-002"]
    assert resolved[0]["sub_question_ids"] == []


def test_resolve_radio_text():
    """单选题文本→选项ID"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q3", "options": ["组队开黑"], "targets": ["Q4", "Q5"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(errors) == 0
    assert resolved[0]["option_ids"] == ["a-r2"]
    assert resolved[0]["target_ids"] == ["q-004", "q-005"]


def test_resolve_rect_star():
    """矩阵量表子问题+子选项→ID"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q6", "sub_questions": [1, 2, 3], "sub_options": ["1", "2", "3"],
               "options": None, "targets": ["Q7"]}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(errors) == 0
    assert resolved[0]["sub_question_ids"] == ["a-sq1", "a-sq2", "a-sq3"]
    assert resolved[0]["option_ids"] == ["a-c1", "a-c2", "a-c3"]
    assert resolved[0]["target_ids"] == ["q-007"]


def test_resolve_source_not_found():
    """源题不存在→报错跳过"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q99", "options": ["1"], "targets": ["Q2"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(resolved) == 0
    assert len(errors) == 1
    assert "Q99" in errors[0]


def test_resolve_option_not_matched():
    """选项文本不匹配→警告"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q3", "options": ["不存在的选项"], "targets": ["Q4"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(resolved) == 0
    assert len(errors) >= 1


if __name__ == "__main__":
    # parse tests
    test_parse_radio_text_option()
    test_parse_star_numeric_option()
    test_parse_multiple_text_options()
    test_parse_rect_star_sub_questions()
    test_parse_long_text_with_parens()
    test_parse_multiple_rules()
    test_parse_skip_invalid_lines()
    print("All parse tests passed!")
    # resolve tests
    test_resolve_star_numeric()
    test_resolve_radio_text()
    test_resolve_rect_star()
    test_resolve_source_not_found()
    test_resolve_option_not_matched()
    print("All resolve tests passed!")
