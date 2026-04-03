# -*- coding: utf-8 -*-
"""问卷数据读取：搜索、获取完整数据、获取题目详情、结构化输出"""
from datetime import datetime

from core.constants import (
    API_SURVEY_LIST, API_QUESTION_LIST, API_QUESTION_DETAIL,
    API_SURVEY_DETAIL,
)
from core.utils import _log, _strip_html


# ─── 基础读取 ─────────────────────────────────────────────────────────────────

def search_surveys(session, base_url, name="", page=1):
    """按名称搜索问卷列表（自动适配国内/国外平台参数格式）"""
    payloads = [
        {"pageNo": page, "surveyName": name, "status": "-1",
         "deliveryRange": -1, "type": -1, "groupId": -1, "groupUser": -1, "gameName": ""},
        {"pageNo": page, "surveyName": name, "status": "0", "gameName": ""},
        {"pageNo": page, "surveyName": name},
    ]
    data = None
    for payload in payloads:
        try:
            resp = session.post(f"{base_url}{API_SURVEY_LIST}", json=payload)
            d = resp.json()
            if d.get("resultCode") == 100:
                data = d
                break
        except Exception:
            continue

    if data is None:
        return {"status": "error", "message": "搜索请求失败"}

    surveys = data.get("dataList", [])
    _STATUS_MAP = {0: "未发布", 1: "回收中", 2: "已停止", 3: "已关闭"}
    results = []
    for s in surveys:
        raw_status = s.get("status", -1)
        results.append({
            "id": s.get("id"),
            "name": s.get("surveyName", ""),
            "status": raw_status,
            "statusLabel": _STATUS_MAP.get(raw_status, f"未知({raw_status})"),
            "responses": s.get("recycleCount", 0),
            "createTime": s.get("createTime", ""),
        })

    page_info = data.get("page") or {}
    total = page_info.get("totalCount", len(results))
    return {"status": "success", "surveys": results, "total": total}


def get_survey_full(session, base_url, survey_id):
    """获取问卷的完整数据（用于修改后 save 回去）"""
    resp = session.get(f"{base_url}{API_SURVEY_DETAIL}", params={"id": survey_id})
    data = resp.json()
    if data.get("resultCode") != 100:
        _log(f"get_survey_full failed: {data.get('resultDesc')}")
        return None
    return data.get("data")


def get_question_list(session, base_url, survey_id):
    """获取问卷的题目列表（统计分析接口，含题型信息）"""
    resp = session.post(
        f"{base_url}{API_QUESTION_LIST}",
        json={"surveyId": survey_id, "type": "", "keyWord": "", "questionExportList": []},
    )
    data = resp.json()
    if data.get("resultCode") != 100:
        _log(f"get_question_list failed: {data.get('resultDesc')}")
        return None
    inner = data.get("data")
    if isinstance(inner, dict):
        return inner.get("questionExportList") or []
    return []


def get_question_detail(session, base_url, survey_id):
    """获取问卷的完整题目详情（含选项文本 + 逻辑设置）"""
    resp = session.get(
        f"{base_url}{API_QUESTION_DETAIL}",
        params={"surveyId": survey_id, "from": "dataclean"},
    )
    data = resp.json()
    if data.get("resultCode") != 100:
        _log(f"get_question_detail failed: {data.get('resultDesc')}")
        return None
    return data.get("dataList") or data.get("data") or []


# ─── 数据合并（内部） ─────────────────────────────────────────────────────────

