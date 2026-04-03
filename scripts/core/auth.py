# -*- coding: utf-8 -*-
"""Cookie 管理：加载、保存、有效性检查、Playwright 自动刷新"""
import json
import os
import time

from .constants import PLATFORMS, API_SURVEY_LIST, _config_file, _profile_dir
from .utils import _log


def load_cookies(platform="cn"):
    """从 config json 读取已保存的 Cookie，返回 dict"""
    cfg = _config_file(platform)
    if not os.path.exists(cfg):
        return {}
    with open(cfg, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("cookies", {})


def save_cookies(platform, cookie_dict):
    """将 Cookie dict 保存到 config json"""
    cfg = _config_file(platform)
    config = {
        "cookies": cookie_dict,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    _log(f"Cookies saved to {cfg}")


def check_auth(session, platform):
    """检查 Cookie 是否有效，返回 True/False"""
    base_url = PLATFORMS[platform]["base_url"]
    payloads = [
        {"pageNo": 1, "surveyName": "", "status": "-1",
         "deliveryRange": -1, "type": -1, "groupId": -1,
         "groupUser": -1, "gameName": ""},
        {"pageNo": 1, "surveyName": "", "status": "0", "gameName": ""},
    ]
    for payload in payloads:
        try:
            resp = session.post(f"{base_url}{API_SURVEY_LIST}", json=payload)
            data = resp.json()
            if data.get("resultCode") == 100:
                return True
        except Exception as e:
            _log(f"Auth check failed: {e}")
    return False


def refresh_cookie(platform="cn", timeout=300):
    """
    用 Playwright 打开浏览器，等待登录后自动保存 Cookie。
    返回 True=成功，False=失败
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    plat = PLATFORMS[platform]
    base_url = plat["base_url"]
    profile_dir_path = _profile_dir(platform)
    target_cookies = plat["target_cookies"]
    required_cookies = plat["required_cookies"]

    _log(f"Platform: {plat['label']} ({base_url})")
    _log("Launching browser...")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir_path,
            channel="msedge",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        survey_url = f"{base_url}/index.html#/surveylist"
        _log(f"Navigating to {survey_url}")
        page.goto(survey_url, wait_until="domcontentloaded")
        _log("Waiting for login cookies...")
        _log("(If you see the login page, please log in manually.)")

        start_time = time.time()
        while time.time() - start_time < timeout:
            cookies = context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies if c["name"] in target_cookies}
            if required_cookies.issubset(cookie_dict.keys()):
                _log("Detected required cookies, saving...")
                save_cookies(platform, cookie_dict)
                context.close()
                return True
            time.sleep(2)
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0 and elapsed > 0:
                _log(f"Still waiting... ({elapsed}s / {timeout}s)")

        _log(f"Timeout after {timeout}s.")
        context.close()
        return False


def ensure_auth(session, platform, reload_session_fn):
    """
    确保认证有效。若无效则自动刷新 Cookie 并重载 session。
    reload_session_fn: 刷新后调用以重建 session 的回调函数
    返回 True=认证可用
    """
    if check_auth(session, platform):
        return True
    _log("Auth invalid, attempting auto-refresh...")
    success = refresh_cookie(platform)
    if success:
        reload_session_fn()
        return check_auth(session, platform)
    return False
