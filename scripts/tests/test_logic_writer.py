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


if __name__ == "__main__":
    test_parse_radio_text_option()
    test_parse_star_numeric_option()
    test_parse_multiple_text_options()
    test_parse_rect_star_sub_questions()
    test_parse_long_text_with_parens()
    test_parse_multiple_rules()
    test_parse_skip_invalid_lines()
    print("All parse tests passed!")