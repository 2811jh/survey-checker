# -*- coding: utf-8 -*-
"""问卷级别操作：复制、新建、保存、锁定"""
import time

from core.constants import (
    API_SURVEY_COPY, API_SURVEY_SAVE, API_SURVEY_LOCK,
    API_SURVEY_ADD, API_SURVEY_SETTING, API_SURVEY_PREVIEW,
)
from core.utils import _log
from survey_io.fetcher import get_survey_full


# ─── 基础操作 ─────────────────────────────────────────────────────────────────

def lock_survey(session, base_url, survey_id):
    """锁定问卷（编辑前需要）"""
    request_id = str(int(time.time() * 1000))
    resp = session.get(
        f"{base_url}{API_SURVEY_LOCK}",
        params={"surveyId": survey_id, "requestId": request_id},
    )
    data = resp.json()
    return data.get("resultCode") == 100


def save_survey(session, base_url, survey_data):
    """保存整个问卷数据"""
    resp = session.post(f"{base_url}{API_SURVEY_SAVE}", json=survey_data)
    data = resp.json()
    if data.get("resultCode") != 100:
        _log(f"save_survey failed: {data.get('resultDesc')}")
        return {"status": "error", "message": data.get("resultDesc", "保存失败")}
    return {"status": "success", "message": "保存成功"}


# ─── 复制问卷 ─────────────────────────────────────────────────────────────────

def copy_survey(session, base_url, platform, source_id, new_name=None):
    """
    复制一份问卷。
    返回: {"status":"success", "new_id": ..., "new_name": ..., "preview_url": ...}
    """
    # 1. 获取源问卷信息
    _log(f"Fetching source survey {source_id} info...")
    source_data = get_survey_full(session, base_url, source_id)
    if not source_data:
        return {"status": "error", "message": f"获取源问卷 {source_id} 失败"}

    source_name = source_data.get("surveyName", f"问卷{source_id}")
    if new_name is None:
        new_name = f"{source_name}-副本"

    payload = {
        "id": source_id,
        "surveyName": new_name,
        "type": source_data.get("type", 0),
        "deliveryRange": source_data.get("deliveryRange", 0),
        "customUrlType": 0,    # 必须=0，否则不会生成静态预览文件
        "customUrl": "",
        "defaultLang": None,   # Web UI 传 null
        "lang": source_data.get("lang", "简体中文"),
        "groupId": -1,         # -1=私有（仅自己可见）
        "groupList": [],
        "remark": source_data.get("remark", ""),
        "gameName": source_data.get("gameName", ""),
        "directArea": source_data.get("directArea", 0),
        "surveyExtraJsonStruct": {"surveyCheckUser": {"uid": ""}},
    }

    _log(f"Copying '{source_name}' → '{new_name}'...")
    resp = session.post(f"{base_url}{API_SURVEY_COPY}", json=payload)
    data = resp.json()

    # 国外系统对 surveyExtraJsonStruct 敏感，失败时去掉该字段重试
    if data.get("resultCode") != 100 and platform == "global":
        _log(f"Copy failed ({data.get('resultDesc')}), retrying without surveyExtraJsonStruct...")
        payload.pop("surveyExtraJsonStruct", None)
        resp = session.post(f"{base_url}{API_SURVEY_COPY}", json=payload)
        data = resp.json()

    if data.get("resultCode") != 100:
        return {"status": "error", "message": f"复制失败: {data.get('resultDesc', '未知错误')}"}

    # 2. 提取新问卷 ID
    new_id = None
    resp_data = data.get("data")
    if isinstance(resp_data, dict):
        new_id = resp_data.get("id")
    if not new_id:
        resp_result = data.get("result")
        if isinstance(resp_result, dict):
            new_id = resp_result.get("id")
        elif resp_result:
            new_id = resp_result

    _log(f"Copy successful! New survey ID: {new_id}")

    # 3. 获取新问卷的 URL
    new_survey_url = None
    new_preview_url = None
    if new_id:
        new_full = get_survey_full(session, base_url, new_id)
        if new_full:
            new_survey_url = new_full.get("surveyUrl")
            new_preview_url = new_full.get("previewUrl")

            # 国外平台：调用 preview 接口触发服务端生成静态 HTML 文件
            if platform == "global":
                _log("Triggering static file generation via preview API...")
                try:
                    pr = session.get(f"{base_url}{API_SURVEY_PREVIEW}", params={"id": new_id})
                    pd = pr.json() if pr.text.strip() else {}
                    if pd.get("resultCode") == 100:
                        _log(f"Preview triggered: {pd.get('data', '')}")
                    else:
                        _log(f"Preview trigger response: {pd.get('resultDesc', '')}")
                except Exception as e:
                    _log(f"Preview trigger error (non-fatal): {e}")

    return {
        "status": "success",
        "message": "复制成功",
        "source_id": source_id,
        "source_name": source_name,
        "new_id": new_id,
        "new_name": new_name,
        "edit_url": f"{base_url}/index.html#/edit/{new_id}" if new_id else None,
        "survey_url": new_survey_url,
        "preview_url": new_preview_url,
    }


