# -*- coding: utf-8 -*-
"""题目增删改操作：clear / add / modify"""
import time

from core.utils import _log, _strip_html, _build_label_map, _gen_id
from survey_io.fetcher import get_survey_full
from operations.survey_ops import lock_survey, save_survey
from operations.builder import build_question, resolve_insert_position


# ─── 清空题目 ─────────────────────────────────────────────────────────────────

def clear_questions(session, base_url, survey_id, keep_imply=False):
    """清空问卷中的所有题目（可选保留隐含题）"""
    survey_data = get_survey_full(session, base_url, survey_id)
    if not survey_data:
        return {"status": "error", "message": "获取问卷数据失败"}

    questions = survey_data.get("questions") or []
    orig_count = len(questions)

    if keep_imply:
        kept = [q for q in questions if q.get("type") == "imply"]
        removed_count = orig_count - len(kept)
        survey_data["questions"] = kept
        _log(f"Keeping {len(kept)} imply questions, removing {removed_count}")
    else:
        removed_count = orig_count
        survey_data["questions"] = []
        _log(f"Removing all {removed_count} questions")

    _log(f"Locking survey {survey_id}...")
    lock_survey(session, base_url, survey_id)

    _log("Saving survey...")
    save_result = save_survey(session, base_url, survey_data)
    if save_result["status"] != "success":
        return {"status": "error", "message": save_result["message"]}

    _log("Verifying (waiting 3s)...")
    time.sleep(3)
    verify_data = get_survey_full(session, base_url, survey_id)
    new_count = len((verify_data or {}).get("questions") or [])
    _log(f"Questions: {orig_count} → {new_count}")

    return {
        "status": "success",
        "message": f"已清空 {removed_count} 道题目",
        "original_count": orig_count,
        "remaining_count": new_count,
    }


# ─── 新增题目 ─────────────────────────────────────────────────────────────────

def add_questions(session, base_url, platform, survey_id, question_specs):
    """向问卷中新增题目"""
    _log(f"Adding {len(question_specs)} questions to survey {survey_id}...")

    survey_data = get_survey_full(session, base_url, survey_id)
    if not survey_data:
        return {"status": "error", "message": "获取问卷数据失败"}

    questions = survey_data.get("questions") or []
    label_map = _build_label_map(questions)
    added = []

    # 构建并排序插入位置
    insertions = []
    for order, spec in enumerate(question_specs):
        q_obj = build_question(spec, questions)
        pos = resolve_insert_position(spec, questions, label_map)
        insertions.append((pos, order, q_obj, spec))

    insertions.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for pos, order, q_obj, spec in insertions:
        questions.insert(pos, q_obj)
        added.append({
            "id": q_obj["id"],
            "type": q_obj["type"],
            "title": _strip_html(q_obj.get("title", ""))[:50],
            "position": pos,
        })

    survey_data["questions"] = questions

    # 锁定并保存
    lock_ok = lock_survey(session, base_url, survey_id)
    if not lock_ok:
        return {"status": "error", "message": "锁定失败！请关闭浏览器编辑器后重试。", "added": added}

    save_result = save_survey(session, base_url, survey_data)
    if save_result["status"] != "success":
        return {"status": "error", "message": save_result["message"], "added": added}

    _log("Verifying (waiting 3s)...")
    time.sleep(3)
    verify_data = get_survey_full(session, base_url, survey_id)

    # ── 逻辑规则写入（暂时禁用，待 logic 工具完善后启用） ────────────
    # all_logic_rules = []
    # for spec in question_specs:
    #     if "logic_rules" in spec:
    #         all_logic_rules.extend(spec["logic_rules"])
    #
    # logic_result = None
    # if all_logic_rules and verify_data:
    #     from operations.logic_ops import set_logic_rules
    #     _log(f"Configuring {len(all_logic_rules)} logic rules...")
    #     logic_result = set_logic_rules(session, base_url, survey_id, all_logic_rules)

    result = {
        "status": "success",
        "message": f"成功新增 {len(added)} 道题目",
        "added": added,
    }
    # if logic_result:
    #     result["logic_result"] = logic_result
    return result


# ─── 修改题目 ─────────────────────────────────────────────────────────────────

