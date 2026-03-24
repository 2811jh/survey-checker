#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网易问卷质量检查工具
从 survey-game.163.com 获取问卷完整内容（题目、选项、逻辑），供 AI 分析检查。

使用方式:
  # 检查认证状态（失败时自动刷新 Cookie）
  python survey_checker.py check

  # 按名称搜索问卷
  python survey_checker.py search --name "回流玩家"

  # 按 ID 抓取问卷完整内容
  python survey_checker.py fetch --id 91044

  # 按名称抓取（自动搜索 + 抓取）
  python survey_checker.py fetch --name "回流玩家"
"""

import argparse
import json
import os
import re
import sys
import time
import requests
from datetime import datetime


# ─── 常量配置 ────────────────────────────────────────────────────────────────

BASE_URL = "https://survey-game.163.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
PROFILE_DIR = os.path.join(SCRIPT_DIR, ".browser_profile")

# API 端点
API_SURVEY_LIST = "/view/survey/list"
API_QUESTION_LIST = "/view/survey_stat/get_question_list"
API_QUESTION_DETAIL = "/view/question/list"
API_SURVEY_DETAIL = "/view/survey/detail"
API_SURVEY_SAVE = "/view/survey/save"
API_SURVEY_LOCK = "/view/survey/set_lock"
API_SURVEY_COPY = "/view/template/survey/quote"

# 需要提取的 Cookie 名称
TARGET_COOKIES = {"SURVEY_TOKEN", "JSESSIONID", "P_INFO"}

DEFAULT_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "origin": BASE_URL,
    "referer": f"{BASE_URL}/index.html",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
    ),
}


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def _log(msg):
    """输出日志到 stderr（不影响 stdout 的 JSON 输出）"""
    print(f"[survey_checker] {msg}", file=sys.stderr, flush=True)


def _json_output(data):
    """统一 JSON 输出到 stdout"""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _strip_html(text):
    """去除 HTML 标签，返回纯文本"""
    return re.sub(r'<[^>]+>', '', text or '').strip()


def _gen_id(prefix="q"):
    """生成唯一 ID，格式与问卷系统一致：q-xxxxx 或 a-xxxxx"""
    import random
    return f"{prefix}-{random.randint(10**16, 10**17 - 1)}"


# ─── Cookie 自动刷新 ─────────────────────────────────────────────────────────

def refresh_cookie(timeout=300):
    """
    自动刷新 Cookie（与 survey_download 相同机制）。
    1. 打开浏览器访问问卷系统
    2. 如果已有登录态（.browser_profile），自动获取 Cookie
    3. 如果没有，等待用户手动登录
    4. 检测到 SURVEY_TOKEN 后保存到 config.json

    返回: True=成功, False=失败
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("ERROR: Playwright not installed.")
        _log("  pip install playwright")
        _log("  playwright install chromium")
        return False

    _log("Launching browser...")
    with sync_playwright() as p:
        # 使用持久化上下文，保留登录 session
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel="msedge",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else context.new_page()
        survey_url = f"{BASE_URL}/index.html#/surveylist"
        _log(f"Navigating to {survey_url}")
        page.goto(survey_url, wait_until="domcontentloaded")

        _log("Waiting for login cookies...")
        _log("(If you see the login page, please log in manually. The script will auto-detect.)")

        start_time = time.time()
        while time.time() - start_time < timeout:
            cookies = context.cookies()
            cookie_dict = {}
            for c in cookies:
                if c["name"] in TARGET_COOKIES:
                    cookie_dict[c["name"]] = c["value"]

            if "SURVEY_TOKEN" in cookie_dict and "JSESSIONID" in cookie_dict:
                _log("Detected cookies, verifying...")
                try:
                    resp = page.evaluate("""async () => {
                        const r = await fetch('/view/survey/list', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                            body: JSON.stringify({pageNo:1,surveyName:"",status:"-1",deliveryRange:-1,type:-1,groupId:-1,groupUser:-1,gameName:""})
                        });
                        return await r.json();
                    }""")
                    if resp.get("resultCode") == 100:
                        _log("Cookies verified successfully!")
                        config = {
                            "cookies": cookie_dict,
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        }
                        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False, indent=2)
                        _log(f"Cookies saved to {CONFIG_FILE}")
                        context.close()
                        return True
                    else:
                        _log("Cookie detected but verification failed, waiting...")
                except Exception:
                    pass

            time.sleep(2)
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0 and elapsed > 0:
                _log(f"Still waiting... ({elapsed}s / {timeout}s)")

        _log(f"Timeout after {timeout}s. Failed to detect valid cookies.")
        context.close()
        return False


# ─── 核心类 ──────────────────────────────────────────────────────────────────