# ─── 新建问卷 ─────────────────────────────────────────────────────────────────

def create_survey(session, base_url, platform, name, game_name,
                  lang="简体中文", delivery_range=0, direct_area=0,
                  custom_url_type=0, remark=""):
    """
    从零创建一个新的空白问卷。
    返回: {"status":"success", "new_id": ..., "new_name": ..., ...}
    """
    default_lang_map = {
        "简体中文": "cn", "英文": "en", "繁體中文": "tw",
        "日本語": "ja", "한국어": "ko",
    }
    default_lang = default_lang_map.get(lang, "cn")

    payload = {
        "surveyName": name,
        "type": 0,
        "deliveryRange": delivery_range,
        "customUrlType": custom_url_type,
        "customUrl": "",
        "lang": lang,
        "defaultLang": default_lang,
        "groupId": -1,
        "groupList": [],
        "remark": remark,
        "gameName": game_name,
        "directArea": direct_area,
        "surveyExtraJsonStruct": {"surveyCheckUser": {"uid": ""}},
    }

    _log(f"Creating new survey '{name}' for game '{game_name}'...")
    resp = session.post(f"{base_url}{API_SURVEY_ADD}", json=payload)
    data = resp.json()

    # 国外系统对 surveyExtraJsonStruct 敏感，失败时用精简 payload 重试
    if data.get("resultCode") != 100 and platform == "global":
        _log(f"Create failed ({data.get('resultDesc')}), retrying without extra fields...")
        minimal = {k: v for k, v in payload.items() if k != "surveyExtraJsonStruct"}
        resp = session.post(f"{base_url}{API_SURVEY_ADD}", json=minimal)
        data = resp.json()

    if data.get("resultCode") != 100:
        return {"status": "error", "message": f"创建失败: {data.get('resultDesc', '未知错误')}"}

    resp_data = data.get("data", {})
    new_id = resp_data.get("id")
    _log(f"Create successful! New survey ID: {new_id}")

    # 修正语言设置（国外平台 /survey/add 创建后 lang 可能不正确）
    if new_id:
        setting_payload = {"id": new_id, "lang": lang, "defaultLang": default_lang}
        try:
            sr = session.post(f"{base_url}{API_SURVEY_SETTING}", json=setting_payload)
            sd = sr.json() if sr.text.strip() else {}
            if sd.get("resultCode") == 100:
                _log(f"Survey setting updated: lang={lang}")
            else:
                _log(f"Survey setting update failed: {sd.get('resultDesc', '')}")
        except Exception as e:
            _log(f"Survey setting update error: {e}")

    # ── 补全默认字段（模拟编辑器首次保存行为）────────────────────────
    if new_id:
        _log("Initializing survey defaults (simulating editor first-save)...")
        full_data = get_survey_full(session, base_url, new_id)
        if full_data:
            defaults = {
                "prefix": "为了给您提供更好的服务，希望您能抽出几分钟时间，将您的感受和建议告诉我们，我们非常重视每位用户的宝贵意见，期待您的参与！现在马上开始吧！",
                "prefixDiffStatus": 0,
                "endDescription": "您已完成本次问卷，感谢您的帮助与支持",
                "closeDescription": "该问卷已关闭，感谢您的关注",
                "endImgSrc": "/static/img/end.png",
                "closeImgSrc": "/static/img/close.png",
                "customUrlType": 0,
                "endType": 0,
                "endURL": "",
                "endButtonExist": 0,
                "endButtonUrl": "",
                "closeButtonExist": 0,
                "closeButtonUrl": "",
                "allowUserReadExamResult": 1,
                "showExamResult": 1,
                "redPackEnabled": 0,
            }
            for k, v in defaults.items():
                if full_data.get(k) is None:
                    full_data[k] = v
            # 确保 questions 为数组（空问卷时为 None，save 会 500）
            if full_data.get("questions") is None:
                full_data["questions"] = []

            lock_survey(session, base_url, new_id)
            save_result = save_survey(session, base_url, full_data)
            if save_result["status"] == "success":
                _log("Survey defaults initialized successfully")
            else:
                _log(f"Warning: defaults initialization failed: {save_result.get('message')}")

            # 触发预览 HTML 生成
            time.sleep(1)
            try:
                pr = session.get(f"{base_url}{API_SURVEY_PREVIEW}", params={"id": new_id})
                pd = pr.json() if pr.text.strip() else {}
                if pd.get("resultCode") == 100:
                    _log(f"Preview generated: {pd.get('data', '')}")
                else:
                    _log(f"Preview generation warning: {pd.get('resultDesc', '')}")
            except Exception as e:
                _log(f"Preview generation error (non-fatal): {e}")

    return {
        "status": "success",
        "message": "创建成功",
        "new_id": new_id,
        "new_name": name,
        "game_name": game_name,
        "edit_url": f"{base_url}/index.html#/edit/{new_id}" if new_id else None,
        "survey_url": resp_data.get("surveyUrl"),
        "preview_url": resp_data.get("previewUrl"),
    }
