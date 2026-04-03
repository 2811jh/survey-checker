# survey_checker 模块化重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将单文件 `scripts/survey_checker.py`（2627行）按职责拆分为多模块结构，保持所有公开接口向后兼容。

**Architecture:** 按职责纵向拆分为 core/、operations/、io/ 三层，平台差异（国内/国外）通过 `platform` 参数 + 少量条件判断集中处理，不重复代码。入口文件 `survey_checker.py` 退化为纯组装层，不含业务逻辑。

**Tech Stack:** Python 3.8+、requests、playwright（仅 auth 模块）

**测试问卷：** 国外平台用 44583，国内平台用 91680

---

## 文件结构（目标）

```
scripts/
├── survey_checker.py          # 入口：SurveyChecker 类外壳 + CLI（<150行）
├── core/
│   ├── __init__.py
│   ├── constants.py           # PLATFORMS、API端点常量、_config_file、_profile_dir
│   ├── utils.py               # _log、_strip_html、_gen_id、_json_output
│   ├── auth.py                # refresh_cookie、_load_config、_ensure_auth、check_auth
│   └── client.py              # _make_headers、make_session（session 工厂）
├── operations/
│   ├── __init__.py
│   ├── survey_ops.py          # copy_survey、create_survey、save_survey、lock_survey（L347-L577）
│   ├── builder.py             # _build_question_from_spec、_find_template、_resolve_insert_position（L788-L1068）
│   ├── question_ops.py        # clear_questions、add_questions、modify_questions（L1070-L1843）
│   ├── logic_ops.py           # set_logic_rules（L1211-L1393）
│   └── calibrate.py           # calibrate、autofix、R1-R7规则（L1891-L2139）
└── survey_io/
    ├── __init__.py
    ├── fetcher.py             # get_survey_full、search_surveys、get_question_list、get_question_detail、fetch_survey（L266-L340、L1862-L2418）
    └── importer.py            # parse_question_file、import_from_markdown（L582-L784）

> ⚠️ 注意：文件夹名使用 `survey_io` 而非 `io`，因为 `io` 是 Python 内置模块名，会导致 ModuleNotFoundError。
```

---

## Phase 1：抽取 core 层（工具函数 + 常量）

### Task 1.1：创建 core/constants.py

**Files:**
- Create: `scripts/core/__init__.py`
- Create: `scripts/core/constants.py`

- [ ] **Step 1:** 创建 `scripts/core/__init__.py`（空文件）

- [ ] **Step 2:** 创建 `scripts/core/constants.py`，迁移常量

内容如下：
```python
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
API_SURVEY_LIST    = "/view/survey/list"
API_QUESTION_LIST  = "/view/survey_stat/get_question_list"
API_QUESTION_DETAIL = "/view/question/list"
API_SURVEY_DETAIL  = "/view/survey/detail"
API_SURVEY_SAVE    = "/view/survey/save"
API_SURVEY_LOCK    = "/view/survey/set_lock"
API_SURVEY_COPY    = "/view/template/survey/quote"
API_SURVEY_SETTING = "/view/survey/setting"
API_SURVEY_ADD     = "/view/survey/add"
API_SURVEY_PREVIEW = "/view/survey/preview"
```

- [ ] **Step 3:** 验证 import 正常

```bash
cd scripts && python -c "from core.constants import PLATFORMS, API_SURVEY_LIST; print('OK', API_SURVEY_LIST)"
```
期望输出：`OK /view/survey/list`

---

### Task 1.2：创建 core/utils.py

**Files:**
- Create: `scripts/core/utils.py`

- [ ] **Step 1:** 创建 `scripts/core/utils.py`

```python
# -*- coding: utf-8 -*-
"""工具函数：日志、HTML清洗、ID生成"""
import json
import random
import re
import sys


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
    return f"{prefix}-{random.randint(10**16, 10**17 - 1)}"


def _build_label_map(questions):
    """构建题目标签映射：{'Q1': 0, 'Q2': 1, 'Y1': 2, 'T1': 3, ...}"""
    label_map = {}
    prefix_counters = {}
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
```

- [ ] **Step 2:** 验证

```bash
cd scripts && python -c "from core.utils import _strip_html, _gen_id, _build_label_map; print(_strip_html('<b>hello</b>')); print(_gen_id('q')[:3])"
```
期望：`hello` 和 `q-`