def _build_questions_from_detail(detail_list):
    """当 stat API 不可用时，直接从 detail 数据构建题目列表（国外系统 fallback）"""
    STR_TYPE_MAP = {
        "imply": ("隐含题", "Y"), "describe": ("说明题", "T"), "paging": ("分页符", "T"),
        "radio": ("单选题", "Q"), "checkbox": ("多选题", "Q"), "blank": ("填空题", "Q"),
        "multiple-text": ("多项填空题", "Q"), "star": ("星级评分题", "Q"),
        "rect-star": ("矩阵星级题", "Q"), "rect-radio": ("矩阵单选题", "Q"),
        "rect-checkbox": ("矩阵多选题", "Q"), "nps": ("NPS题", "Q"),
        "rect-nps": ("矩阵NPS题", "Q"), "scale": ("量表题", "Q"),
        "sort": ("排序题", "Q"), "dropdown": ("下拉选择题", "Q"),
        "language": ("语言选择题", "Q"), "date": ("日期选择题", "Q"),
        "option-merge": ("选项合并", "T"), "question-merge": ("多题合并", "T"),
    }
    prefix_counters = {"Q": 0, "Y": 0, "T": 0}
    questions = []
    for detail in detail_list:
        q_type = detail.get("type", "")
        type_name, prefix = STR_TYPE_MAP.get(q_type, (f"未知({q_type})", "Q"))
        prefix_counters[prefix] = prefix_counters.get(prefix, 0) + 1
        label = f"{prefix}{prefix_counters[prefix]}"
        question = {
            "label": label, "prefix": prefix, "index": prefix_counters[prefix],
            "id": detail.get("id"),
            "title": _strip_html(detail.get("title", "")),
            "type_code": q_type, "type": type_name,
            "required": detail.get("required", 0),
            "options": [], "logic": None, "sub_questions": [],
            "layout": detail.get("layout", 0),
            "maxRow": detail.get("maxRow", 1),
        }
        for opt in (detail.get("options") or []):
            opt_text = _strip_html(opt.get("text", ""))
            if opt_text:
                question["options"].append({
                    "id": opt.get("id"), "text": opt_text,
                    "mutex": opt.get("mutex", 0), "hasOther": opt.get("hasOther", 0),
                    "hidden": opt.get("hidden", 0), "noRandom": opt.get("noRandom", 0),
                })
        logic = detail.get("logic") or detail.get("jumpLogic") or detail.get("displayLogic")
        if logic:
            question["logic"] = logic
        for sub in (detail.get("subQuestions") or []):
            sub_title = _strip_html(sub.get("title", ""))
            if sub_title:
                question["sub_questions"].append({"id": sub.get("id"), "title": sub_title})
        if detail.get("description"):
            question["description"] = _strip_html(detail["description"])
        if detail.get("random"):
            question["random"] = detail["random"]
        questions.append(question)
    return questions


def _merge_question_data(stat_questions, detail_data):
    """合并统计接口和详情接口的数据"""
    detail_map = {}
    if isinstance(detail_data, list):
        for q in detail_data:
            qid = q.get("id")
            if qid:
                detail_map[qid] = q
    elif isinstance(detail_data, dict):
        q_list = detail_data.get("questionList") or detail_data.get("list") or []
        for q in q_list:
            qid = q.get("id")
            if qid:
                detail_map[qid] = q

    STR_TYPE_MAP = {
        "imply": ("隐含题", "Y"), "describe": ("说明题", "T"), "paging": ("分页符", "T"),
        "radio": ("单选题", "Q"), "checkbox": ("多选题", "Q"), "blank": ("填空题", "Q"),
        "multiple-text": ("多项填空题", "Q"), "star": ("星级评分题", "Q"),
        "rect-star": ("矩阵星级题", "Q"), "rect-radio": ("矩阵单选题", "Q"),
        "rect-checkbox": ("矩阵多选题", "Q"), "nps": ("NPS题", "Q"),
        "rect-nps": ("矩阵NPS题", "Q"), "scale": ("量表题", "Q"),
        "sort": ("排序题", "Q"), "dropdown": ("下拉选择题", "Q"),
        "cascade": ("关联选择题", "Q"), "language": ("语言选择题", "Q"),
        "date": ("日期选择题", "Q"), "city": ("城市选择题", "Q"),
        "file": ("文件上传题", "Q"), "option-merge": ("选项合并", "T"),
        "question-merge": ("多题合并", "T"),
    }
    NUM_TYPE_MAP = {
        1: ("单选题", "Q"), 2: ("多选题", "Q"), 3: ("填空题", "Q"),
        4: ("矩阵单选题", "Q"), 5: ("矩阵多选题", "Q"), 6: ("排序题", "Q"),
        7: ("量表题", "Q"), 8: ("NPS题", "Q"), 9: ("下拉选择题", "Q"),
        10: ("日期选择题", "Q"), 11: ("文件上传题", "Q"),
    }

    prefix_counters = {"Q": 0, "Y": 0, "T": 0}
    merged = []
    for sq in stat_questions:
        qid = sq.get("id") or sq.get("questionId")
        q_type_code = sq.get("type") or sq.get("questionType", 0)

        if isinstance(q_type_code, str):
            type_name, prefix = STR_TYPE_MAP.get(q_type_code, (f"未知({q_type_code})", "Q"))
        else:
            type_name, prefix = NUM_TYPE_MAP.get(q_type_code, (f"未知({q_type_code})", "Q"))

        prefix_counters[prefix] = prefix_counters.get(prefix, 0) + 1
        label = f"{prefix}{prefix_counters[prefix]}"
        detail = detail_map.get(qid, {})
        required_val = detail.get("required") if detail.get("required") is not None else sq.get("required", 0)

        question = {
            "label": label, "prefix": prefix, "index": prefix_counters[prefix],
            "id": qid,
            "title": _strip_html(sq.get("title") or sq.get("questionTitle", "")),
            "type_code": q_type_code, "type": type_name,
            "required": required_val,
            "options": [], "logic": None, "sub_questions": [],
        }

        options = detail.get("options") or sq.get("options") or []
        for opt in options:
            opt_text = _strip_html(opt.get("text") or opt.get("optionText", ""))
            if opt_text:
                question["options"].append({
                    "id": opt.get("id"), "text": opt_text,
                    "mutex": opt.get("mutex", 0), "hasOther": opt.get("hasOther", 0),
                    "hidden": opt.get("hidden", 0), "noRandom": opt.get("noRandom", 0),
                })

        logic = detail.get("logic") or detail.get("jumpLogic") or detail.get("displayLogic")
        if logic:
            question["logic"] = logic

        sub_questions = detail.get("subQuestions") or sq.get("subQuestions") or []
        for sub in sub_questions:
            question["sub_questions"].append({
                "id": sub.get("id"),
                "title": _strip_html(sub.get("title") or sub.get("subTitle", "")),
            })

        if detail.get("description"):
            question["description"] = _strip_html(detail["description"])
        if detail.get("random"):
            question["random"] = detail["random"]

        merged.append(question)
    return merged


