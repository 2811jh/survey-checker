# -*- coding: utf-8 -*-
"""Markdown 问卷文案导入：解析 → spec → add_questions"""
import re

from core.utils import _log


# ─── 排他/其他关键词（与 builder 保持一致）─────────────────────────────────────

EXCLUSIVE_KEYWORDS = [
    "以上都没", "以上均没", "都没有", "都不是", "我没有不满意",
    "我认为", "我没在", "只玩", "我没遇到", "没遇到",
    "以上都不", "都不需要",
]


# ─── 解析 ─────────────────────────────────────────────────────────────────────

def parse_question_file(filepath):
    """
    解析问卷题目文本文件，返回 add_questions 所需的 spec 列表。
    支持格式：数字[题型]标题，后续行为选项/提示文案/评分等。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    raw_questions = []
    current = None
    i = 0

    type_map = {
        "量表题": "star", "矩形量表题": "rect-star",
        "矩形单选题": "rect-radio", "矩形多选题": "rect-checkbox",
        "多选题": "checkbox", "单选题": "radio",
        "填空题": "blank", "多项填空题": "multiple-text",
        "分页符": "paging", "描述说明": "describe",
        "隐含问题": "imply",
    }

    # 跳过文件头部 [问卷标题] / [问卷说明] 行
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("[问卷标题]") or line.startswith("[问卷说明]"):
            i += 1
            continue
        break

    while i < len(lines):
        line = lines[i].strip()
        # ⚠️ 遇到 [逻辑] 块标记，停止解析题目
        if line == "[逻辑]":
            break
        m = re.match(r"^(\d+)\[(.+?)\](.+)$", line)
        if m:
            if current:
                raw_questions.append(current)
            qtype_cn = m.group(2)
            current = {
                "type": type_map.get(qtype_cn, "radio"),
                "title": m.group(3).strip(),
                "_num": int(m.group(1)),
                "_lines": [],
                "_logic_lines": [],   # 新增：跳转逻辑行
                "_in_logic": False,
            }
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    i += 1
                    continue
                if re.match(r"^\d+\[", next_line):
                    break
                # 检测 [跳转逻辑] 块的开始/结束
                if next_line == "[跳转逻辑]":
                    current["_in_logic"] = True
                    i += 1
                    continue
                # 在逻辑块内，以 "当 " 开头的行是逻辑规则
                if current["_in_logic"]:
                    if next_line.startswith("当 "):
                        current["_logic_lines"].append(next_line)
                        i += 1
                        continue
                    else:
                        # 逻辑块结束（遇到非规则行）
                        current["_in_logic"] = False
                current["_lines"].append(next_line)
                i += 1
            continue
        i += 1

    if current:
        raw_questions.append(current)

    # 转换为 spec 列表
    result = []
    for q in raw_questions:
        spec = {"type": q["type"], "title": q["title"]}
        extra = q["_lines"]

        if q["type"] == "paging":
            result.append(spec)
            continue

        if q["type"] == "imply":
            var_type = "1"
            var_name = ""
            for el in extra:
                if el.startswith("[变量类型]"):
                    var_type = el.replace("[变量类型]", "").strip()
                elif el.startswith("[变量名称]"):
                    var_name = el.replace("[变量名称]", "").strip()
            spec["required"] = 0
            spec["hidden"] = 1
            spec["varType"] = var_type
            spec["varName"] = var_name
            result.append(spec)
            continue

        if q["type"] == "describe":
            for el in extra:
                spec["title"] += "<br>" + el
            spec["required"] = 0
            result.append(spec)
            continue

        # required
        if "非必填" in q["title"]:
            spec["required"] = 0
        elif q["type"] in ("blank", "multiple-text"):
            spec["required"] = 0
        else:
            spec["required"] = 1

        hint_line = score_line = sub_title_line = None
        option_lines = []

        for el in extra:
            if el.startswith("[提示文案]"):
                hint_line = el.replace("[提示文案]", "").strip()
            elif el.startswith("[评分]"):
                score_line = el.replace("[评分]", "").strip()
            elif el.startswith("*"):
                sub_title_line = el
            elif el.startswith("&nbsp;") or el.startswith("（点击可放大"):
                spec["title"] += "<br>" + el
            elif "//" in el and q["type"] in ("rect-radio", "rect-checkbox"):
                option_lines.insert(0, el)
            else:
                option_lines.append(el)

        if sub_title_line:
            spec["title"] += "<br>" + sub_title_line

        # 量表题 / NPS
        if q["type"] == "star":
            if hint_line:
                parts = hint_line.split("//")
                spec["startDesc"] = parts[0].strip() if len(parts) > 0 else ""
                spec["middleDesc"] = parts[1].strip() if len(parts) > 1 else ""
                spec["endDesc"] = parts[2].strip() if len(parts) > 2 else ""
            if score_line:
                if score_line.upper() == "NPS" or "10" in score_line:
                    spec["options"] = [str(x) for x in range(0, 11)]
                    spec["_is_nps"] = True
                else:
                    m2 = re.search(r"(\d+)", score_line)
                    n = int(m2.group(1)) if m2 else 5
                    spec["options"] = [str(x) for x in range(1, n + 1)]

        # 矩阵量表题
        elif q["type"] == "rect-star":
            if hint_line:
                parts = hint_line.split("//")
                spec["startDesc"] = parts[0].strip() if len(parts) > 0 else ""
                spec["middleDesc"] = parts[1].strip() if len(parts) > 1 else ""
                spec["endDesc"] = parts[2].strip() if len(parts) > 2 else ""
            if score_line:
                if "10" in score_line:
                    spec["options"] = [str(x) for x in range(0, 11)]
                else:
                    m2 = re.search(r"(\d+)", score_line)
                    n = int(m2.group(1)) if m2 else 5
                    spec["options"] = [str(x) for x in range(1, n + 1)]
            spec["subQuestions"] = [ol for ol in option_lines if ol.strip()]

        # 矩阵单选/多选题
        elif q["type"] in ("rect-radio", "rect-checkbox"):
            col_opts, sub_qs = [], []
            for el in option_lines:
                if "//" in el:
                    col_opts = [o.strip() for o in el.split("//") if o.strip()]
                elif el.strip():
                    sub_qs.append(el.strip())
            spec["options"] = col_opts
            spec["subQuestions"] = sub_qs

        # 多选/单选
        elif q["type"] in ("checkbox", "radio"):
            opts = []
            for ol in option_lines:
                ol = ol.strip()
                if not ol:
                    continue
                is_mutex = any(kw in ol for kw in EXCLUSIVE_KEYWORDS)
                if ol == "其他" or ol.startswith("其他游戏"):
                    opts.append({"text": ol, "hasOther": 1, "noRandom": 1})
                elif is_mutex:
                    opts.append({"text": ol, "mutex": 1, "noRandom": 1})
                else:
                    opts.append(ol)
            spec["options"] = opts
            if len(opts) >= 20:
                spec["layout"] = 3
            elif len(opts) >= 8:
                spec["layout"] = 2
            if q["type"] == "checkbox":
                spec["random"] = 1

        # 多项填空
        elif q["type"] == "multiple-text":
            spec["subQuestions"] = [
                {"title": ol.strip(), "placeholder": "请输入..."}
                for ol in option_lines if ol.strip()
            ]

        # 填空题附加说明
        elif q["type"] == "blank":
            for el in option_lines:
                if el.strip():
                    spec["title"] += "<br>" + el.strip()

        # ── 解析 [跳转逻辑] 块 → logic_rules ──────────────────────────────
        if q.get("_logic_lines"):
            logic_rules = _parse_logic_lines(q["_logic_lines"])
            if logic_rules:
                spec["logic_rules"] = logic_rules

        result.append(spec)

    return result


# ─── 跳转逻辑文本解析 ─────────────────────────────────────────────────────────

def _parse_logic_lines(logic_lines: list) -> list:
    """
    将标准格式的 [跳转逻辑] 文本行转化为 logic_rules spec 列表。

    输入示例：
      ["当 评分 1-2 分 → 显示 Q11（不满意原因）",
       "当 选择"是的，卸载了" → 显示 Q12"]

    输出示例：
      [{"when_options": ["评分 1-2 分"], "show_questions": ["Q11"], "action": "show"},
       {"when_options": ["是的，卸载了"],  "show_questions": ["Q12"], "action": "show"}]
    """
    rules = []
    for line in logic_lines:
        # 格式：当 <条件> → <动作> <目标>
        # 动作关键词：显示、跳转到、结束问卷
        m = re.match(r"^当\s+(.+?)\s+(?:→|->)\s+(.+)$", line)
        if not m:
            continue
        condition = m.group(1).strip()
        action_part = m.group(2).strip()

        # 解析条件（选项文字），去掉引号
        condition_clean = re.sub(r"[\"\"\"'']", "", condition)
        # 去掉括号注释（如"评分 1-2 分" 保留，"Q11（不满意原因）"去掉括号）
        condition_clean = re.sub(r"（[^）]*）", "", condition_clean).strip()
        # 去掉"选择"前缀
        condition_clean = re.sub(r"^选择\s*", "", condition_clean).strip()

        rule = {"when_options": [condition_clean]}

        if "结束问卷" in action_part:
            rule["action"] = "end"
            rule["show_questions"] = []
        elif "跳转到" in action_part or "跳至" in action_part:
            rule["action"] = "jump"
            targets = re.findall(r"Q\d+", action_part)
            rule["show_questions"] = targets
        else:
            # 默认：显示
            rule["action"] = "show"
            targets = re.findall(r"Q\d+", action_part)
            rule["show_questions"] = targets

        if rule.get("show_questions") is not None:
            rules.append(rule)

    return rules


# ─── 导入入口 ─────────────────────────────────────────────────────────────────

def import_from_markdown(session, base_url, platform, survey_id, filepath):
    """
    解析 Markdown/文本文件并导入为问卷题目。
    调用 parse_question_file 解析，再调用 question_ops.add_questions 写入。
    录入成功后，自动提取 [逻辑] 块并写入逻辑规则。
    """
    # 延迟导入避免循环依赖
    from operations.question_ops import add_questions

    _log(f"Parsing {filepath}...")
    specs = parse_question_file(filepath)
    _log(f"Parsed {len(specs)} question specs")

    if not specs:
        return {"status": "error", "message": "未解析到任何题目，请检查文件格式"}

    result = add_questions(session, base_url, platform, survey_id, specs)

    # ── 自动写入逻辑规则 ────────────────────────────────────────────
    if result.get("status") == "success":
        from operations.logic_writer import (
            extract_logic_block, parse_logic_block,
            resolve_logic_rules, write_logic_rules,
        )
        from survey_io.fetcher import get_survey_full
        logic_lines = extract_logic_block(filepath)
        if logic_lines:
            _log(f"Found {len(logic_lines)} logic rules in [逻辑] block")
            parsed = parse_logic_block(logic_lines)
            if parsed:
                survey_data = get_survey_full(session, base_url, survey_id)
                if survey_data:
                    questions = survey_data.get("questions") or []
                    resolved, logic_errors = resolve_logic_rules(parsed, questions)
                    if resolved:
                        logic_result = write_logic_rules(
                            session, base_url, survey_id, resolved
                        )
                        result["logic_result"] = logic_result
                    if logic_errors:
                        result["logic_errors"] = logic_errors
                    _log(f"Logic: {len(resolved)} resolved, {len(logic_errors)} errors")
        else:
            _log("No [逻辑] block found in file")

    return result