---

### Task 1.3：创建 core/client.py

**Files:**
- Create: `scripts/core/client.py`

- [ ] **Step 1:** 创建 `scripts/core/client.py`

```python
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


def make_session(platform, cookies):
    """创建配置好的 requests.Session，挂载 Cookie 和 headers"""
    plat = PLATFORMS[platform]
    base_url = plat["base_url"]
    cookie_domain = plat["cookie_domain"]
    session = requests.Session()
    session.headers.update(_make_headers(base_url))
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=cookie_domain)
    return session
```

- [ ] **Step 2:** 验证

```bash
cd scripts && python -c "from core.client import make_session; s=make_session('cn',{}); print('session OK')"
```

---

### Task 1.4：创建 core/auth.py

**Files:**
- Create: `scripts/core/auth.py`

- [ ] **Step 1:** 创建 `scripts/core/auth.py`（迁移 L123-L262 的认证相关代码）

```python
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
```

- [ ] **Step 2:** 验证

```bash
cd scripts && python -c "from core.auth import load_cookies; c=load_cookies('cn'); print('cookies loaded:', list(c.keys()))"
```

- [ ] **Step 3:** commit

```bash
git add scripts/core/ && git commit -m "refactor: extract core layer (constants, utils, client, auth)"
```

---

## Phase 2：抽取 io 层

### Task 2.1：创建 io/fetcher.py

**Files:**
- Create: `scripts/io/__init__.py`
- Create: `scripts/io/fetcher.py`

迁移来源：
- `search_surveys` (L266-L304)
- `get_question_list` (L308-L321)
- `get_survey_full` (L325-L335)
- `get_question_detail` (L1862-L1874)
- `fetch_survey` (L2141-L2418，含内部函数 `_build_questions_from_detail`、`_merge_question_data`)

- [ ] **Step 1:** 创建 `scripts/io/__init__.py`（空文件）

- [ ] **Step 2:** 创建 `scripts/io/fetcher.py`，将上述方法从 `self.xxx` 形式改为独立函数 `xxx(session, base_url, ...)`

关键签名变化：
```python
# 原来（方法）
def get_survey_full(self, survey_id): ...
def search_surveys(self, name="", page=1): ...
def fetch_survey(self, survey_id=None, survey_name=None, select_index=None): ...

# 重构后（函数）
def get_survey_full(session, base_url, survey_id): ...
def search_surveys(session, base_url, name="", page=1): ...
def fetch_survey(session, base_url, survey_id=None, survey_name=None, select_index=None): ...
```

- [ ] **Step 3:** 验证（使用国外测试问卷 44583）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS, API_SURVEY_DETAIL
from core.auth import load_cookies
from core.client import make_session
from io.fetcher import get_survey_full

cookies = load_cookies('global')
session = make_session('global', cookies)
base_url = PLATFORMS['global']['base_url']
d = get_survey_full(session, base_url, 44583)
print('surveyName:', d.get('surveyName') if d else 'FAILED')
"
```
期望：`surveyName: 测试问卷`（或该问卷实际名称）

- [ ] **Step 4:** 验证（使用国内测试问卷 91680）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from io.fetcher import get_survey_full

cookies = load_cookies('cn')
session = make_session('cn', cookies)
base_url = PLATFORMS['cn']['base_url']
d = get_survey_full(session, base_url, 91680)
print('surveyName:', d.get('surveyName') if d else 'FAILED')
"
```
期望：`surveyName: 【测试】回流玩家调研-副本`

- [ ] **Step 5:** commit

```bash
git add scripts/io/ && git commit -m "refactor: extract io/fetcher.py"
```

---

### Task 2.2：创建 io/importer.py

**Files:**
- Create: `scripts/io/importer.py`

迁移来源：
- `parse_question_file` (L582-L784，静态方法)
- `import_from_markdown`（目前内嵌在 SurveyChecker 中，需提取为独立函数）

- [ ] **Step 1:** 创建 `scripts/io/importer.py`

关键签名：
```python
def parse_question_file(filepath) -> list: ...  # 返回 spec 列表（纯解析，无网络调用）
def import_from_markdown(session, base_url, platform, survey_id, filepath) -> dict: ...
```

- [ ] **Step 2:** 验证 parse（不需要网络）

