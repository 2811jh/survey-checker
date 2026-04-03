# -*- coding: utf-8 -*-
"""
问卷校准（calibrate）：按 R1–R8 规则自动扫描并修复问卷。
"""
from core.utils import _log, _strip_html, _build_label_map
from survey_io.fetcher import get_survey_full
from operations.question_ops import modify_questions

# ── 规则常量 ──────────────────────────────────────────────────────────────────

# 排他性选项关键词 — R3 规则
EXCLUSIVE_KEYWORDS = [
    "以上都没", "以上均没", "都没有", "都不是", "没有以上", "以上皆无",
    "我没有", "我没在", "只玩", "我认为", "没遇到", "没有不满意",
    "以上都不", "以上均不", "都不需要", "都不想", "以上皆不",
]

# "其他"选项关键词 — R2 / R8 规则
OTHER_KEYWORDS = ["其他"]

# 异常末尾标点 — R7 规则
ABNORMAL_TRAILING_PUNCT = [
    "：", ":", "；", ";", "，", ",", "、",
]


# ── 核心扫描函数 ──────────────────────────────────────────────────────────────

def calibrate(session, base_url, survey_id, dry_run=False):
    """
    问卷校准：按 R1-R8 固定规则扫描问卷，自动生成修复方案并执行。
    dry_run=True 时仅输出方案，不执行修改。
    """
    _log(f"Calibrate scanning survey {survey_id}...")
    data = get_survey_full(session, base_url, survey_id)
    if not data:
        return {"status": "error", "message": "获取问卷数据失败"}

    qs = data.get("questions") or []
    label_map = _build_label_map(qs)
    issues = []
    modifications = []

    for label, idx in sorted(label_map.items(), key=lambda x: x[1]):
        if not label.startswith("Q"):
            continue
        q = qs[idx]
        qtype = q.get("type", "")
        opts = q.get("options") or []
        title_text = _strip_html(q.get("title", ""))[:60]
        changes = {}
        option_mods = []

        # ── R1: 多选题选项>=8 → layout=2, >=20 → layout=3 ─────────────────
        if qtype == "checkbox" and len(opts) >= 8:
            target_layout = 3 if len(opts) >= 20 else 2
            current_layout = q.get("layout") or 0
            if current_layout != target_layout:
                issues.append({
                    "rule": "R1", "question": label,
                    "desc": f"{len(opts)}个选项, layout={current_layout} → 应改为{target_layout}",
                    "title": title_text,
                })
                changes["layout"] = target_layout
                changes["maxRow"] = target_layout

        # ── R2: 多选题 random=1 + 特殊项 noRandom=1 ───────────────────────
        if qtype == "checkbox":
            if q.get("random", 0) != 1:
                issues.append({
                    "rule": "R2", "question": label,
                    "desc": f"random={q.get('random', 0)} → 应改为1",
                    "title": title_text,
                })
                changes["random"] = 1

            for o in opts:
                otxt = _strip_html(o.get("text", ""))
                is_special = (
                    o.get("hasOther") == 1
                    or o.get("mutex") == 1
                    or any(kw == otxt.strip() for kw in OTHER_KEYWORDS)
                )
                if is_special and o.get("noRandom", 0) != 1:
                    issues.append({
                        "rule": "R2", "question": label,
                        "desc": f"选项'{otxt[:20]}' noRandom=0 → 应为1（固定位置不参与随机）",
                        "title": title_text,
                    })
                    option_mods.append({"text": otxt[:30], "noRandom": 1})

        # ── R3: 排他性选项必须 mutex=1 ─────────────────────────────────────
        if qtype == "checkbox":
            for o in opts:
                otxt = _strip_html(o.get("text", ""))
                if any(kw in otxt for kw in EXCLUSIVE_KEYWORDS):
                    if o.get("mutex", 0) != 1:
                        issues.append({
                            "rule": "R3", "question": label,
                            "desc": f"'{otxt[:20]}' 应为互斥 mutex=1",
                            "title": title_text,
                        })
                        option_mods.append({"text": otxt[:30], "mutex": 1, "noRandom": 1})

        # ── R4: 文本题非必填 ────────────────────────────────────────────────
        if qtype == "blank" and q.get("required", 0) == 1:
            issues.append({
                "rule": "R4", "question": label,
                "desc": "文本题 required=1 → 应改为0",
                "title": title_text,
            })
            changes["required"] = 0

        # ── R6: 必填一致性检查 ──────────────────────────────────────────────
        NON_QUESTION_TYPES = ("describe", "paging", "imply")
        title_full = _strip_html(q.get("title", ""))
        has_non_required_hint = "非必填" in title_full

        if qtype not in NON_QUESTION_TYPES and qtype != "blank":
            if has_non_required_hint and q.get("required", 0) != 0:
                issues.append({
                    "rule": "R6", "question": label,
                    "desc": "题干标注「非必填」但 required=1 → 应改为0",
                    "title": title_text,
                })
                changes["required"] = 0
            elif not has_non_required_hint and q.get("required", 0) != 1:
                issues.append({
                    "rule": "R6", "question": label,
                    "desc": "非文本题 required=0 → 应改为1",
                    "title": title_text,
                })
                changes["required"] = 1

        # ── R7: 异常标点符号检查（子问题标题末尾） ─────────────────────────
        sub_qs = q.get("subQuestions") or []
        for sub in sub_qs:
            sub_title = _strip_html(sub.get("title", ""))
            if sub_title:
                for punct in ABNORMAL_TRAILING_PUNCT:
                    if sub_title.endswith(punct):
                        issues.append({
                            "rule": "R7", "question": label,
                            "desc": f"子问题'{sub_title[:25]}' 末尾含异常标点「{punct}」→ 应去除",
                            "title": title_text,
                        })
                        cleaned = sub_title.rstrip("".join(ABNORMAL_TRAILING_PUNCT)).strip()
                        if cleaned != sub_title:
                            if "sub_title_fixes" not in changes:
                                changes["sub_title_fixes"] = []
                            changes["sub_title_fixes"].append({
                                "sub_id": sub.get("id"),
                                "old_title": sub_title,
                                "new_title": cleaned,
                            })
                        break

        # ── R8: "其他"选项必须开启输入框 (hasOther=1) ──────────────────────
        if qtype in ("checkbox", "radio"):
            for o in opts:
                otxt = _strip_html(o.get("text", ""))
                if any(kw == otxt.strip() for kw in OTHER_KEYWORDS):
                    if o.get("hasOther", 0) != 1:
                        issues.append({
                            "rule": "R8", "question": label,
                            "desc": f"选项'{otxt[:20]}' hasOther=0 → 应开启 hasOther=1",
                            "title": title_text,
                        })
                        option_mods.append({"text": otxt[:30], "hasOther": 1})

        # 汇总本题修改
        if changes or option_mods:
            mod = {"question_label": label, "changes": dict(changes)}
            if option_mods:
                mod["changes"]["option_mutex"] = option_mods
            modifications.append(mod)

    # ── R5: 满意度追问逻辑检查（仅告警，不自动修复）─────────────────────────
    r5_warnings = []
    id_to_label = {qs[i].get("id"): lbl for lbl, i in label_map.items() if qs[i].get("id")}

    for label, idx in sorted(label_map.items(), key=lambda x: x[1]):
        if not label.startswith("Q"):
            continue
        q = qs[idx]
        qtype = q.get("type", "")
        title_full = _strip_html(q.get("title", ""))
        if qtype in ("star", "rect-star", "nps") and "满意" in title_full:
            parent_logic_targets = {
                qid
                for rule in (q.get("logic") or [])
                for qid in (rule.get("questions") or [])
            }
            for offset in range(1, 4):
                next_idx = idx + offset
                if next_idx >= len(qs):
                    break
                next_q = qs[next_idx]
                next_type = next_q.get("type", "")
                if next_type in ("paging", "describe", "imply"):
                    continue
                next_title = _strip_html(next_q.get("title", ""))
                if any(kw in next_title for kw in ("不满意", "不太满意", "一般")):
                    next_qid = next_q.get("id")
                    has_own_logic = bool(next_q.get("logic"))
                    has_parent_logic = next_qid in parent_logic_targets
                    if not has_own_logic and not has_parent_logic:
                        next_label = next((nl for nl, ni in label_map.items() if ni == next_idx), f"idx{next_idx}")
                        r5_warnings.append({
                            "rule": "R5", "question": next_label,
                            "desc": f"追问题缺少显示逻辑（可能应受 {label} 评分控制）",
                            "title": next_title[:50],
                            "auto_fixable": False,
                        })

    # ── 汇总结果 ──────────────────────────────────────────────────────────────
    all_issues = issues + r5_warnings
    result = {
        "status": "scanned",
        "survey_id": survey_id,
        "total_issues": len(all_issues),
        "auto_fixable": len(modifications),
        "issues": all_issues,
        "modifications": modifications,
    }

    if dry_run or not modifications:
        result["message"] = (
            f"扫描完成：发现 {len(all_issues)} 个问题，"
            f"其中 {len(modifications)} 个可自动修复（dry-run 模式，未执行）"
            if dry_run else
            f"扫描完成：发现 {len(all_issues)} 个问题，"
            f"{'无需自动修复' if not modifications else f'{len(modifications)} 个可自动修复'}"
        )
        return result

    # 执行修复
    _log(f"Calibrate: applying fixes for {len(modifications)} questions...")
    fix_result = modify_questions(session, base_url, survey_id, modifications)
    result["fix_result"] = fix_result
    result["message"] = (
        f"扫描发现 {len(all_issues)} 个问题，"
        f"已自动修复 {fix_result.get('modifications_applied', 0)} 项"
    )
    result["status"] = fix_result.get("status", "error")
    return result
