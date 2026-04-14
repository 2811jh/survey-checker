# -*- coding: utf-8 -*-
"""题目构建：将 spec 字典转换为平台 API 所需的完整 question 对象"""
import copy as copy_mod

from core.utils import _gen_id, _strip_html, _log


# ─── 模板查找 ─────────────────────────────────────────────────────────────────

def find_template(questions, qtype):
    """在现有题目中找到同类型模板，深拷贝作为新题目的基础"""
    for q in questions:
        if q.get("type") == qtype:
            return copy_mod.deepcopy(q)
    return None


# ─── 默认骨架 ─────────────────────────────────────────────────────────────────

def _default_skeleton(qtype):
    """返回完整骨架 dict，包含前端编辑器和预览组件所需的全部字段"""
    return {
        "type": qtype,
        "title": "",
        "description": None,
        "index": "0",
        "required": 1,
        "hidden": 0,
        "random": 0,
        "randomColumn": 0,
        "maxRow": 3 if qtype == "blank" else 1,
        "maxLength": -1,
        "maxShowLength": -1,
        "minLength": -1,
        "layout": 0 if qtype in ("star", "paging") else 1,
        "displayForm": 0,
        "levels": None if qtype == "star" else ["", ""],
        "groups": None if qtype == "star" else [],
        "logic": [{"options": [], "questions": [], "subQuestions": [], "controlSubQuestions": "{}"}],
        "tag": "",
        "tagCustom": "",
        "referType": 0,
        "questionLang": "",
        "mark": 0,
        "zoom": 1,
        "fixFirstLine": 1,
        "validate": 0,
        "level": 0,
        "score": 10,
        "starType": 1,
        "star": 1,
        "starEnd": 5,
        "startDesc": "",
        "middleDesc": "",
        "endDesc": "",
        "enrollable": 0,
        "nps": 0,
        "openScore": 1,
        "area": 1,
        "dataTrend": "",
        "noRandom": 0,
        "placeholder": None,
    }


# ─── 选项构建 ─────────────────────────────────────────────────────────────────

def _build_option(opt):
    """将字符串或 dict 选项转换为完整的 option 对象"""
    if isinstance(opt, str):
        return {
            "id": _gen_id("a"),
            "text": opt,
            "hasOther": 0,
            "otherRequired": 0,
            "otherPlaceholder": "",
            "weight": None,
            "noRandom": 0,
            "mutex": 0,
            "referType": 0,
            "referQuestionId": None,
            "optionReferId": None,
            "hidden": 0,
            "referOptionId": None,
            "bottomOrTop": 0,
        }
    return {
        "id": _gen_id("a"),
        "text": opt.get("text", ""),
        "hasOther": opt.get("hasOther", 0),
        "otherRequired": opt.get("otherRequired", 0),
        "otherPlaceholder": opt.get("otherPlaceholder", ""),
        "weight": opt.get("weight", None),
        "noRandom": opt.get("noRandom", 0),
        "mutex": opt.get("mutex", 0),
        "referType": 0,
        "referQuestionId": None,
        "optionReferId": None,
        "hidden": 0,
        "referOptionId": None,
        "bottomOrTop": 0,
    }


# ─── 子题目构建 ───────────────────────────────────────────────────────────────

def _build_sub_question(sub, sub_type):
    """将 str 或 dict 子题目转换为完整的 sub_question 对象"""
    sub_title = sub if isinstance(sub, str) else sub.get("title", "")
    sub_obj = {
        "id": _gen_id("a"),
        "title": sub_title,
        "description": None,
        "type": sub_type,
        "options": None,
        "subQuestions": None,
        "index": None,
        "maxRow": 1,
        "maxLength": -1 if sub_type != "blank" else 20,
        "maxShowLength": -1,
        "minLength": -1,
        "random": 0,
        "randomColumn": 0,
        "required": 0,
        "validate": None,
        "level": None,
        "levels": None,
        "groups": None,
        "logic": None,
        "noRandom": 0,
        "starType": 1 if sub_type == "star" else 0,
        "star": 1 if sub_type == "star" else 0,
        "starEnd": 5 if sub_type == "star" else 0,
        "startDesc": None,
        "middleDesc": None,
        "endDesc": None,
        "placeholder": sub.get("placeholder", "") if isinstance(sub, dict) else "",
        "hidden": 0,
        "layout": 0,
        "displayForm": 0,
        "tag": None,
        "referType": 0,
        "zoom": 1,
        "nps": 0,
        "openScore": 1 if sub_type == "star" else 0,
        "area": 1,
    }
    # 矩阵量表题的评分范围可以自定义
    if sub_type == "star" and isinstance(sub, dict):
        sub_obj["starEnd"] = sub.get("starEnd", 5)
    return sub_obj