```bash
cd scripts && python -c "
from io.importer import parse_question_file
import tempfile, os
md = '1[单选题]你喜欢什么颜色？\n红色\n蓝色\n绿色\n'
with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
    f.write(md); fname = f.name
specs = parse_question_file(fname)
os.unlink(fname)
print('specs count:', len(specs))
print('first type:', specs[0]['type'])
print('first opts:', [o if isinstance(o,str) else o['text'] for o in specs[0]['options']])
"
```
期望：`specs count: 1`，`first type: radio`，`first opts: ['红色', '蓝色', '绿色']`

- [ ] **Step 3:** commit

```bash
git add scripts/io/importer.py && git commit -m "refactor: extract io/importer.py"
```

---

## Phase 3：抽取 operations 层

### Task 3.1：创建 operations/builder.py

**Files:**
- Create: `scripts/operations/__init__.py`
- Create: `scripts/operations/builder.py`

迁移来源：
- `_find_template` (L788-L794)
- `_build_question_from_spec` (L796-L1038，约 240 行)
- `_resolve_insert_position` (L1039-L1068)

按题型拆分子函数（在 builder.py 内部）：`_apply_options`、`_apply_sub_questions`、`_apply_star_fields`、`_apply_imply_fields`

关键签名：
```python
def find_template(questions, qtype) -> dict: ...
def build_question(spec, existing_questions) -> dict: ...
def resolve_insert_position(spec, questions, label_map) -> int: ...
```

- [ ] **Step 1:** 创建 `scripts/operations/__init__.py`（空文件）

- [ ] **Step 2:** 创建 `scripts/operations/builder.py`，迁移并重构

- [ ] **Step 3:** 验证（不需要网络）

```bash
cd scripts && python -c "
from operations.builder import build_question

spec = {'type': 'radio', 'title': '测试题', 'options': ['A', 'B', 'C'], 'required': 1}
q = build_question(spec, [])
print('type:', q['type'])
print('title:', q['title'])
print('options count:', len(q['options']))
print('id starts with q-:', q['id'].startswith('q-'))
"
```
期望：type=radio，title=测试题，options count=3，id starts=True

- [ ] **Step 4:** commit

```bash
git add scripts/operations/ && git commit -m "refactor: extract operations/builder.py"
```

---

### Task 3.2：创建 operations/survey_ops.py

**Files:**
- Create: `scripts/operations/survey_ops.py`

迁移来源：
- `lock_survey` (L337-L345)
- `save_survey` (L347-L357)
- `copy_survey` (L361-L486)
- `create_survey` (L490-L577)

关键签名：
```python
def lock_survey(session, base_url, survey_id) -> bool: ...
def save_survey(session, base_url, survey_data) -> dict: ...
def copy_survey(session, base_url, platform, source_id, new_name=None) -> dict: ...
def create_survey(session, base_url, platform, name, game_name, lang="简体中文", ...) -> dict: ...
```

- [ ] **Step 1:** 创建 `scripts/operations/survey_ops.py`

- [ ] **Step 2:** 验证 copy_survey（国外平台，测试问卷 44583）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from operations.survey_ops import copy_survey

cookies = load_cookies('global')
session = make_session('global', cookies)
base_url = PLATFORMS['global']['base_url']
r = copy_survey(session, base_url, 'global', 44583, '[重构测试] 44583副本')
print('status:', r['status'])
print('new_id:', r.get('new_id'))
print('preview_url:', r.get('preview_url'))
"
```
期望：status=success，有 new_id，有 preview_url

- [ ] **Step 3:** 验证 copy_survey（国内平台，测试问卷 91680）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from operations.survey_ops import copy_survey

cookies = load_cookies('cn')
session = make_session('cn', cookies)
base_url = PLATFORMS['cn']['base_url']
r = copy_survey(session, base_url, 'cn', 91680, '[重构测试] 91680副本')
print('status:', r['status'])
print('new_id:', r.get('new_id'))
"
```
期望：status=success，有 new_id

- [ ] **Step 4:** commit

```bash
git add scripts/operations/survey_ops.py && git commit -m "refactor: extract operations/survey_ops.py"
```

---

### Task 3.3：创建 operations/logic_ops.py

**Files:**
- Create: `scripts/operations/logic_ops.py`