def modify_questions(session, base_url, survey_id, modifications):
    """
    修改问卷中的题目设置。
    modifications 格式: [{"question_label":"Q6","changes":{"required":0,...}}]
    """
    _log(f"Fetching full survey data for ID: {survey_id}")
    survey_data = get_survey_full(session, base_url, survey_id)
    if not survey_data:
        return {"status": "error", "message": "无法获取问卷数据"}

    questions = survey_data.get("questions") or []
    if not questions:
        return {"status": "error", "message": "问卷中没有题目"}

    label_map = _build_label_map(questions)
    change_log = []

    for mod in modifications:
        q_label = mod.get("question_label")
        q_id = mod.get("question_id")
        changes = mod.get("changes", {})

        target_idx = None
        if q_label and q_label in label_map:
            target_idx = label_map[q_label]
        elif q_id:
            for idx, q in enumerate(questions):
                if q.get("id") == q_id:
                    target_idx = idx
                    break

        if target_idx is None:
            change_log.append({"question": q_label or q_id, "status": "skipped", "reason": "题目未找到"})
            continue

        q = questions[target_idx]
        q_title = _strip_html(q.get("title", ""))[:40]
        applied = []

        # required / random / title
        for simple_field in ["required", "random", "title"]:
            if simple_field in changes:
                old_val = _strip_html(q.get(simple_field, ""))[:30] if simple_field == "title" else q.get(simple_field)
                q[simple_field] = changes[simple_field]
                new_val = _strip_html(changes[simple_field])[:30] if simple_field == "title" else changes[simple_field]
                applied.append(f"{simple_field}: {old_val} → {new_val}")

        # option_mutex
        if "option_mutex" in changes:
            for opt_mod in changes["option_mutex"]:
                opt_text = opt_mod.get("text", "")
                for opt in (q.get("options") or []):
                    if opt_text and opt_text in _strip_html(opt.get("text", "")):
                        for field in ["mutex", "noRandom", "hasOther"]:
                            if field in opt_mod:
                                old_v = opt.get(field, 0)
                                opt[field] = opt_mod[field]
                                applied.append(f"option '{opt_text[:15]}' {field}: {old_v} → {opt_mod[field]}")
                        break

        # option_changes（更灵活）
        if "option_changes" in changes:
            for opt_mod in changes["option_changes"]:
                opt_index = opt_mod.get("index")
                opt_text = opt_mod.get("text")
                target_opt = None
                opts = q.get("options") or []
                if opt_index is not None and 0 <= opt_index < len(opts):
                    target_opt = opts[opt_index]
                elif opt_text:
                    for opt in opts:
                        if opt_text in _strip_html(opt.get("text", "")):
                            target_opt = opt
                            break
                if target_opt:
                    for field in ["mutex", "noRandom", "hasOther", "text", "hidden"]:
                        if field in opt_mod:
                            old_v = target_opt.get(field)
                            target_opt[field] = opt_mod[field]
                            label_txt = _strip_html(target_opt.get("text", ""))[:15]
                            applied.append(f"option '{label_txt}' {field}: {old_v} → {opt_mod[field]}")

        # option_texts（按序号修改文本）
        if "option_texts" in changes:
            for ot in changes["option_texts"]:
                opt_index = ot.get("index")
                old_text_match = ot.get("old_text")
                new_text = ot.get("new_text", "")
                opts = q.get("options") or []
                target_opt = None
                if opt_index is not None and 0 <= opt_index < len(opts):
                    target_opt = opts[opt_index]
                elif old_text_match:
                    for opt in opts:
                        if old_text_match in _strip_html(opt.get("text", "")):
                            target_opt = opt
                            break
                if target_opt and new_text:
                    old_t = _strip_html(target_opt.get("text", ""))[:20]
                    target_opt["text"] = new_text
                    applied.append(f"option text: '{old_t}' → '{new_text[:20]}'")

        # logic（原始 ID 格式）
        if "logic" in changes:
            old_count = len(q.get("logic") or [])
            q["logic"] = changes["logic"]
            applied.append(f"logic: {old_count} rules → {len(changes['logic'])} rules (raw)")

        # logic_rules（label/text 格式，自动转 ID）
        if "logic_rules" in changes:
            new_logic = []
            for rule in changes["logic_rules"]:
                opt_ids = []
                for opt_ref in rule.get("when_options", []):
                    for opt in (q.get("options") or []):
                        if opt_ref in _strip_html(opt.get("text", "")):
                            opt_ids.append(opt["id"])
                            break
                q_ids = []
                for q_ref in rule.get("show_questions", []):
                    if q_ref in label_map:
                        q_ids.append(questions[label_map[q_ref]]["id"])
                    elif q_ref.startswith("q-"):
                        q_ids.append(q_ref)
                if opt_ids or q_ids:
                    new_logic.append({
                        "options": opt_ids,
                        "questions": q_ids,
                        "subQuestions": rule.get("show_sub_questions", []),
                        "controlSubQuestions": rule.get("controlSubQuestions", "{}"),
                    })
            old_count = len(q.get("logic") or [])
            q["logic"] = new_logic
            applied.append(f"logic: {old_count} rules → {len(new_logic)} rules")

        # add_options
        if "add_options" in changes:
            if q.get("options") is None:
                q["options"] = []
            for new_opt in changes["add_options"]:
                opt_id = f"a-{int(time.time()*1000)}{len(q['options'])}"
                q["options"].append({
                    "id": opt_id, "text": new_opt.get("text", ""),
                    "mutex": new_opt.get("mutex", 0), "noRandom": new_opt.get("noRandom", 0),
                    "hasOther": new_opt.get("hasOther", 0), "hidden": 0,
                })
                applied.append(f"add option: '{new_opt.get('text','')[:20]}'")

        # remove_options
        if "remove_options" in changes:
            for rem in changes["remove_options"]:
                opts = q.get("options") or []
                for i, opt in enumerate(opts):
                    if rem in _strip_html(opt.get("text", "")):
                        opts.pop(i)
                        applied.append(f"remove option: '{rem[:20]}'")
                        break

        # sub_title_fixes
        if "sub_title_fixes" in changes:
            for fix in changes["sub_title_fixes"]:
                for sub in (q.get("subQuestions") or []):
                    if sub.get("id") == fix.get("sub_id"):
                        old_t = fix.get("old_title", "")
                        sub["title"] = fix.get("new_title", "")
                        applied.append(f"sub_title: '{old_t[:20]}' → '{fix.get('new_title','')[:20]}'")
                        break

        # description
        if "description" in changes:
            old_desc = q.get("description") or ""
            q["description"] = changes["description"]
            applied.append(f"description: '{str(old_desc)[:20]}' → '{str(changes['description'])[:20]}'")

        # 其他字段
        for field in ["random", "layout", "randomColumn", "noRandom", "maxLength", "minLength",
                      "maxRow", "validate", "starType", "level", "maxShowLength", "fixFirstLine", "displace"]:
            if field in changes:
                old_val = q.get(field)
                q[field] = changes[field]
                applied.append(f"{field}: {old_val} → {changes[field]}")

        change_log.append({
            "question": q_label or q_id,
            "title": q_title,
            "status": "modified" if applied else "no_change",
            "changes": applied,
        })

    # 无实际修改
    actual_changes = [c for c in change_log if c["status"] == "modified"]
    if not actual_changes:
        return {"status": "no_change", "message": "没有实际修改", "change_log": change_log}

    # 锁定并保存
    _log(f"Locking survey {survey_id}...")
    lock_ok = lock_survey(session, base_url, survey_id)
    if not lock_ok:
        return {
            "status": "error",
            "message": "锁定问卷失败！请先关闭浏览器中的问卷编辑器页面，然后重试。",
            "modifications_applied": 0, "change_log": change_log,
        }

    _log(f"Saving {len(actual_changes)} modifications...")
    save_result = save_survey(session, base_url, survey_data)
    if save_result["status"] != "success":
        return {"status": "error", "message": save_result["message"], "modifications_applied": 0, "change_log": change_log}

    # 验证
    _log("Verifying modifications (waiting 3s)...")
    time.sleep(3)
    verified_data = get_survey_full(session, base_url, survey_id)
    verification_failures = []

    if verified_data:
        verified_qs = verified_data.get("questions", [])
        verified_label_map = _build_label_map(verified_qs)

        for mod in modifications:
            q_label = mod.get("question_label")
            q_id = mod.get("question_id")
            changes = mod.get("changes", {})
            v_idx = verified_label_map.get(q_label) if q_label else None
            if v_idx is None and q_id:
                for idx, vq in enumerate(verified_qs):
                    if vq.get("id") == q_id:
                        v_idx = idx
                        break
            if v_idx is None:
                continue
            vq = verified_qs[v_idx]
            if "required" in changes and vq.get("required") != changes["required"]:
                verification_failures.append(f"{q_label or q_id}: required expected {changes['required']}, got {vq.get('required')}")
            if "title" in changes and _strip_html(vq.get("title", "")) != _strip_html(changes["title"]):
                verification_failures.append(f"{q_label or q_id}: title not updated")
            if "option_mutex" in changes:
                for opt_mod in changes["option_mutex"]:
                    opt_text = opt_mod.get("text", "")
                    for vopt in (vq.get("options") or []):
                        if opt_text and opt_text in _strip_html(vopt.get("text", "")):
                            for field in ["mutex", "noRandom", "hasOther"]:
                                if field in opt_mod and vopt.get(field) != opt_mod[field]:
                                    verification_failures.append(f"{q_label or q_id}: option '{opt_text}' {field} expected {opt_mod[field]}, got {vopt.get(field)}")
                            break

    if verification_failures:
        _log(f"VERIFICATION FAILED: {len(verification_failures)} issues! Retrying...")
        for vf in verification_failures:
            _log(f"  - {vf}")

        retry_data = get_survey_full(session, base_url, survey_id)
        if retry_data:
            retry_qs = retry_data.get("questions", [])
            retry_label_map = _build_label_map(retry_qs)
            for mod in modifications:
                q_label = mod.get("question_label")
                q_id = mod.get("question_id")
                changes = mod.get("changes", {})
                r_idx = retry_label_map.get(q_label) if q_label else None
                if r_idx is None and q_id:
                    for idx, rq in enumerate(retry_qs):
                        if rq.get("id") == q_id:
                            r_idx = idx
                            break
                if r_idx is None:
                    continue
                rq = retry_qs[r_idx]
                for field in ["required", "title"]:
                    if field in changes:
                        rq[field] = changes[field]
                if "option_mutex" in changes:
                    for opt_mod in changes["option_mutex"]:
                        opt_text = opt_mod.get("text", "")
                        for opt in (rq.get("options") or []):
                            if opt_text and opt_text in _strip_html(opt.get("text", "")):
                                for field in ["mutex", "noRandom", "hasOther"]:
                                    if field in opt_mod:
                                        opt[field] = opt_mod[field]
                                break

            lock_survey(session, base_url, survey_id)
            time.sleep(1)
            retry_save = save_survey(session, base_url, retry_data)

            if retry_save["status"] == "success":
                _log("Retry save returned success. Verifying again...")
                final_data = get_survey_full(session, base_url, survey_id)
                if final_data:
                    final_qs = final_data.get("questions", [])
                    final_label_map = _build_label_map(final_qs)
                    still_failed = []
                    for mod in modifications:
                        q_label = mod.get("question_label")
                        changes = mod.get("changes", {})
                        f_idx = final_label_map.get(q_label) if q_label else None
                        if f_idx is not None and "required" in changes:
                            if final_qs[f_idx].get("required") != changes["required"]:
                                still_failed.append(f"{q_label}: required still {final_qs[f_idx].get('required')}")
                    if still_failed:
                        return {
                            "status": "error",
                            "message": "保存后验证失败（重试后仍然不生效）。请关闭编辑器后重试。",
                            "verification_failures": still_failed,
                            "modifications_applied": 0, "change_log": change_log,
                        }
                    _log("Retry verification passed!")
                    return {
                        "status": "success", "message": "保存成功（重试后验证通过）",
                        "modifications_applied": len(actual_changes), "change_log": change_log,
                    }

        return {
            "status": "error",
            "message": "保存后验证失败。请确认浏览器未打开该问卷的编辑器。",
            "verification_failures": verification_failures,
            "modifications_applied": 0, "change_log": change_log,
        }

    _log("Verification passed!")
    lock_survey(session, base_url, survey_id)  # 续期/解锁

    return {
        "status": "success",
        "message": "保存成功（已验证生效）",
        "modifications_applied": len(actual_changes),
        "change_log": change_log,
    }
