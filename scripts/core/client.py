# -*- coding: utf-8 -*-
"""HTTP session 工厂"""
import requests
from .constants import PLATFORMS


def _make_headers(base_url):
    return {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "origin": base_url,
        "referer": f"{base_url}/index.html",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
        ),
    }


def make_session(platform, cookies=None):
    """
    创建配置好的 requests.Session，挂载 Cookie 和 headers。
    若 cookies 未传入，自动从 config.json 加载。
    """
    if cookies is None:
        from .auth import load_cookies
        cookies = load_cookies(platform)
    plat = PLATFORMS[platform]
    base_url = plat["base_url"]
    cookie_domain = plat["cookie_domain"]
    session = requests.Session()
    session.headers.update(_make_headers(base_url))
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=cookie_domain)
    return session
