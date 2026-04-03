# -*- coding: utf-8 -*-
"""显示/跳转逻辑规则设置"""
import time

from core.utils import _log, _strip_html, _build_label_map
from survey_io.fetcher import get_survey_full
from operations.survey_ops import lock_survey, save_survey


def set_logic_rules(session, base_url, survey_id, logic_rules):
    """
    为问卷设置显示/跳转逻辑。
    logic_rules 格式:
    [{"sourceLabel":"Q1","selectedOptionTexts":["A","B"],"goToLabel":"Q5"}]
    逻辑含义：当来源题选中了指定选项时，显示目标题。
    """
    _log(f"Setting {len(logic_rules)} logic rules for survey {survey_id}...")

    survey_data = get_survey_full(session, base_url, survey_id)
    if not survey_data:
        return {"status": "error", "message": "获取问卷数据失败"}

    questions = survey_data.get("questions", []) or []
    label_map = _build_label_map(questions)
    title_map = {_strip_html(q.get("title", "")): i for i, q in enumerate(questions) if _strip_html(q.get("title", ""))}

    applied = []
    errors = []

    for rule in logic_rules:
        try:
            # 1. 定位来源题
            src_idx = None
            if "sourceLabel" in rule:
                src_idx = label_map.get(rule["sourceLabel"])
            elif "sourceQuestionTitle" in rule:
                src_title = rule["sourceQuestionTitle"]
                src_idx = title_map.get(src_title)
                if src_idx is None:
                    for t, idx in title_map.items():
                        if src_title in t:
                            src_idx = idx
                            break

            if src_idx is None:
                errors.append(f"来源题未找到: {rule.get('sourceLabel') or rule.get('sourceQuestionTitle')}")
                continue

            src_q = questions[src_idx]
            if src_q.get("type") not in ("radio", "checkbox", "star"):
                errors.append(f"来源题类型 {src_q.get('type')} 不支持逻辑设置")
                continue

            # 2. 定位目标题
            tgt_idx = None
            if "goToLabel" in rule:
                tgt_idx = label_map.get(rule["goToLabel"])
            elif "goToQuestionTitle" in rule:
                tgt_title = rule["goToQuestionTitle"]
                tgt_idx = title_map.get(tgt_title)
                if tgt_idx is None:
                    for t, idx in title_map.items():
                        if tgt_title in t:
                            tgt_idx = idx
                            break

            if tgt_idx is None:
                errors.append(f"目标题未找到: {rule.get('goToLabel') or rule.get('goToQuestionTitle')}")
                continue

            tgt_q = questions[tgt_idx]
            if tgt_q.get("type") in ("paging", "imply", "describe"):
                errors.append(f"目标题类型 {tgt_q.get('type')} 不支持作为逻辑目标")
                continue
            if tgt_idx <= src_idx:
                errors.append(f"仅支持向后跳转，来源 idx={src_idx} → 目标 idx={tgt_idx}")
                continue

            # 3. 匹配选项 ID
            selected_texts = rule.get("selectedOptionTexts", [])
            option_ids = []
            for sel_text in selected_texts:
                for opt in (src_q.get("options") or []):
                    opt_text = _strip_html(opt.get("text", ""))
                    if sel_text == opt_text or sel_text in opt_text or str(sel_text) == opt_text:
                        option_ids.append(opt["id"])
                        break
                else:
                    errors.append(f"选项 '{sel_text}' 在来源题中未找到")

            if not option_ids:
                continue

            # 4. 写入 logic 字段
            src_logic = src_q.get("logic", [])
            if not isinstance(src_logic, list):
                src_logic = []

            existing_rule = next((lr for lr in src_logic if tgt_q["id"] in (lr.get("questions") or [])), None)
            if existing_rule:
                existing_opts = set(existing_rule.get("options", []))
                existing_opts.update(option_ids)
                existing_rule["options"] = list(existing_opts)
            else:
                src_logic.append({
                    "options": option_ids,
                    "questions": [tgt_q["id"]],
                    "subQuestions": [],
                    "controlSubQuestions": "{}",
                })

            src_q["logic"] = src_logic
            applied.append({
                "source": rule.get("sourceLabel") or _strip_html(src_q["title"])[:30],
                "options": selected_texts,
                "target": rule.get("goToLabel") or _strip_html(tgt_q["title"])[:30],
            })

        except Exception as e:
            errors.append(f"规则处理异常: {str(e)}")

    if not applied:
        return {"status": "error", "message": "没有成功应用的逻辑规则", "errors": errors}

    survey_data["questions"] = questions
    lock_ok = lock_survey(session, base_url, survey_id)
    if not lock_ok:
        return {"status": "error", "message": "锁定失败，请关闭编辑器", "applied": applied, "errors": errors}

    save_result = save_survey(session, base_url, survey_data)
    _log("Verifying logic (waiting 3s)...")
    time.sleep(3)

    return {
        "status": save_result["status"],
        "message": f"成功设置 {len(applied)} 条逻辑规则",
        "applied": applied,
        "errors": errors if errors else None,
    }
