# -*- coding: utf-8 -*-
"""问卷逻辑规则解析与写入 — 替代 logic_ops.py"""
import re
import time

from core.utils import _log, _strip_html, _build_label_map
from survey_io.fetcher import get_survey_full
from operations.survey_ops import lock_survey, save_survey


def parse_logic_block(lines: list) -> list:
    """
    解析 [逻辑] 块文本行 → 结构化规则列表。

    语法：源题 Q{n} [子问题 {序号,...}] 选项|子选项 {值,...} → 显示 Q{n}[,Q{m}...]

    返回: [{"source":"Q1", "options":["1","2"], "targets":["Q2"],
            "sub_questions":None, "sub_options":None}, ...]
    """
    rules = []
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("源题"):
            continue

        # 1. 提取源题
        m_src = re.match(r"^源题\s+(Q\d+)", line)
        if not m_src:
            continue
        source = m_src.group(1)

        # 2. 提取目标（→ 显示 Qx,Qy）
        m_tgt = re.search(r"→\s*显示\s+(Q[\d,\sQ]+)", line)
        if not m_tgt:
            continue
        targets = re.findall(r"Q\d+", m_tgt.group(1))
        if not targets:
            continue

        # 3. 提取中间部分（源题和→之间）
        middle = line[m_src.end():m_tgt.start()].strip()

        sub_questions = None
        sub_options = None
        options = None

        # 4. 检测子问题
        m_sub = re.search(r"子问题\s+([\d,\s]+)", middle)
        if m_sub:
            sub_questions = [int(x.strip()) for x in m_sub.group(1).split(",") if x.strip()]
            middle = middle[m_sub.end():].strip()

        # 5. 检测子选项 vs 选项
        if "子选项" in middle:
            sub_part = re.sub(r"^子选项\s*", "", middle).strip()
            sub_options = _parse_option_values(sub_part)
        elif "选项" in middle:
            opt_part = re.sub(r"^选项\s*", "", middle).strip()
            options = _parse_option_values(opt_part)

        rules.append({
            "source": source,
            "options": options,
            "targets": targets,
            "sub_questions": sub_questions,
            "sub_options": sub_options,
        })

    return rules


def _parse_option_values(text: str) -> list:
    """解析选项值：引号包裹→文本，无引号→数值字符串"""
    # 尝试提取引号内的文本（支持中英文引号）
    quoted = re.findall(r'["\u201c]([^"\u201d]*)["\u201d]', text)
    if quoted:
        return quoted
    # 无引号：按逗号分割
    return [v.strip() for v in text.split(",") if v.strip()]