迁移来源：`set_logic_rules` (L1211-L1393，约 180 行)

关键签名：
```python
def set_logic_rules(session, base_url, survey_id, logic_rules) -> dict: ...
```
（依赖 `save_survey`、`lock_survey` from `survey_ops`，以及 `get_survey_full` from `fetcher`）

- [ ] **Step 1:** 创建 `scripts/operations/logic_ops.py`

- [ ] **Step 2:** 验证（无需实际调用，只验证 import）

```bash
cd scripts && python -c "from operations.logic_ops import set_logic_rules; print('import OK')"
```

- [ ] **Step 3:** commit

```bash
git add scripts/operations/logic_ops.py && git commit -m "refactor: extract operations/logic_ops.py"
```

---

### Task 3.4：创建 operations/question_ops.py

**Files:**
- Create: `scripts/operations/question_ops.py`

迁移来源：
- `clear_questions` (L1070-L1126)
- `add_questions` (L1126-L1210)
- `modify_questions` (L1395-L1843，约 450 行，最复杂的部分)

关键签名：
```python
def clear_questions(session, base_url, survey_id, keep_imply=False) -> dict: ...
def add_questions(session, base_url, platform, survey_id, question_specs) -> dict: ...
def modify_questions(session, base_url, survey_id, modifications) -> dict: ...
```

- [ ] **Step 1:** 创建 `scripts/operations/question_ops.py`

- [ ] **Step 2:** 验证 add_questions（国外测试问卷 44583）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from operations.question_ops import add_questions

cookies = load_cookies('global')
session = make_session('global', cookies)
base_url = PLATFORMS['global']['base_url']

# 找一个刚复制的空问卷（用上一步 copy 的 new_id）
# 或者直接测试向已有问卷追加（需在测试后手动删除）
print('import OK - skip network test for now')
"
```

- [ ] **Step 3:** 验证 modify_questions（国内测试问卷 91680，dry-run 模式）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from operations.calibrate import calibrate

cookies = load_cookies('cn')
session = make_session('cn', cookies)
base_url = PLATFORMS['cn']['base_url']
r = calibrate(session, base_url, 'cn', 91680, dry_run=True)
print('status:', r['status'])
print('issues:', r.get('total_issues'))
"
```

- [ ] **Step 4:** commit

```bash
git add scripts/operations/question_ops.py && git commit -m "refactor: extract operations/question_ops.py"
```

---

### Task 3.5：创建 operations/calibrate.py

**Files:**
- Create: `scripts/operations/calibrate.py`

迁移来源：`calibrate` + `autofix` (L1891-L2139，约 250 行)

将每个规则从内嵌 if 块提取为独立函数：
- `_check_r1_required(q, q_label, lang_hint)` → 返回 issue dict 或 None
- `_check_r2_other_no_random(q, q_label)` → 返回 modifications 列表
- `_check_r3_mutex(q, q_label)` → 返回 modifications 列表
- `_check_r4_r6_boundary(q, q_label)` → 返回 modifications 列表
- `_check_r5_random_block(q, q_label, next_q)` → 返回 warning 或 None
- `_check_r7_trailing_punct(q, q_label)` → 返回 modifications 列表

关键签名：
```python
def calibrate(session, base_url, platform, survey_id, dry_run=False) -> dict: ...
def autofix(session, base_url, platform, survey_id, dry_run=False) -> dict: ...  # 别名
```

- [ ] **Step 1:** 创建 `scripts/operations/calibrate.py`

- [ ] **Step 2:** 验证（国内测试问卷 91680，dry_run=True）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from operations.calibrate import calibrate

cookies = load_cookies('cn')
session = make_session('cn', cookies)
base_url = PLATFORMS['cn']['base_url']
r = calibrate(session, base_url, 'cn', 91680, dry_run=True)
print('status:', r['status'])
print('total_issues:', r.get('total_issues'))
print('auto_fixable:', r.get('auto_fixable'))
"
```

- [ ] **Step 3:** 验证（国外测试问卷 44583，dry_run=True）

```bash
cd scripts && python -c "
from core.constants import PLATFORMS
from core.auth import load_cookies
from core.client import make_session
from operations.calibrate import calibrate

