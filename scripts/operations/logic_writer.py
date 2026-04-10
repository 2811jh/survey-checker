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


# ─── ID 匹配 ─────────────────────────────────────────────────────────────────

def resolve_logic_rules(parsed_rules: list, questions: list):
    """
    将解析后的规则匹配为实际 ID。

    返回: (resolved_list, errors_list)
      resolved: [{"src_idx":0, "option_ids":[...], "target_ids":[...], "sub_question_ids":[...]}]
      errors: ["错误描述", ...]
    """
    label_map = _build_label_map(questions)
    resolved = []
    errors = []

    for rule in parsed_rules:
        source = rule["source"]
        # 1. 定位源题
        src_idx = label_map.get(source)
        if src_idx is None:
            errors.append(f"源题未找到: {source}")
            continue
        src_q = questions[src_idx]

        # 2. 定位目标题
        target_ids = []
        for tgt_label in rule["targets"]:
            tgt_idx = label_map.get(tgt_label)
            if tgt_idx is None:
                errors.append(f"目标题未找到: {tgt_label}")
                continue
            target_ids.append(questions[tgt_idx]["id"])
        if not target_ids:
            continue

        # 3. 匹配子问题 ID（矩阵题）
        sub_question_ids = []
        if rule.get("sub_questions"):
            subs = src_q.get("subQuestions") or []
            for seq in rule["sub_questions"]:
                if 1 <= seq <= len(subs):
                    sub_question_ids.append(subs[seq - 1]["id"])
                else:
                    errors.append(f"{source} 子问题序号 {seq} 越界（共 {len(subs)} 个子问题）")

        # 4. 匹配选项/子选项 ID
        option_ids = []
        opt_values = rule.get("sub_options") or rule.get("options") or []
        src_options = src_q.get("options") or []

        for val in opt_values:
            matched = False
            for opt in src_options:
                opt_text = _strip_html(opt.get("text", ""))
                # 精确匹配（数值）或模糊匹配（文本）
                if val == opt_text or val in opt_text:
                    option_ids.append(opt["id"])
                    matched = True
                    break
            if not matched:
                errors.append(f"{source} 选项未匹配: '{val}'")

        if not option_ids:
            errors.append(f"{source} 无有效选项匹配，规则跳过")
            continue

        resolved.append({
            "src_idx": src_idx,
            "option_ids": option_ids,
            "target_ids": target_ids,
            "sub_question_ids": sub_question_ids,
        })

    return resolved, errors