class SurveyChecker:
    """网易问卷内容抓取器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._load_config()

    # ── Cookie 管理 ──────────────────────────────────────────────────────

    def _load_config(self):
        """从 config.json 加载 Cookie"""
        if not os.path.exists(CONFIG_FILE):
            return False
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        for name, value in config.get("cookies", {}).items():
            self.session.cookies.set(name, value, domain="survey-game.163.com")
        return True

    def _auto_refresh_cookie(self):
        """自动刷新 Cookie，刷新后重新加载"""
        _log("Attempting auto-refresh cookie...")
        success = refresh_cookie(timeout=300)
        if success:
            self._load_config()
        return success

    def _ensure_auth(self):
        """确保认证有效，失败时自动刷新。返回 True=认证可用"""
        if self.check_auth():
            return True
        _log("Auth invalid, attempting auto-refresh...")
        if self._auto_refresh_cookie():
            return self.check_auth()
        return False

    # ── 认证检查 ─────────────────────────────────────────────────────────

    def check_auth(self):
        """检查 Cookie 是否有效"""
        try:
            resp = self.session.post(
                f"{BASE_URL}{API_SURVEY_LIST}",
                json={
                    "pageNo": 1, "surveyName": "", "status": "-1",
                    "deliveryRange": -1, "type": -1, "groupId": -1,
                    "groupUser": -1, "gameName": "",
                },
            )
            data = resp.json()
            return data.get("resultCode") == 100
        except Exception as e:
            _log(f"Auth check failed: {e}")
            return False

    # ── 问卷搜索 ─────────────────────────────────────────────────────────

    def search_surveys(self, name="", page=1):
        """按名称搜索问卷列表"""
        resp = self.session.post(
            f"{BASE_URL}{API_SURVEY_LIST}",
            json={
                "pageNo": page,
                "surveyName": name,
                "status": "-1",
                "deliveryRange": -1,
                "type": -1,
                "groupId": -1,
                "groupUser": -1,
                "gameName": "",
            },
        )
        data = resp.json()
        if data.get("resultCode") != 100:
            return {"status": "error", "message": data.get("resultDesc", "Unknown error")}

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

    # ── 获取问卷题目列表（统计分析接口）──────────────────────────────────

    def get_question_list(self, survey_id):
        """获取问卷的题目列表（统计分析接口，含题型信息）"""
        resp = self.session.post(
            f"{BASE_URL}{API_QUESTION_LIST}",
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

    # ── 获取完整问卷数据（用于修改和保存）─────────────────────────────

    def get_survey_full(self, survey_id):
        """获取问卷的完整数据（用于修改后 save 回去）"""
        resp = self.session.get(
            f"{BASE_URL}{API_SURVEY_DETAIL}",
            params={"id": survey_id},
        )
        data = resp.json()
        if data.get("resultCode") != 100:
            _log(f"get_survey_full failed: {data.get('resultDesc')}")
            return None
        return data.get("data")

    def lock_survey(self, survey_id):
        """锁定问卷（编辑前需要）"""
        request_id = str(int(time.time() * 1000))
        resp = self.session.get(
            f"{BASE_URL}{API_SURVEY_LOCK}",
            params={"surveyId": survey_id, "requestId": request_id},
        )
        data = resp.json()
        return data.get("resultCode") == 100

    def save_survey(self, survey_data):
        """保存整个问卷数据"""
        resp = self.session.post(
            f"{BASE_URL}{API_SURVEY_SAVE}",
            json=survey_data,
        )
        data = resp.json()
        if data.get("resultCode") != 100:
            _log(f"save_survey failed: {data.get('resultDesc')}")
            return {"status": "error", "message": data.get("resultDesc", "保存失败")}
        return {"status": "success", "message": "保存成功"}

    # ── 复制问卷 ────────────────────────────────────────────────────────

    def copy_survey(self, source_id, new_name=None):
        """
        复制一份问卷。
        source_id: 源问卷 ID
        new_name: 新问卷名称（可选，默认在原名称后加"-副本"）
        返回: {"status":"success", "new_id": 新问卷ID, "new_name": 新名称}
        """
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效，自动刷新失败。"}

        # 1. 获取源问卷的基本信息
        _log(f"Fetching source survey {source_id} info...")
        source_data = self.get_survey_full(source_id)
        if not source_data:
            return {"status": "error", "message": f"获取源问卷 {source_id} 失败"}

        source_name = source_data.get("surveyName", f"问卷{source_id}")
        game_name = source_data.get("gameName", "")
        survey_type = source_data.get("type", 0)
        delivery_range = source_data.get("deliveryRange", 0)
        lang = source_data.get("lang", "简体中文")
        default_lang = source_data.get("defaultLang")
        group_id = source_data.get("groupId", -1)
        group_list = source_data.get("groupList", [])
        remark = source_data.get("remark", "")
        direct_area = source_data.get("directArea", 0)
        custom_url_type = source_data.get("customUrlType", 0)
        custom_url = source_data.get("customUrl", "")
        survey_extra = source_data.get("surveyExtraJsonStruct", {"surveyCheckUser": {"uid": ""}})

        if new_name is None:
            new_name = f"{source_name}-副本"

        _log(f"Copying '{source_name}' → '{new_name}'...")

        # 2. 调用复制接口
        payload = {
            "id": source_id,
            "surveyName": new_name,
            "type": survey_type,
            "deliveryRange": delivery_range,
            "customUrlType": custom_url_type,
            "customUrl": custom_url,
            "lang": lang,
            "defaultLang": default_lang,
            "groupId": group_id,
            "groupList": group_list,
            "remark": remark,
            "gameName": game_name,
            "directArea": direct_area,
            "surveyExtraJsonStruct": survey_extra,
        }

        resp = self.session.post(
            f"{BASE_URL}{API_SURVEY_COPY}",
            json=payload,
        )
        data = resp.json()

        if data.get("resultCode") != 100:
            return {
                "status": "error",
                "message": f"复制失败: {data.get('resultDesc', '未知错误')}",
            }

        # 3. 从响应中提取新问卷 ID
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
        return {
            "status": "success",
            "message": f"复制成功",
            "source_id": source_id,
            "source_name": source_name,
            "new_id": new_id,
            "new_name": new_name,
            "edit_url": f"{BASE_URL}/index.html#/edit/{new_id}" if new_id else None,
        }

    # ── 解析题目文件 → JSON ──────────────────────────────────────────────

    @staticmethod
    def parse_question_file(filepath):
        """
        解析问卷题目文本文件，返回 add_questions 所需的 JSON 列表。
        支持格式：数字[题型]标题，后续行为选项/提示文案/评分等。
        示例：
            6[量表题]您对这款游戏的满意度如何？
            [提示文案]非常不满意//一般//非常满意
            [评分]5星
        """
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        raw_questions = []
        current = None
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"^(\d+)\[(.+?)\](.+)$", line)
            if m:
                if current:
                    raw_questions.append(current)
                qtype_cn = m.group(2)
                type_map = {
                    "量表题": "star", "矩形量表题": "rect-star",
                    "矩形单选题": "rect-radio", "矩形多选题": "rect-checkbox",
                    "多选题": "checkbox", "单选题": "radio",
                    "填空题": "blank", "多项填空题": "multiple-text",
                    "分页符": "paging", "描述说明": "describe",
                    "隐含问题": "imply",
                }
                current = {
                    "type": type_map.get(qtype_cn, "radio"),
                    "title": m.group(3).strip(),
                    "_num": int(m.group(1)),
                    "_lines": [],
                }
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    if not next_line:
                        i += 1
                        continue
                    if re.match(r"^\d+\[", next_line):
                        break
                    current["_lines"].append(next_line)
                    i += 1
                continue
            i += 1

        if current:
            raw_questions.append(current)

        # 转换为 spec 列表
        result = []
        exclusive_keywords = [
            "以上都没", "以上均没", "都没有", "都不是", "我没有不满意",
            "我认为", "我没在", "只玩", "我没遇到", "没遇到",
            "以上都不", "都不需要",
        ]

        for q in raw_questions:
            spec = {"type": q["type"], "title": q["title"]}
            extra = q["_lines"]

            if q["type"] == "paging":
                result.append(spec)
                continue

            if q["type"] == "imply":
                # 隐含题：解析变量类型和变量名称
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
                    if "10" in score_line:
                        # NPS 题：0-10分，标记为 nps
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
                    is_mutex = any(kw in ol for kw in exclusive_keywords)
                    if ol == "其他" or ol.startswith("其他游戏"):
                        opts.append({"text": ol, "hasOther": 1, "noRandom": 1})
                    elif is_mutex:
                        opts.append({"text": ol, "mutex": 1, "noRandom": 1})
                    else:
                        opts.append(ol)
                spec["options"] = opts
                if len(opts) >= 8:
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

            result.append(spec)

        return result

    # ── 新增题目 ────────────────────────────────────────────────────────

    def _find_template(self, questions, qtype):
        """在现有题目中找到同类型模板，深拷贝作为新题目的基础"""
        import copy as copy_mod
        for q in questions:
            if q.get("type") == qtype:
                return copy_mod.deepcopy(q)
        return None

    def _build_question_from_spec(self, spec, existing_questions):
        """
        根据用户的简化描述构建一个完整的 question 对象。
        spec 格式（参照 SurveyKit）:
        {
            "type": "radio",
            "title": "题目标题",
            "options": ["选项A", "选项B", {"text":"其他","hasOther":1}],
            "required": 1,
            "random": 0,
            "layout": 0,
            "insert": {"afterLabel": "Q10"} 或 {"afterTitle": "满意度评价"} 或 {"index": 5},
            "startDesc": "...", "middleDesc": "...", "endDesc": "...",  # star 题型
            "subQuestions": [{"title":"行1"}, {"title":"行2"}],  # 矩阵/多项填空
            "placeholder": "请输入",  # blank 题型
            "maxRow": 2,
            "logic_rules": [...]  # 可选，随题目一起配置
        }
        """
        qtype = spec.get("type", "radio")

        # 优先找同类型模板深拷贝，找不到就用最小骨架
        template = self._find_template(existing_questions, qtype)

        if template:
            q = template
        else:
            # 最小骨架（参照 Survey_Question_Type_Mapping.md）
            q = {
                "type": qtype,
                "title": "",
                "description": None,
                "index": "0",
                "required": 1,
                "hidden": 0,
                "random": 0,
                "randomColumn": 0,
                "maxRow": 1,
                "maxLength": -1,
                "maxShowLength": -1,
                "minLength": -1,
                "layout": 0 if qtype in ("star", "rect-star", "paging") else 1,
                "displayForm": 0,
                "levels": None if qtype in ("star",) else ["", "选项描述"],
                "groups": None if qtype in ("star",) else [],
                "logic": [],
                "tag": "",
                "referType": 0,
                "questionLang": "",
                "mark": 0,
                "zoom": 1,
            }

        # 生成新的唯一 ID
        q["id"] = _gen_id("q")

        # 设置标题
        q["title"] = spec.get("title", q.get("title", ""))

        # 设置通用字段
        for field in ["required", "random", "layout", "maxRow", "maxLength",
                       "placeholder", "hidden", "randomColumn", "displayForm"]:
            if field in spec:
                q[field] = spec[field]

        # 量表题专属字段
        for field in ["startDesc", "middleDesc", "endDesc"]:
            if field in spec:
                q[field] = spec[field]

        # 量表/矩阵量表题必须设置评分范围
        if qtype in ("star", "rect-star"):
            is_nps = spec.get("_is_nps", False)
            if is_nps:
                # NPS 推荐题：0-10分
                q["nps"] = 1
                q["starType"] = 1
                q["star"] = 0
                q["starEnd"] = 10
                q["openScore"] = 1
                q["score"] = None
            else:
                # 普通满意度题：1-5星
                q["starType"] = q.get("starType") or 1
                q["star"] = q.get("star") or 1
                q["starEnd"] = q.get("starEnd") or 5
                q["openScore"] = 1
                q["score"] = 10

        # 处理选项（radio/checkbox/qselect/sort/star）
        if "options" in spec:
            new_options = []
            for opt in spec["options"]:
                if isinstance(opt, str):
                    # 简写：纯文本选项
                    new_options.append({
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
                    })
                elif isinstance(opt, dict):
                    # 完整对象：支持 hasOther, mutex, noRandom 等
                    opt_obj = {
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
                    new_options.append(opt_obj)
            q["options"] = new_options

        # 处理子题目（rect-star/rect-radio/rect-checkbox/multiple-text）
        if "subQuestions" in spec:
            new_subs = []
            # 根据题型决定子题目的 type
            sub_type_map = {
                "rect-star": "star",
                "rect-radio": "radio",
                "rect-checkbox": "checkbox",
                "multiple-text": "blank",
            }
            sub_type = sub_type_map.get(qtype, None)

            for sub in spec["subQuestions"]:
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
                new_subs.append(sub_obj)
            q["subQuestions"] = new_subs

        # paging / describe 不需要 options
        if qtype in ("paging", "describe", "blank", "multiple-text"):
            if "options" not in spec:
                q["options"] = [] if qtype == "paging" else None

        return q

    def _resolve_insert_position(self, spec, questions, label_map):
        """解析插入位置，返回数组索引"""
        insert = spec.get("insert", {})

        # 按题号标签定位：afterLabel="Q10"
        if "afterLabel" in insert:
            label = insert["afterLabel"]
            if label in label_map:
                return label_map[label] + 1
            else:
                _log(f"WARNING: label '{label}' not found, appending to end")
                return len(questions)

        # 按题目标题定位：afterTitle="满意度评价"
        if "afterTitle" in insert:
            target_title = insert["afterTitle"]
            for i, q in enumerate(questions):
                if target_title in _strip_html(q.get("title", "")):
                    return i + 1
            _log(f"WARNING: title '{target_title}' not found, appending to end")
            return len(questions)

        # 按数组索引定位
        if "index" in insert:
            return min(insert["index"], len(questions))

        # 默认追加到末尾
        return len(questions)

    def add_questions(self, survey_id, question_specs):
        """
        向问卷中新增题目。
        survey_id: 问卷 ID
        question_specs: 题目描述列表，每个元素是一个 spec dict
        返回新增题目的信息
        """
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}

        _log(f"Adding {len(question_specs)} questions to survey {survey_id}...")

        # 1. 获取当前完整数据
        survey_data = self.get_survey_full(survey_id)
        if not survey_data:
            return {"status": "error", "message": "获取问卷数据失败"}

        questions = survey_data.get("questions", [])
        label_map = self._build_label_map(questions)
        added = []

        # 2. 按顺序构建并插入题目
        insertions = []  # [(index, original_order, question_obj, spec)]
        for order, spec in enumerate(question_specs):
            q_obj = self._build_question_from_spec(spec, questions)
            pos = self._resolve_insert_position(spec, questions, label_map)
            insertions.append((pos, order, q_obj, spec))

        # 按位置从大到小排序；同一位置的按 order 从大到小（最后的先插入，后续的插入同一位置会推到前面，自然恢复正序）
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

        # 3. 锁定并保存
        lock_ok = self.lock_survey(survey_id)
        if not lock_ok:
            return {
                "status": "error",
                "message": "锁定失败！请关闭浏览器编辑器后重试。",
                "added": added,
            }

        save_result = self.save_survey(survey_data)
        if save_result["status"] != "success":
            return {"status": "error", "message": save_result["message"], "added": added}

        # 4. 验证
        _log("Verifying (waiting 3s)...")
        time.sleep(3)
        verify_data = self.get_survey_full(survey_id)
        if verify_data:
            new_count = len(verify_data.get("questions", []))
            orig_count = new_count - len(added)
            _log(f"Questions: {orig_count} → {new_count} (+{len(added)})")

        # 5. 如果有 logic_rules，在题目添加后配置逻辑
        all_logic_rules = []
        for spec in question_specs:
            if "logic_rules" in spec:
                all_logic_rules.extend(spec["logic_rules"])
        
        logic_result = None
        if all_logic_rules and verify_data:
            _log(f"Configuring {len(all_logic_rules)} logic rules...")
            logic_result = self.set_logic_rules(survey_id, all_logic_rules)

        result = {
            "status": "success",
            "message": f"成功新增 {len(added)} 道题目",
            "added": added,
        }
        if logic_result:
            result["logic_result"] = logic_result
        return result

    # ── 逻辑规则设置 ────────────────────────────────────────────────────

    def set_logic_rules(self, survey_id, logic_rules):
        """
        为问卷设置显示/跳转逻辑。
        logic_rules 格式（与 SurveyKit 一致）:
        [
            {
                "sourceQuestionTitle": "来源题标题",  # 或 "sourceLabel": "Q1"
                "selectedOptionTexts": ["选项A", "选项B"],
                "goToQuestionTitle": "目标题标题",  # 或 "goToLabel": "Q5"
            }
        ]
        逻辑含义：当来源题选中了指定选项时，显示目标题。
        """
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}

        _log(f"Setting {len(logic_rules)} logic rules for survey {survey_id}...")

        # 获取最新数据
        survey_data = self.get_survey_full(survey_id)
        if not survey_data:
            return {"status": "error", "message": "获取问卷数据失败"}

        questions = survey_data.get("questions", [])
        label_map = self._build_label_map(questions)

        # 建立标题→索引映射
        title_map = {}
        for i, q in enumerate(questions):
            t = _strip_html(q.get("title", ""))
            if t:
                title_map[t] = i

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
                    # 精确匹配
                    if src_title in title_map:
                        src_idx = title_map[src_title]
                    else:
                        # 模糊匹配
                        for t, idx in title_map.items():
                            if src_title in t:
                                src_idx = idx
                                break

                if src_idx is None:
                    errors.append(f"来源题未找到: {rule.get('sourceLabel') or rule.get('sourceQuestionTitle')}")
                    continue

                src_q = questions[src_idx]
                src_type = src_q.get("type", "")

                # 仅支持 radio/checkbox/star 作为逻辑来源
                if src_type not in ("radio", "checkbox", "star"):
                    errors.append(f"来源题类型 {src_type} 不支持逻辑设置")
                    continue

                # 2. 定位目标题
                tgt_idx = None
                if "goToLabel" in rule:
                    tgt_idx = label_map.get(rule["goToLabel"])
                elif "goToQuestionTitle" in rule:
                    tgt_title = rule["goToQuestionTitle"]
                    if tgt_title in title_map:
                        tgt_idx = title_map[tgt_title]
                    else:
                        for t, idx in title_map.items():
                            if tgt_title in t:
                                tgt_idx = idx
                                break

                if tgt_idx is None:
                    errors.append(f"目标题未找到: {rule.get('goToLabel') or rule.get('goToQuestionTitle')}")
                    continue

                tgt_q = questions[tgt_idx]

                # 不支持 paging/imply/describe 作为目标
                if tgt_q.get("type") in ("paging", "imply", "describe"):
                    errors.append(f"目标题类型 {tgt_q.get('type')} 不支持作为逻辑目标")
                    continue

                # 仅支持向后跳
                if tgt_idx <= src_idx:
                    errors.append(f"仅支持向后跳转，来源 idx={src_idx} → 目标 idx={tgt_idx}")
                    continue

                # 3. 匹配选项 ID
                selected_texts = rule.get("selectedOptionTexts", [])
                option_ids = []
                src_options = src_q.get("options", []) or []

                for sel_text in selected_texts:
                    found = False
                    for opt in src_options:
                        opt_text = _strip_html(opt.get("text", ""))
                        if sel_text == opt_text or sel_text in opt_text:
                            option_ids.append(opt["id"])
                            found = True
                            break
                    if not found:
                        # 对于 star 题型，选项文本是数字
                        for opt in src_options:
                            if str(sel_text) == _strip_html(opt.get("text", "")):
                                option_ids.append(opt["id"])
                                found = True
                                break
                    if not found:
                        errors.append(f"选项 '{sel_text}' 在来源题中未找到")

                if not option_ids:
                    continue

                # 4. 写入 logic 字段
                # 逻辑存储在来源题的 logic 中
                src_logic = src_q.get("logic", [])
                if not isinstance(src_logic, list):
                    src_logic = []

                # 查找是否已有指向目标题的规则
                existing_rule = None
                for lr in src_logic:
                    if tgt_q["id"] in (lr.get("questions") or []):
                        existing_rule = lr
                        break

                if existing_rule:
                    # 合并选项
                    existing_opts = set(existing_rule.get("options", []))
                    existing_opts.update(option_ids)
                    existing_rule["options"] = list(existing_opts)
                else:
                    # 新增规则
                    new_rule = {
                        "options": option_ids,
                        "questions": [tgt_q["id"]],
                        "subQuestions": [],
                        "controlSubQuestions": "{}",
                    }
                    src_logic.append(new_rule)

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

        # 5. 保存
        survey_data["questions"] = questions
        lock_ok = self.lock_survey(survey_id)
        if not lock_ok:
            return {"status": "error", "message": "锁定失败，请关闭编辑器", "applied": applied, "errors": errors}

        save_result = self.save_survey(survey_data)

        _log("Verifying logic (waiting 3s)...")
        time.sleep(3)

        return {
            "status": save_result["status"],
            "message": f"成功设置 {len(applied)} 条逻辑规则",
            "applied": applied,
            "errors": errors if errors else None,
        }

    # ── 修改问卷题目设置 ─────────────────────────────────────────────────

    def modify_questions(self, survey_id, modifications):
        """
        修改问卷中的题目设置。
        
        参数:
            survey_id: 问卷 ID
            modifications: 修改列表，每个元素是一个 dict:
                {
                    "question_label": "Q6",           # 题号标签
                    "question_id": "q-xxx",            # 或者直接用题目 ID
                    "changes": {
                        "required": 0,                 # 修改必填设置 (0/1)
                        "random": 1,                   # 选项全部随机 (0/1)
                        "option_mutex": [               # 设置选项互斥
                            {"text": "我没有不满意的地方", "mutex": 1},
                            {"text": "其他", "noRandom": 1},
                        ],
                        "title": "新的题目标题",        # 修改题目标题
                    }
                }
        
        返回:
            修改结果（包含变更日志）
        """
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}

        # 1. 获取完整问卷数据
        _log(f"Fetching full survey data for ID: {survey_id}")
        survey_data = self.get_survey_full(survey_id)
        if not survey_data:
            return {"status": "error", "message": "无法获取问卷数据"}

        questions = survey_data.get("questions", [])
        if not questions:
            return {"status": "error", "message": "问卷中没有题目"}

        # 2. 构建 label→index 映射
        label_map = self._build_label_map(questions)

        # 3. 应用修改
        change_log = []
        for mod in modifications:
            q_label = mod.get("question_label")
            q_id = mod.get("question_id")
            changes = mod.get("changes", {})

            # 定位题目
            target_idx = None
            if q_label and q_label in label_map:
                target_idx = label_map[q_label]
            elif q_id:
                for idx, q in enumerate(questions):
                    if q.get("id") == q_id:
                        target_idx = idx
                        break

            if target_idx is None:
                change_log.append({
                    "question": q_label or q_id,
                    "status": "skipped",
                    "reason": "题目未找到",
                })
                continue

            q = questions[target_idx]
            q_title = _strip_html(q.get("title", ""))[:40]
            applied = []

            # ── 修改 required ────────────────────────────────────────
            if "required" in changes:
                old_val = q.get("required")
                new_val = changes["required"]
                q["required"] = new_val
                applied.append(f"required: {old_val} → {new_val}")

            # ── 修改 random (选项全部随机) ────────────────────────────
            if "random" in changes:
                old_val = q.get("random")
                new_val = changes["random"]
                q["random"] = new_val
                applied.append(f"random: {old_val} → {new_val}")

            # ── 修改 title ───────────────────────────────────────────
            if "title" in changes:
                old_val = _strip_html(q.get("title", ""))[:30]
                q["title"] = changes["title"]
                applied.append(f"title: '{old_val}...' → '{changes['title'][:30]}...'")

            # ── 修改选项级属性 (mutex / noRandom / hasOther) ─────────
            if "option_mutex" in changes:
                for opt_mod in changes["option_mutex"]:
                    opt_text = opt_mod.get("text", "")
                    for opt in (q.get("options") or []):
                        opt_clean = _strip_html(opt.get("text", ""))
                        if opt_text and opt_text in opt_clean:
                            for field in ["mutex", "noRandom", "hasOther"]:
                                if field in opt_mod:
                                    old_v = opt.get(field, 0)
                                    opt[field] = opt_mod[field]
                                    applied.append(
                                        f"option '{opt_text[:15]}' {field}: {old_v} → {opt_mod[field]}"
                                    )
                            break

            # ── 修改选项级属性（通过 option_changes 更灵活）───────────
            if "option_changes" in changes:
                for opt_mod in changes["option_changes"]:
                    opt_index = opt_mod.get("index")  # 按序号
                    opt_text = opt_mod.get("text")    # 按文本匹配
                    
                    target_opt = None
                    if opt_index is not None and 0 <= opt_index < len(q.get("options") or []):
                        target_opt = q["options"][opt_index]
                    elif opt_text:
                        for opt in (q.get("options") or []):
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

            # ── 修改选项文本（按序号精确修改）────────────────────────────
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

            # ── 添加/修改/清除逻辑设置 (显示逻辑 / 题目关联) ────────────
            # logic 格式: 数组，每个元素 = {options:[选项ID], questions:[题目ID], subQuestions:[], controlSubQuestions:"{}"}
            # 逻辑含义: 当本题的 options 中任意选项被选中时，显示 questions 中的题目
            #
            # changes 中使用 logic_rules（按题号/选项文本引用，脚本自动转换为 ID）:
            #   "logic_rules": [
            #     {
            #       "when_options": ["选项文本1", "选项文本2"],  # 当这些选项被选中
            #       "show_questions": ["Q7", "Q8"],              # 显示这些题目
            #       "show_sub_questions": []                      # 可选：显示的矩阵子题目
            #     }
            #   ]
            # 也可以直接设置 "logic": [...] 用原始 ID 格式
            # 设置 "logic_rules": [] 或 "logic": [] 表示清除所有逻辑
            if "logic" in changes:
                old_count = len(q.get("logic") or [])
                q["logic"] = changes["logic"]
                new_count = len(changes["logic"])
                applied.append(f"logic: {old_count} rules → {new_count} rules (raw)")

            if "logic_rules" in changes:
                # 将用户友好的 label/text 格式转为 API 需要的 ID 格式
                new_logic = []
                for rule in changes["logic_rules"]:
                    # 解析选项 → ID
                    opt_ids = []
                    for opt_ref in rule.get("when_options", []):
                        for opt in (q.get("options") or []):
                            if opt_ref in _strip_html(opt.get("text", "")):
                                opt_ids.append(opt["id"])
                                break

                    # 解析题目 → ID
                    q_ids = []
                    for q_ref in rule.get("show_questions", []):
                        if q_ref in label_map:
                            ref_q = questions[label_map[q_ref]]
                            q_ids.append(ref_q["id"])
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

            # ── 添加/删除选项 ────────────────────────────────────────────
            if "add_options" in changes:
                if q.get("options") is None:
                    q["options"] = []
                for new_opt in changes["add_options"]:
                    opt_id = f"a-{int(time.time()*1000)}{len(q['options'])}"
                    q["options"].append({
                        "id": opt_id,
                        "text": new_opt.get("text", ""),
                        "mutex": new_opt.get("mutex", 0),
                        "noRandom": new_opt.get("noRandom", 0),
                        "hasOther": new_opt.get("hasOther", 0),
                        "hidden": 0,
                    })
                    applied.append(f"add option: '{new_opt.get('text','')[:20]}'")

            if "remove_options" in changes:
                for rem in changes["remove_options"]:
                    opts = q.get("options") or []
                    for i, opt in enumerate(opts):
                        if rem in _strip_html(opt.get("text", "")):
                            removed_text = _strip_html(opt["text"])[:20]
                            opts.pop(i)
                            applied.append(f"remove option: '{removed_text}'")
                            break

            # ── 修改子问题标题（R7 异常标点修复）─────────────────────────
            if "sub_title_fixes" in changes:
                sub_qs = q.get("subQuestions") or []
                for fix in changes["sub_title_fixes"]:
                    sub_id = fix.get("sub_id")
                    new_title = fix.get("new_title", "")
                    old_title = fix.get("old_title", "")
                    for sub in sub_qs:
                        if sub.get("id") == sub_id:
                            sub["title"] = new_title
                            applied.append(f"sub_title: '{old_title[:20]}' → '{new_title[:20]}'")
                            break

            # ── 修改 description（题目描述/补充说明）─────────────────────
            if "description" in changes:
                old_desc = q.get("description") or ""
                q["description"] = changes["description"]
                applied.append(f"description: '{old_desc[:20]}' → '{str(changes['description'])[:20]}'")

            # ── 修改 random / layout / randomColumn / noRandom / maxLength 等其他字段 ──
            for field in ["random", "layout", "randomColumn", "noRandom", "maxLength", "minLength",
                          "maxRow", "validate", "starType", "level",
                          "maxShowLength", "fixFirstLine", "displace"]:
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

        # 4. 检查是否有实际修改
        actual_changes = [c for c in change_log if c["status"] == "modified"]
        if not actual_changes:
            return {
                "status": "no_change",
                "message": "没有实际修改",
                "change_log": change_log,
            }

        # 5. 锁定问卷（必须成功，否则 save 会被静默忽略）
        _log(f"Locking survey {survey_id}...")
        lock_ok = self.lock_survey(survey_id)
        if not lock_ok:
            return {
                "status": "error",
                "message": "锁定问卷失败！请先关闭浏览器中的问卷编辑器页面，然后重试。"
                           "（问卷被浏览器编辑器锁定时，API 保存会被静默忽略。）",
                "modifications_applied": 0,
                "change_log": change_log,
            }

        # 6. 保存
        _log(f"Saving {len(actual_changes)} modifications...")
        save_result = self.save_survey(survey_data)

        if save_result["status"] != "success":
            return {
                "status": "error",
                "message": save_result["message"],
                "modifications_applied": 0,
                "change_log": change_log,
            }

        # 7. 保存后验证 — 等待后重新获取数据，确认修改是否真正生效
        _log("Verifying modifications (waiting 3s to bypass cache)...")
        time.sleep(3)
        verified_data = self.get_survey_full(survey_id)
        verification_failures = []

        if verified_data:
            verified_qs = verified_data.get("questions", [])
            verified_label_map = self._build_label_map(verified_qs)

            for mod in modifications:
                q_label = mod.get("question_label")
                q_id = mod.get("question_id")
                changes = mod.get("changes", {})

                # 定位已保存的题目
                v_idx = None
                if q_label and q_label in verified_label_map:
                    v_idx = verified_label_map[q_label]
                elif q_id:
                    for idx, vq in enumerate(verified_qs):
                        if vq.get("id") == q_id:
                            v_idx = idx
                            break

                if v_idx is None:
                    continue

                vq = verified_qs[v_idx]

                # 检查 required 是否生效
                if "required" in changes and vq.get("required") != changes["required"]:
                    verification_failures.append(
                        f"{q_label or q_id}: required expected {changes['required']}, got {vq.get('required')}"
                    )

                # 检查 title 是否生效
                if "title" in changes and _strip_html(vq.get("title", "")) != _strip_html(changes["title"]):
                    verification_failures.append(
                        f"{q_label or q_id}: title not updated"
                    )

                # 检查选项互斥/noRandom 是否生效
                if "option_mutex" in changes:
                    for opt_mod in changes["option_mutex"]:
                        opt_text = opt_mod.get("text", "")
                        for vopt in (vq.get("options") or []):
                            if opt_text and opt_text in _strip_html(vopt.get("text", "")):
                                for field in ["mutex", "noRandom", "hasOther"]:
                                    if field in opt_mod and vopt.get(field) != opt_mod[field]:
                                        verification_failures.append(
                                            f"{q_label or q_id}: option '{opt_text}' {field} expected {opt_mod[field]}, got {vopt.get(field)}"
                                        )
                                break

        if verification_failures:
            _log(f"VERIFICATION FAILED: {len(verification_failures)} issues detected!")
            for vf in verification_failures:
                _log(f"  - {vf}")

            # 重试一次：重新获取最新数据，重新修改，重新保存
            _log("Retrying: Re-fetching fresh data and re-applying modifications...")
            retry_data = self.get_survey_full(survey_id)
            if retry_data:
                retry_qs = retry_data.get("questions", [])
                retry_label_map = self._build_label_map(retry_qs)

                for mod in modifications:
                    q_label = mod.get("question_label")
                    q_id = mod.get("question_id")
                    changes = mod.get("changes", {})

                    r_idx = None
                    if q_label and q_label in retry_label_map:
                        r_idx = retry_label_map[q_label]
                    elif q_id:
                        for idx, rq in enumerate(retry_qs):
                            if rq.get("id") == q_id:
                                r_idx = idx
                                break
                    if r_idx is None:
                        continue

                    rq = retry_qs[r_idx]
                    if "required" in changes:
                        rq["required"] = changes["required"]
                    if "title" in changes:
                        rq["title"] = changes["title"]
                    if "option_mutex" in changes:
                        for opt_mod in changes["option_mutex"]:
                            opt_text = opt_mod.get("text", "")
                            for opt in (rq.get("options") or []):
                                if opt_text and opt_text in _strip_html(opt.get("text", "")):
                                    for field in ["mutex", "noRandom", "hasOther"]:
                                        if field in opt_mod:
                                            opt[field] = opt_mod[field]
                                    break

                self.lock_survey(survey_id)
                time.sleep(1)
                retry_save = self.save_survey(retry_data)

                # 二次验证
                if retry_save["status"] == "success":
                    _log("Retry save returned success. Verifying again...")
                    final_data = self.get_survey_full(survey_id)
                    if final_data:
                        final_qs = final_data.get("questions", [])
                        final_label_map = self._build_label_map(final_qs)
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
                                "message": f"保存后验证失败（重试后仍然不生效）。可能原因：浏览器编辑器正在打开此问卷。请关闭编辑器后重试。",
                                "verification_failures": still_failed,
                                "modifications_applied": 0,
                                "change_log": change_log,
                            }
                        else:
                            _log("Retry verification passed!")
                            return {
                                "status": "success",
                                "message": "保存成功（重试后验证通过）",
                                "modifications_applied": len(actual_changes),
                                "change_log": change_log,
                            }

            return {
                "status": "error",
                "message": f"保存后验证失败。请确认浏览器未打开该问卷的编辑器。",
                "verification_failures": verification_failures,
                "modifications_applied": 0,
                "change_log": change_log,
            }

        _log("Verification passed! All modifications confirmed.")

        # 8. 解锁（再次调用 lock 会自动续期/解锁）
        self.lock_survey(survey_id)

        return {
            "status": "success",
            "message": "保存成功（已验证生效）",
            "modifications_applied": len(actual_changes),
            "change_log": change_log,
        }

    def _build_label_map(self, questions):
        """构建 Q1/Y1/T1 → 数组 index 的映射"""
        label_map = {}
        prefix_counters = {"Q": 0, "Y": 0, "T": 0}
        STR_PREFIX = {
            "imply": "Y", "describe": "T", "paging": "T",
            "option-merge": "T", "question-merge": "T",
        }
        for idx, q in enumerate(questions):
            q_type = q.get("type", "")
            prefix = STR_PREFIX.get(q_type, "Q")
            prefix_counters[prefix] = prefix_counters.get(prefix, 0) + 1
            label = f"{prefix}{prefix_counters[prefix]}"
            label_map[label] = idx
        return label_map

    # ── 获取问卷题目详情（编辑接口，含选项文本 + 逻辑设置）─────────────

    def get_question_detail(self, survey_id):
        """获取问卷的完整题目详情（含选项文本、跳转逻辑等）"""
        resp = self.session.get(
            f"{BASE_URL}{API_QUESTION_DETAIL}",
            params={"surveyId": survey_id, "from": "dataclean"},
        )
        data = resp.json()
        if data.get("resultCode") != 100:
            _log(f"get_question_detail failed: {data.get('resultDesc')}")
            return None
        return data.get("dataList") or data.get("data") or []

    # ── calibrate (问卷校准): 按固定规则自动扫描并修复 ─────────────────────

    # 排他性选项关键词 — 用于 R3 规则判断
    EXCLUSIVE_KEYWORDS = [
        "以上都没", "以上均没", "都没有", "都不是", "没有以上", "以上皆无",
        "我没有", "我没在", "只玩", "我认为", "没遇到", "没有不满意",
        "以上都不", "以上均不", "都不需要", "都不想", "以上皆不",
    ]

    # "其他"选项关键词 — 用于 R2 规则判断 noRandom
    OTHER_KEYWORDS = ["其他"]

    # 异常标点符号 — 用于 R7 规则（子问题标题、选项文本末尾的奇怪标点）
    ABNORMAL_TRAILING_PUNCT = [
        "：", ":", "；", ";", "，", ",", "、",
    ]

    def calibrate(self, survey_id, dry_run=False):
        """
        问卷校准：按 R1-R7 固定规则扫描问卷，自动生成修复方案并执行。
        dry_run=True 时仅输出方案不修改。
        """
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效，自动刷新失败。"}

        _log(f"Calibrate scanning survey {survey_id}...")
        data = self.get_survey_full(survey_id)
        if not data:
            return {"status": "error", "message": "获取问卷数据失败"}

        qs = data.get("questions", [])
        label_map = self._build_label_map(qs)
        issues = []       # 发现的问题列表
        modifications = []  # 自动修复 JSON

        for label, idx in sorted(label_map.items(), key=lambda x: x[1]):
            if not label.startswith("Q"):
                continue
            q = qs[idx]
            qtype = q.get("type", "")
            opts = q.get("options") or []
            title_text = _strip_html(q.get("title", ""))[:60]
            changes = {}
            option_mods = []

            # ── R1: 多选题选项>=8 → layout=2, >=20 → layout=3 ────────
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

            # ── R2: 多选题 random=1 + 其他/互斥项 noRandom=1 ─────────
            if qtype == "checkbox":
                if q.get("random", 0) != 1:
                    issues.append({
                        "rule": "R2", "question": label,
                        "desc": f"random={q.get('random',0)} → 应改为1",
                        "title": title_text,
                    })
                    changes["random"] = 1

                for o in opts:
                    otxt = _strip_html(o.get("text", ""))
                    # 需要固定位置（noRandom=1）的选项：hasOther / mutex / 文本为"其他"
                    is_special = (
                        o.get("hasOther") == 1
                        or o.get("mutex") == 1
                        or any(kw == otxt.strip() for kw in self.OTHER_KEYWORDS)
                    )
                    if is_special and o.get("noRandom", 0) != 1:
                        issues.append({
                            "rule": "R2", "question": label,
                            "desc": f"选项'{otxt[:20]}' noRandom=0 → 应为1（应固定位置不参与随机）",
                            "title": title_text,
                        })
                        option_mods.append({"text": otxt[:30], "noRandom": 1})

            # ── R3: 排他性选项必须 mutex=1 ────────────────────────────
            if qtype == "checkbox":
                for o in opts:
                    otxt = _strip_html(o.get("text", ""))
                    if any(kw in otxt for kw in self.EXCLUSIVE_KEYWORDS):
                        if o.get("mutex", 0) != 1:
                            issues.append({
                                "rule": "R3", "question": label,
                                "desc": f"'{otxt[:20]}' 应为互斥 mutex=1",
                                "title": title_text,
                            })
                            option_mods.append({"text": otxt[:30], "mutex": 1, "noRandom": 1})

            # ── R4: 文本题非必填 ──────────────────────────────────────
            if qtype == "blank" and q.get("required", 0) == 1:
                issues.append({
                    "rule": "R4", "question": label,
                    "desc": f"文本题 required=1 → 应改为0",
                    "title": title_text,
                })
                changes["required"] = 0

            # ── R6: 必填一致性检查 ───────────────────────────────────
            # - 题干含"非必填" → required 必须为 0
            # - 非文本题且题干不含"非必填" → required 必须为 1
            NON_QUESTION_TYPES = ("describe", "paging", "imply")
            title_full = _strip_html(q.get("title", ""))
            has_non_required_hint = "非必填" in title_full

            if qtype not in NON_QUESTION_TYPES and qtype != "blank":
                # R6 只处理非文本题（文本题由 R4 处理）
                if has_non_required_hint and q.get("required", 0) != 0:
                    # 题干写了"非必填"但实际设为必填
                    issues.append({
                        "rule": "R6", "question": label,
                        "desc": "题干标注「非必填」但 required=1 → 应改为0",
                        "title": title_text,
                    })
                    changes["required"] = 0
                elif not has_non_required_hint and q.get("required", 0) != 1:
                    # 无"非必填"标注的非文本题 → 必须必填
                    issues.append({
                        "rule": "R6", "question": label,
                        "desc": f"非文本题 required=0 → 应改为1",
                        "title": title_text,
                    })
                    changes["required"] = 1

            # ── R7: 异常标点符号检查（子问题标题末尾） ─────────────────
            sub_qs = q.get("subQuestions") or []
            for sub in sub_qs:
                sub_title = _strip_html(sub.get("title", ""))
                if sub_title:
                    for punct in self.ABNORMAL_TRAILING_PUNCT:
                        if sub_title.endswith(punct):
                            issues.append({
                                "rule": "R7", "question": label,
                                "desc": f"子问题'{sub_title[:25]}' 末尾含异常标点「{punct}」→ 应去除",
                                "title": title_text,
                            })
                            # 自动去除末尾异常标点
                            cleaned = sub_title.rstrip("".join(self.ABNORMAL_TRAILING_PUNCT)).strip()
                            if cleaned != sub_title:
                                if "sub_title_fixes" not in changes:
                                    changes["sub_title_fixes"] = []
                                changes["sub_title_fixes"].append({
                                    "sub_id": sub.get("id"),
                                    "old_title": sub_title,
                                    "new_title": cleaned,
                                })
                            break  # 每个子题目只报一次

            # 汇总本题修改
            if changes or option_mods:
                mod = {"question_label": label, "changes": changes}
                if option_mods:
                    mod["changes"]["option_mutex"] = option_mods
                modifications.append(mod)

        # R5 逻辑关系 — 仅检测不自动修复（需要人工确认逻辑条件）
        # 注意：逻辑可能存储在父题（评分题）的 logic 字段中，而非追问题自身
        r5_warnings = []
        # 建立 question id → label 映射
        id_to_label = {}
        for lbl, i in label_map.items():
            qid = qs[i].get("id")
            if qid:
                id_to_label[qid] = lbl

        for label, idx in sorted(label_map.items(), key=lambda x: x[1]):
            if not label.startswith("Q"):
                continue
            q = qs[idx]
            title_text = _strip_html(q.get("title", ""))
            qtype = q.get("type", "")
            # 找满意度评分题后面的追问题
            if qtype in ("star", "rect-star", "nps") and ("满意" in title_text):
                # 检查该评分题的 logic 是否已指向后续追问题
                parent_logic = q.get("logic") or []
                parent_logic_targets = set()
                for rule in parent_logic:
                    for target_qid in (rule.get("questions") or []):
                        parent_logic_targets.add(target_qid)

                for offset in range(1, 4):
                    next_idx = idx + offset
                    if next_idx >= len(qs):
                        break
                    next_q = qs[next_idx]
                    next_title = _strip_html(next_q.get("title", ""))
                    next_type = next_q.get("type", "")
                    if next_type in ("paging", "describe", "imply"):
                        continue
                    if ("不满意" in next_title or "不太满意" in next_title or "一般" in next_title):
                        next_qid = next_q.get("id")
                        # 检查：追问题自身有 logic，或者父题的 logic 已指向追问题
                        has_own_logic = bool(next_q.get("logic"))
                        has_parent_logic = next_qid in parent_logic_targets
                        if not has_own_logic and not has_parent_logic:
                            next_label = None
                            for nl, ni in label_map.items():
                                if ni == next_idx:
                                    next_label = nl
                                    break
                            r5_warnings.append({
                                "rule": "R5", "question": next_label or f"idx{next_idx}",
                                "desc": f"追问题缺少显示逻辑（可能应受 {label} 评分控制）",
                                "title": next_title[:50],
                                "auto_fixable": False,
                            })

        # 汇总结果
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
        _log(f"Calibrate: fixing {len(modifications)} issues...")
        fix_result = self.modify_questions(survey_id, modifications)
        result["fix_result"] = fix_result
        result["message"] = (
            f"扫描发现 {len(all_issues)} 个问题，"
            f"已自动修复 {fix_result.get('modifications_applied', 0)} 项"
        )
        result["status"] = fix_result.get("status", "error")
        return result

    # 保留 autofix 为别名，向后兼容
    def autofix(self, survey_id, dry_run=False):
        """autofix 的别名，已更名为 calibrate（问卷校准）"""
        return self.calibrate(survey_id, dry_run=dry_run)

    # ── 抓取完整问卷 ─────────────────────────────────────────────────────

    def fetch_survey(self, survey_id=None, survey_name=None, select_index=None):
        """
        抓取指定问卷的完整内容。
        返回结构化数据，包含：
        - survey_info: 问卷基本信息（名称、ID、状态等）
        - questions: 完整题目列表（含题目文本、选项文本、题型、逻辑等）
        """
        # 1. 确保认证
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效，自动刷新失败。请检查网络或手动登录。"}

        # 2. 定位问卷
        target_id = survey_id
        target_name = survey_name or ""

        if not target_id and target_name:
            _log(f"Searching for survey: {target_name}")
            search_result = self.search_surveys(target_name)
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

        # 3. 获取问卷基本信息
        survey_info = {"id": target_id, "name": target_name}

        # 4. 获取题目列表（统计接口 — 含题型）
        stat_questions = self.get_question_list(target_id)
        if stat_questions is None:
            return {"status": "error", "message": f"无法获取问卷题目列表（ID: {target_id}）"}

        _log(f"Got {len(stat_questions)} questions from stat API")

        # 5. 获取题目详情（编辑接口 — 含选项文本、逻辑）
        detail_questions = self.get_question_detail(target_id)
        _log(f"Got detail data: {type(detail_questions)}")

        # 6. 合并数据，构建完整的题目列表
        questions = self._merge_question_data(stat_questions, detail_questions)

        # 统计各类题目数量
        q_count = sum(1 for q in questions if q.get("prefix") == "Q")
        y_count = sum(1 for q in questions if q.get("prefix") == "Y")
        t_count = sum(1 for q in questions if q.get("prefix") == "T")

        return {
            "status": "success",
            "survey_info": survey_info,
            "questions": questions,
            "total_items": len(questions),
            "question_count": q_count,       # 正式题目数（Q题）
            "hidden_count": y_count,         # 隐含题数（Y题）
            "description_count": t_count,    # 说明题数（T题）
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _merge_question_data(self, stat_questions, detail_data):
        """合并统计接口和详情接口的数据"""
        # 构建详情的 id→data 映射
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

        # ── 题型分类 ────────────────────────────────────────────────
        # 问卷系统中的题型编号规则：
        #   Y = 隐含题 (imply)         → 不算正式题目
        #   T = 说明题 (describe)       → 不算正式题目
        #   Q = 正式题目 (其他所有题型)  → 需要检查的题目
        #
        # type_code 为字符串时直接匹配，为数字时按映射转换

        # 字符串题型 → 中文名称 + 前缀类别
        STR_TYPE_MAP = {
            "imply":          ("隐含题",     "Y"),
            "describe":       ("说明题",     "T"),
            "paging":         ("分页符",     "T"),
            "radio":          ("单选题",     "Q"),
            "checkbox":       ("多选题",     "Q"),
            "blank":          ("填空题",     "Q"),
            "multiple-text":  ("多项填空题", "Q"),
            "star":           ("星级评分题", "Q"),
            "rect-star":      ("矩阵星级题", "Q"),
            "rect-radio":     ("矩阵单选题", "Q"),
            "rect-checkbox":  ("矩阵多选题", "Q"),
            "nps":            ("NPS题",      "Q"),
            "rect-nps":       ("矩阵NPS题",  "Q"),
            "scale":          ("量表题",     "Q"),
            "sort":           ("排序题",     "Q"),
            "dropdown":       ("下拉选择题", "Q"),
            "cascade":        ("关联选择题", "Q"),
            "language":       ("语言选择题", "Q"),
            "date":           ("日期选择题", "Q"),
            "city":           ("城市选择题", "Q"),
            "file":           ("文件上传题", "Q"),
            "option-merge":   ("选项合并",   "T"),
            "question-merge": ("多题合并",   "T"),
        }
        # 数字题型映射（兼容旧格式）
        NUM_TYPE_MAP = {
            1: ("单选题", "Q"), 2: ("多选题", "Q"), 3: ("填空题", "Q"),
            4: ("矩阵单选题", "Q"), 5: ("矩阵多选题", "Q"), 6: ("排序题", "Q"),
            7: ("量表题", "Q"), 8: ("NPS题", "Q"), 9: ("下拉选择题", "Q"),
            10: ("日期选择题", "Q"), 11: ("文件上传题", "Q"),
        }

        # ── 分类编号计数器 ──────────────────────────────────────────
        prefix_counters = {"Q": 0, "Y": 0, "T": 0}

        merged = []
        for _raw_idx, sq in enumerate(stat_questions):
            qid = sq.get("id") or sq.get("questionId")
            q_type_code = sq.get("type") or sq.get("questionType", 0)

            # 确定题型名称和前缀
            if isinstance(q_type_code, str):
                type_name, prefix = STR_TYPE_MAP.get(q_type_code, (f"未知({q_type_code})", "Q"))
            else:
                type_name, prefix = NUM_TYPE_MAP.get(q_type_code, (f"未知({q_type_code})", "Q"))

            prefix_counters[prefix] = prefix_counters.get(prefix, 0) + 1
            label = f"{prefix}{prefix_counters[prefix]}"

            # 详情接口数据（含选项完整属性、逻辑设置等，是权威数据源）
            detail = detail_map.get(qid, {})

            # required 优先从详情接口取（比统计接口更准确）
            required_val = detail.get("required") if detail.get("required") is not None else sq.get("required", 0)

            question = {
                "label": label,               # Q1, Y1, T1 等
                "prefix": prefix,             # Q / Y / T
                "index": prefix_counters[prefix],
                "id": qid,
                "title": _strip_html(sq.get("title") or sq.get("questionTitle", "")),
                "type_code": q_type_code,
                "type": type_name,
                "required": required_val,      # 0=非必填, 1=必填（以详情接口为准）
                "options": [],
                "logic": None,
                "sub_questions": [],
            }

            # ── 选项：完整提取属性（含互斥、其他项等）─────────────────
            options = detail.get("options") or sq.get("options") or []
            for opt in options:
                opt_text = _strip_html(opt.get("text") or opt.get("optionText", ""))
                if opt_text:
                    question["options"].append({
                        "id": opt.get("id"),
                        "text": opt_text,
                        "mutex": opt.get("mutex", 0),        # 1=互斥选项
                        "hasOther": opt.get("hasOther", 0),   # 1=带"其他"填空
                        "hidden": opt.get("hidden", 0),       # 1=隐藏选项
                        "noRandom": opt.get("noRandom", 0),   # 1=不参与随机排序
                    })

            # ── 逻辑设置 ─────────────────────────────────────────────
            logic = detail.get("logic") or detail.get("jumpLogic") or detail.get("displayLogic")
            if logic:
                question["logic"] = logic

            # ── 子题目（矩阵题等）────────────────────────────────────
            sub_questions = detail.get("subQuestions") or sq.get("subQuestions") or []
            for sub in sub_questions:
                question["sub_questions"].append({
                    "id": sub.get("id"),
                    "title": _strip_html(sub.get("title") or sub.get("subTitle", "")),
                })

            # ── 其他题目级属性 ────────────────────────────────────────
            if detail.get("description"):
                question["description"] = _strip_html(detail["description"])
            if detail.get("random"):
                question["random"] = detail["random"]  # 选项随机

            merged.append(question)

        return merged


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="网易问卷质量检查工具 — 获取问卷内容",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── check: 检查认证 ─────────────────────────────────────────────────
    subparsers.add_parser("check", help="检查认证是否有效（失败时自动刷新）")

    # ── search: 搜索问卷 ────────────────────────────────────────────────
    search_p = subparsers.add_parser("search", help="按名称搜索问卷")
    search_p.add_argument("--name", required=True, help="问卷名称（支持模糊搜索）")
    search_p.add_argument("--page", type=int, default=1, help="页码（默认 1）")

    # ── fetch: 抓取问卷内容 ─────────────────────────────────────────────
    fetch_p = subparsers.add_parser("fetch", help="抓取问卷完整内容（题目+选项+逻辑）")
    fetch_p.add_argument("--id", type=int, help="问卷 ID")
    fetch_p.add_argument("--name", help="问卷名称（模糊匹配）")
    fetch_p.add_argument("--select", type=int, help="多个匹配时的选择序号（从 0 开始）")

    # ── modify: 修改问卷题目设置 ────────────────────────────────────────
    modify_p = subparsers.add_parser("modify", help="修改问卷题目设置（通过JSON）")
    modify_p.add_argument("--id", type=int, required=True, help="问卷 ID")
    modify_p.add_argument("--json", required=True,
                          help='修改内容 JSON 字符串或文件路径（以 @ 开头表示文件）')

    # ── calibrate: 问卷校准（按固定规则自动扫描并修复）──────────────────
    calibrate_p = subparsers.add_parser("calibrate", help="问卷校准：按 R1-R7 固定规则自动扫描并修复问卷")
    calibrate_p.add_argument("--id", type=int, required=True, help="问卷 ID")
    calibrate_p.add_argument("--dry-run", action="store_true",
                             help="仅扫描输出修复方案，不执行修改")

    # autofix 保留为 calibrate 的别名（向后兼容）
    autofix_p = subparsers.add_parser("autofix", help="（已更名为 calibrate）问卷校准")
    autofix_p.add_argument("--id", type=int, required=True, help="问卷 ID")
    autofix_p.add_argument("--dry-run", action="store_true",
                           help="仅扫描输出修复方案，不执行修改")

    # ── copy: 复制问卷 ─────────────────────────────────────────────────
    copy_p = subparsers.add_parser("copy", help="复制问卷")
    copy_p.add_argument("--id", type=int, required=True, help="源问卷 ID")
    copy_p.add_argument("--name", type=str, default=None,
                        help="新问卷名称（默认：原名称-副本）")

    # ── add: 新增题目 ─────────────────────────────────────────────────
    add_p = subparsers.add_parser("add", help="向问卷新增题目")
    add_p.add_argument("--id", type=int, required=True, help="问卷 ID")
    add_p.add_argument("--json", required=True,
                       help="题目描述 JSON 字符串或文件路径（以 @ 开头表示文件）")

    # ── logic: 设置逻辑规则 ───────────────────────────────────────────
    logic_p = subparsers.add_parser("logic", help="设置问卷题目间的逻辑规则")
    logic_p.add_argument("--id", type=int, required=True, help="问卷 ID")
    logic_p.add_argument("--json", required=True,
                         help="逻辑规则 JSON 字符串或文件路径（以 @ 开头表示文件）")

    # ── import: 从文本文件解析并录入题目 ──────────────────────────────
    import_p = subparsers.add_parser("import", help="从文本文件解析题目并录入问卷")
    import_p.add_argument("--id", type=int, required=True, help="问卷 ID")
    import_p.add_argument("--file", required=True, help="题目文本文件路径")
    import_p.add_argument("--dry-run", action="store_true",
                          help="仅解析输出 JSON，不录入问卷")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    checker = SurveyChecker()

    if args.command == "check":
        if checker.check_auth():
            _json_output({"status": "success", "message": "认证有效 ✓"})
        else:
            _log("Auth invalid, attempting auto-refresh...")
            if checker._auto_refresh_cookie() and checker.check_auth():
                _json_output({"status": "success", "message": "认证已自动刷新 ✓"})
            else:
                _json_output({"status": "error", "message": "认证无效，自动刷新失败。"})

    elif args.command == "search":
        if not checker._ensure_auth():
            _json_output({"status": "error", "message": "认证无效，自动刷新失败。"})
            return
        result = checker.search_surveys(args.name, args.page)
        _json_output(result)

    elif args.command == "fetch":
        result = checker.fetch_survey(
            survey_id=args.id,
            survey_name=args.name,
            select_index=args.select,
        )
        _json_output(result)

    elif args.command == "modify":
        # 解析修改内容
        json_str = args.json
        if json_str.startswith("@"):
            filepath = json_str[1:]
            with open(filepath, "r", encoding="utf-8") as f:
                modifications = json.load(f)
        else:
            modifications = json.loads(json_str)

        if not isinstance(modifications, list):
            modifications = [modifications]

        result = checker.modify_questions(args.id, modifications)
        _json_output(result)

    elif args.command == "calibrate":
        result = checker.calibrate(args.id, dry_run=args.dry_run)
        _json_output(result)

    elif args.command == "autofix":
        result = checker.calibrate(args.id, dry_run=args.dry_run)
        _json_output(result)

    elif args.command == "copy":
        result = checker.copy_survey(args.id, new_name=args.name)
        _json_output(result)

    elif args.command == "add":
        json_str = args.json
        if json_str.startswith("@"):
            with open(json_str[1:], "r", encoding="utf-8") as f:
                specs = json.load(f)
        else:
            specs = json.loads(json_str)
        if not isinstance(specs, list):
            specs = [specs]
        result = checker.add_questions(args.id, specs)
        _json_output(result)

    elif args.command == "logic":
        json_str = args.json
        if json_str.startswith("@"):
            with open(json_str[1:], "r", encoding="utf-8") as f:
                rules = json.load(f)
        else:
            rules = json.loads(json_str)
        if not isinstance(rules, list):
            rules = [rules]
        result = checker.set_logic_rules(args.id, rules)
        _json_output(result)

    elif args.command == "import":
        _log(f"Parsing file: {args.file}")
        specs = SurveyChecker.parse_question_file(args.file)
        _log(f"Parsed {len(specs)} questions")
        if args.dry_run:
            _json_output({
                "status": "parsed",
                "count": len(specs),
                "questions": [
                    {
                        "type": s.get("type"),
                        "title": _strip_html(s.get("title", ""))[:60],
                        "options": len(s.get("options", []) or s.get("subQuestions", []) or []),
                        "required": s.get("required"),
                    }
                    for s in specs
                ],
            })
        else:
            result = checker.add_questions(args.id, specs)
            _json_output(result)


if __name__ == "__main__":
    main()