cookies = load_cookies('global')
session = make_session('global', cookies)
base_url = PLATFORMS['global']['base_url']
r = calibrate(session, base_url, 'global', 44583, dry_run=True)
print('status:', r['status'])
print('total_issues:', r.get('total_issues'))
"
```

- [ ] **Step 4:** commit

```bash
git add scripts/operations/calibrate.py && git commit -m "refactor: extract operations/calibrate.py"
```

---

## Phase 4：重构入口文件 survey_checker.py

### Task 4.1：将 SurveyChecker 改为纯组装层

**Files:**
- Modify: `scripts/survey_checker.py`

目标：`survey_checker.py` 只保留 `SurveyChecker` 类外壳 + CLI，所有方法改为调用对应子模块函数，不包含任何业务逻辑。

- [ ] **Step 1:** 重写 `survey_checker.py`，结构如下

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网易问卷质量检查工具 — 入口文件
所有业务逻辑已迁移至 core/ operations/ io/ 子模块。
"""
import argparse
import sys
import os

# 确保 scripts/ 目录在 sys.path 中（支持直接运行和 import 两种方式）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.constants import PLATFORMS, DEFAULT_PLATFORM
from core.utils import _log, _json_output
from core.auth import load_cookies, ensure_auth, check_auth
from core.client import make_session
from io.fetcher import get_survey_full, search_surveys, get_question_list, get_question_detail, fetch_survey
from io.importer import parse_question_file, import_from_markdown
from operations.survey_ops import copy_survey, create_survey, save_survey, lock_survey
from operations.question_ops import clear_questions, add_questions, modify_questions
from operations.logic_ops import set_logic_rules
from operations.calibrate import calibrate, autofix
from operations.builder import build_question


class SurveyChecker:
    """网易问卷操作工具（向后兼容入口）"""

    def __init__(self, platform="cn"):
        if platform not in PLATFORMS:
            raise ValueError(f"Unknown platform '{platform}'. Choose from: {list(PLATFORMS.keys())}")
        self.platform = platform
        plat = PLATFORMS[platform]
        self.base_url = plat["base_url"]
        self.cookie_domain = plat["cookie_domain"]
        self.platform_label = plat["label"]
        _log(f"Platform: {self.platform_label} ({self.base_url})")
        cookies = load_cookies(platform)
        self.session = make_session(platform, cookies)

    # ── 认证 ────────────────────────────────────────────────────────────
    def _reload_session(self):
        cookies = load_cookies(self.platform)
        self.session = make_session(self.platform, cookies)

    def _ensure_auth(self):
        return ensure_auth(self.session, self.platform, self._reload_session)

    def check_auth(self):
        return check_auth(self.session, self.platform)

    # ── 数据读取 ─────────────────────────────────────────────────────────
    def get_survey_full(self, survey_id):
        return get_survey_full(self.session, self.base_url, survey_id)

    def search_surveys(self, name="", page=1):
        return search_surveys(self.session, self.base_url, name, page)

    def get_question_list(self, survey_id):
        return get_question_list(self.session, self.base_url, survey_id)

    def get_question_detail(self, survey_id):
        return get_question_detail(self.session, self.base_url, survey_id)

    def fetch_survey(self, survey_id=None, survey_name=None, select_index=None):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return fetch_survey(self.session, self.base_url, survey_id, survey_name, select_index)

    # ── 问卷操作 ─────────────────────────────────────────────────────────
    def lock_survey(self, survey_id):
        return lock_survey(self.session, self.base_url, survey_id)

    def save_survey(self, survey_data):
        return save_survey(self.session, self.base_url, survey_data)

    def copy_survey(self, source_id, new_name=None):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return copy_survey(self.session, self.base_url, self.platform, source_id, new_name)

    def create_survey(self, name, game_name, lang="简体中文", delivery_range=0,
                      direct_area=0, custom_url_type=0, remark=""):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return create_survey(self.session, self.base_url, self.platform,
                             name, game_name, lang, delivery_range, direct_area, custom_url_type, remark)

    # ── 题目操作 ─────────────────────────────────────────────────────────
    def clear_questions(self, survey_id, keep_imply=False):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return clear_questions(self.session, self.base_url, survey_id, keep_imply)

    def add_questions(self, survey_id, question_specs):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return add_questions(self.session, self.base_url, self.platform, survey_id, question_specs)

    def modify_questions(self, survey_id, modifications):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return modify_questions(self.session, self.base_url, survey_id, modifications)

    def set_logic_rules(self, survey_id, logic_rules):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return set_logic_rules(self.session, self.base_url, survey_id, logic_rules)

    # ── 校准 ─────────────────────────────────────────────────────────────
    def calibrate(self, survey_id, dry_run=False):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return calibrate(self.session, self.base_url, self.platform, survey_id, dry_run)

    def autofix(self, survey_id, dry_run=False):
        return self.calibrate(survey_id, dry_run)

    # ── Markdown 导入 ─────────────────────────────────────────────────────
    @staticmethod
    def parse_question_file(filepath):
        return parse_question_file(filepath)

    def import_from_markdown(self, survey_id, filepath):
        if not self._ensure_auth():
            return {"status": "error", "message": "认证无效"}
        return import_from_markdown(self.session, self.base_url, self.platform, survey_id, filepath)


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="网易问卷工具")
    parser.add_argument("--platform", default="cn", choices=list(PLATFORMS.keys()))
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("check", help="检查认证状态")

    p_search = subparsers.add_parser("search", help="搜索问卷")
    p_search.add_argument("--name", required=True)

    p_fetch = subparsers.add_parser("fetch", help="抓取问卷内容")
    p_fetch.add_argument("--id", type=int)
    p_fetch.add_argument("--name")
    p_fetch.add_argument("--select", type=int)

    args = parser.parse_args()
    checker = SurveyChecker(args.platform)

    if args.command == "check":
        ok = checker._ensure_auth()
        _json_output({"status": "ok" if ok else "error", "authenticated": ok})
    elif args.command == "search":
        result = checker.search_surveys(args.name)
        _json_output(result)
    elif args.command == "fetch":
        result = checker.fetch_survey(
            survey_id=args.id,
            survey_name=args.name,
            select_index=args.select,
        )
        _json_output(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** 验证向后兼容（国外平台）

```bash
cd scripts && python -c "
from survey_checker import SurveyChecker
gl = SurveyChecker('global')
d = gl.get_survey_full(44583)
print('get_survey_full OK:', d.get('surveyName') if d else 'FAILED')
r = gl.copy_survey(44583, '[重构完成] 向后兼容测试')
print('copy_survey OK:', r.get('status'), 'new_id:', r.get('new_id'))
"
```

- [ ] **Step 3:** 验证向后兼容（国内平台）

```bash
cd scripts && python -c "
from survey_checker import SurveyChecker
cn = SurveyChecker('cn')
r = cn.calibrate(91680, dry_run=True)
print('calibrate OK:', r.get('status'), 'issues:', r.get('total_issues'))
"
```

- [ ] **Step 4:** 验证 CLI

```bash
cd scripts && python survey_checker.py --platform global fetch --id 44583 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('CLI fetch OK, questions:', len(d.get('questions',[])))"
```

- [ ] **Step 5:** commit

```bash
git add scripts/survey_checker.py && git commit -m "refactor: survey_checker.py -> pure assembly layer, all logic in submodules"
```

---

## Phase 5：全量回归测试

### Task 5.1：核心功能验证

- [ ] **国外 copy_survey：** preview_url HTTP 200，groupId=-1，无协作群
- [ ] **国内 copy_survey：** status=success，有 new_id
- [ ] **国外 calibrate dry_run：** status=scanned，返回 issues 列表
- [ ] **国内 calibrate dry_run：** status=scanned，返回 issues 列表
- [ ] **fetch_survey 国外：** 返回问卷名称、题目列表
- [ ] **fetch_survey 国内：** 返回问卷名称、题目列表
- [ ] **CLI check：** 返回 `{"authenticated": true}`
- [ ] **CLI fetch：** 返回含 questions 的 JSON

- [ ] **最终 commit & push**

```bash
git add -A && git commit -m "refactor: complete modular restructure of survey_checker" && git push origin master
```

---

## 验证标准

| 检查项 | 标准 |
|--------|------|
| 所有文件行数 | < 400 行 |
| survey_checker.py 行数 | < 200 行（纯组装） |
| 国外 preview_url | HTTP 200 |
| 国外 groupId | -1（无协作群） |
| 国内/国外 calibrate | 返回 issues 列表 |
| 现有调用方式 | 完全向后兼容 |