# ─── 主构建函数 ───────────────────────────────────────────────────────────────

def build_question(spec, existing_questions):
    """
    根据 spec 构建完整的 question 对象。
    spec 格式见 SurveyKit 文档（type/title/options/required/random/layout/insert/...）
    """
    qtype = spec.get("type", "radio")

    # 优先找同类型模板深拷贝，找不到就用骨架
    q = find_template(existing_questions, qtype) or _default_skeleton(qtype)

    # 生成新 ID + 设置标题
    q["id"] = _gen_id("q")
    q["title"] = spec.get("title", q.get("title", ""))

    # 通用字段
    for field in ["required", "random", "layout", "maxRow", "maxLength",
                   "placeholder", "hidden", "randomColumn", "displayForm"]:
        if field in spec:
            q[field] = spec[field]

    # layout/maxRow 联动（checkbox/radio 多列布局）
    if qtype in ("checkbox", "radio") and "layout" in spec:
        layout_val = spec["layout"]
        if layout_val in (2, 3):
            q["maxRow"] = layout_val

    # ── 隐含题 ───────────────────────────────────────────────────────────
    if qtype == "imply":
        q["hidden"] = 1
        q["required"] = 1
        q["level"] = 1
        q["layout"] = 0
        q["levels"] = None
        q["groups"] = None
        q["tag"] = None
        q["mark"] = None
        q["questionLang"] = None
        q["fixFirstLine"] = 0
        for _f in ["score", "starType", "star", "starEnd", "startDesc",
                    "middleDesc", "endDesc", "enrollable", "tagCustom", "validate"]:
            q.pop(_f, None)
        if "varName" in spec:
            q["variableName"] = spec["varName"]
        if "varType" in spec:
            q["level"] = int(spec["varType"]) if spec["varType"] else 1

    # ── 量表题描述文案 ────────────────────────────────────────────────────
    for field in ["startDesc", "middleDesc", "endDesc"]:
        if field in spec:
            q[field] = spec[field]

    # ── 量表题 / NPS 评分范围 ─────────────────────────────────────────────
    if qtype in ("star", "rect-star"):
        if spec.get("_is_nps"):
            q["nps"] = 1
            q["starType"] = 4        # 数字样式（1=星形 2=爱心 3=点赞 4=数字 5=方块）
            q["star"] = 0
            q["starEnd"] = 10
            q["openScore"] = 1
            q["score"] = None
            q["tag"] = "recommend_willing"   # NPS 题默认标签：评价-推荐意愿
            q["tagCustom"] = "recommend_willing"   # 标签：评价-推荐意愿
        else:
            q["starType"] = q.get("starType") or 1
            q["star"] = q.get("star") or 1
            q["starEnd"] = q.get("starEnd") or 5
            q["openScore"] = 1
            q["score"] = 10

    # ── 选项 ──────────────────────────────────────────────────────────────
    if "options" in spec:
        q["options"] = [_build_option(opt) for opt in spec["options"]]

    # ── 子题目 ────────────────────────────────────────────────────────────
    if "subQuestions" in spec:
        sub_type_map = {
            "rect-star": "star", "rect-radio": "radio",
            "rect-checkbox": "checkbox", "multiple-text": "blank",
        }
        sub_type = sub_type_map.get(qtype)
        q["subQuestions"] = [_build_sub_question(sub, sub_type) for sub in spec["subQuestions"]]

    # ── paging/describe/blank 不需要 options ──────────────────────────────
    if qtype in ("paging", "describe", "blank", "multiple-text"):
        if "options" not in spec:
            q["options"] = [] if qtype == "paging" else None

    return q


# ─── 插入位置解析 ─────────────────────────────────────────────────────────────

def resolve_insert_position(spec, questions, label_map):
    """解析插入位置，返回数组索引。支持 afterLabel / afterTitle / index"""
    insert = spec.get("insert", {})

    if "afterLabel" in insert:
        label = insert["afterLabel"]
        if label in label_map:
            return label_map[label] + 1
        _log(f"WARNING: label '{label}' not found, appending to end")
        return len(questions)

    if "afterTitle" in insert:
        target_title = insert["afterTitle"]
        for i, q in enumerate(questions):
            if target_title in _strip_html(q.get("title", "")):
                return i + 1
        _log(f"WARNING: title '{target_title}' not found, appending to end")
        return len(questions)

    if "index" in insert:
        return min(insert["index"], len(questions))

    return len(questions)