# ─── 结构化抓取（主接口）─────────────────────────────────────────────────────

def fetch_survey(session, base_url, survey_id=None, survey_name=None, select_index=None):
    """
    抓取指定问卷的完整内容，返回结构化数据。
    注意：调用方负责确保认证有效（_ensure_auth）。
    """
    target_id = survey_id
    target_name = survey_name or ""

    # 按名称搜索
    if not target_id and target_name:
        _log(f"Searching for survey: {target_name}")
        search_result = search_surveys(session, base_url, target_name)
        if search_result["status"] != "success":
            return search_result

        matches = search_result["surveys"]
        if not matches:
            return {"status": "no_match", "message": f"未找到包含「{target_name}」的问卷"}

        if len(matches) == 1:
            target_id = matches[0]["id"]
            target_name = matches[0]["name"]
        elif select_index is not None and 0 <= select_index < len(matches):
            target_id = matches[select_index]["id"]
            target_name = matches[select_index]["name"]
        else:
            return {
                "status": "multiple_matches",
                "message": f"找到 {len(matches)} 份匹配的问卷，请选择：",
                "surveys": matches,
            }

    if not target_id:
        return {"status": "error", "message": "请提供问卷 ID 或名称"}

    _log(f"Fetching survey: {target_name} (ID: {target_id})")
    survey_info = {"id": target_id, "name": target_name}

    # 获取题目列表（统计接口）
    stat_questions = get_question_list(session, base_url, target_id)
    if stat_questions is None:
        return {"status": "error", "message": f"无法获取问卷题目列表（ID: {target_id}）"}
    _log(f"Got {len(stat_questions)} questions from stat API")

    # 获取题目详情（编辑接口）
    detail_questions = get_question_detail(session, base_url, target_id)
    _log(f"Got detail data: {type(detail_questions)}, len={len(detail_questions) if isinstance(detail_questions, list) else 'N/A'}")

    # 合并数据
    if not stat_questions and not detail_questions:
        _log("Both APIs empty, falling back to survey/detail full data mode")
        full_data = get_survey_full(session, base_url, target_id)
        detail_list = (full_data or {}).get("questions") or []
        questions = _build_questions_from_detail(detail_list)
        if full_data and not survey_info.get("name"):
            survey_info["name"] = full_data.get("surveyName", "")
    elif not stat_questions and detail_questions:
        _log("Stat API returned empty, falling back to detail-only mode")
        detail_list = detail_questions if isinstance(detail_questions, list) else []
        questions = _build_questions_from_detail(detail_list)
    else:
        questions = _merge_question_data(stat_questions, detail_questions)

    q_count = sum(1 for q in questions if q.get("prefix") == "Q")
    y_count = sum(1 for q in questions if q.get("prefix") == "Y")
    t_count = sum(1 for q in questions if q.get("prefix") == "T")

    return {
        "status": "success",
        "survey_info": survey_info,
        "questions": questions,
        "total_items": len(questions),
        "question_count": q_count,
        "hidden_count": y_count,
        "description_count": t_count,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
