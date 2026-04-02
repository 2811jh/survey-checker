# -*- coding: utf-8 -*-
"""平台配置与 API 端点常量"""
import os

PLATFORMS = {
    "cn": {
        "label": "国内",
        "base_url": "https://survey-game.163.com",
        "cookie_domain": "survey-game.163.com",
        "target_cookies": {"SURVEY_TOKEN", "JSESSIONID", "P_INFO"},
        "required_cookies": {"SURVEY_TOKEN", "JSESSIONID"},
    },
    "global": {
        "label": "国外",
        "base_url": "https://survey-game.easebar.com",
        "cookie_domain": "survey-game.easebar.com",
        "target_cookies": {"oversea-online_SURVEY_TOKEN", "SURVEY_TOKEN", "JSESSIONID", "P_INFO"},
        "required_cookies": {"oversea-online_SURVEY_TOKEN"},
    },
}
DEFAULT_PLATFORM = "cn"

# SCRIPT_DIR 指向 scripts/ 目录（本文件在 scripts/core/ 下，需要上一级）
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_file(platform="cn"):
    if platform == "cn":
        return os.path.join(SCRIPT_DIR, "config.json")
    return os.path.join(SCRIPT_DIR, f"config_{platform}.json")


def _profile_dir(platform="cn"):
    if platform == "cn":
        return os.path.join(SCRIPT_DIR, ".browser_profile")
    return os.path.join(SCRIPT_DIR, f".browser_profile_{platform}")


# API 端点
API_SURVEY_LIST     = "/view/survey/list"
API_QUESTION_LIST   = "/view/survey_stat/get_question_list"
API_QUESTION_DETAIL = "/view/question/list"
API_SURVEY_DETAIL   = "/view/survey/detail"
API_SURVEY_SAVE     = "/view/survey/save"
API_SURVEY_LOCK     = "/view/survey/set_lock"
API_SURVEY_COPY     = "/view/template/survey/quote"
API_SURVEY_SETTING  = "/view/survey/setting"
API_SURVEY_ADD      = "/view/survey/add"
API_SURVEY_PREVIEW  = "/view/survey/preview"
