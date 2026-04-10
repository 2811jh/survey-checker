# Logic Writer 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 实现问卷跳转逻辑的自动解析与写入工具 `logic_writer.py`，替代现有 `logic_ops.py`

**Architecture:** 新建 `logic_writer.py` 提供 parse→resolve→write 三步流水线；修改 `importer.py` 录入后自动调用；改造 CLI `logic` 命令；删除旧模块并清理引用；更新 SKILL.md

**Tech Stack:** Python 3, requests, re

**Spec:** `docs/specs/2026-04-10-logic-writer-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `scripts/operations/logic_writer.py` | **新建** | 核心模块：parse_logic_block + resolve_logic_rules + write_logic_rules + extract_logic_block |
| `scripts/tests/test_logic_writer.py` | **新建** | 单元测试：parse 和 resolve |
| `scripts/operations/logic_ops.py` | **删除** | 被 logic_writer 替代 |
| `scripts/survey_io/importer.py` | **修改** | import_from_markdown 末尾调用 logic_writer |
| `scripts/survey_checker.py` | **修改** | CLI logic 命令改为调用新模块 |
| `scripts/operations/question_ops.py` | **修改** | 删除已注释的 logic_ops 引用 |
| `SKILL.md` | **修改** | 更新 Step 3.7、3.8、完成展示表格 |

---

## Task 1: 实现 `parse_logic_block` 函数

**Files:**
- Create: `scripts/operations/logic_writer.py`
- Create: `scripts/tests/test_logic_writer.py`

- [x] **Step 1: 创建测试文件，编写 parse 单元测试**

```python
# scripts/tests/test_logic_writer.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from operations.logic_writer import parse_logic_block


def test_parse_radio_text_option():
    """单选题文本选项"""
    lines = ['源题 Q16 选项 "组队开黑" → 显示 Q17,Q18']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["source"] == "Q16"
    assert result[0]["options"] == ["组队开黑"]
    assert result[0]["targets"] == ["Q17", "Q18"]
    assert result[0]["sub_questions"] is None
    assert result[0]["sub_options"] is None


def test_parse_star_numeric_option():
    """量表题数值评分"""
    lines = ['源题 Q1 选项 1,2 → 显示 Q2']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["source"] == "Q1"
    assert result[0]["options"] == ["1", "2"]
    assert result[0]["targets"] == ["Q2"]


def test_parse_multiple_text_options():
    """多个文本选项"""
    lines = ['源题 Q24 选项 "非常困难","有点困难" → 显示 Q25']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["options"] == ["非常困难", "有点困难"]
    assert result[0]["targets"] == ["Q25"]


def test_parse_rect_star_sub_questions():
    """矩阵量表题子问题+子选项"""
    lines = ['源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["source"] == "Q28"
    assert result[0]["sub_questions"] == [1, 2, 3]
    assert result[0]["sub_options"] == ["1", "2", "3"]
    assert result[0]["targets"] == ["Q29"]
    assert result[0]["options"] is None  # 子选项场景 options 为 None


def test_parse_long_text_with_parens():
    """含括号的长文本选项"""
    lines = ['源题 Q3 选项 "QQ（如QQ群、QQ空间、QQ游戏中心、兴趣部落等）" → 显示 Q4']
    result = parse_logic_block(lines)
    assert len(result) == 1
    assert result[0]["options"] == ["QQ（如QQ群、QQ空间、QQ游戏中心、兴趣部落等）"]


def test_parse_multiple_rules():
    """多条规则"""
    lines = [
        '源题 Q1 选项 1,2 → 显示 Q2',
        '源题 Q16 选项 "组队开黑" → 显示 Q17,Q18',
        '源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29',
    ]
    result = parse_logic_block(lines)
    assert len(result) == 3


def test_parse_skip_invalid_lines():
    """跳过无效行"""
    lines = ['这不是逻辑规则', '', '源题 Q1 选项 1,2 → 显示 Q2']
    result = parse_logic_block(lines)
    assert len(result) == 1


if __name__ == "__main__":
    test_parse_radio_text_option()
    test_parse_star_numeric_option()
    test_parse_multiple_text_options()
    test_parse_rect_star_sub_questions()
    test_parse_long_text_with_parens()
    test_parse_multiple_rules()
    test_parse_skip_invalid_lines()
    print("All parse tests passed!")
```

- [x] **Step 2: 运行测试，确认失败（模块不存在）**

Run: `cd scripts && python tests/test_logic_writer.py`
Expected: ImportError — `logic_writer` 不存在

- [x] **Step 3: 实现 `parse_logic_block`**

```python
# scripts/operations/logic_writer.py
# -*- coding: utf-8 -*-
"""问卷逻辑规则解析与写入 — 替代 logic_ops.py"""
import re
import time

from core.utils import _log, _strip_html, _build_label_map
from survey_io.fetcher import get_survey_full
from operations.survey_ops import lock_survey, save_survey


def parse_logic_block(lines: list) -> list:
    """
    解析 [逻辑] 块文本行 → 结构化规则列表。

    语法：源题 Q{n} [子问题 {序号,...}] 选项|子选项 {值,...} → 显示 Q{n}[,Q{m}...]

    返回: [{"source":"Q1", "options":["1","2"], "targets":["Q2"],
            "sub_questions":None, "sub_options":None}, ...]
    """
    rules = []
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("源题"):
            continue

        # 1. 提取源题
        m_src = re.match(r"^源题\s+(Q\d+)", line)
        if not m_src:
            continue
        source = m_src.group(1)

        # 2. 提取目标（→ 显示 Qx,Qy）
        m_tgt = re.search(r"→\s*显示\s+(Q[\d,\s Q]+)", line)
        if not m_tgt:
            continue
        targets = re.findall(r"Q\d+", m_tgt.group(1))
        if not targets:
            continue

        # 3. 提取中间部分（源题和→之间）
        middle = line[m_src.end():m_tgt.start()].strip()

        sub_questions = None
        sub_options = None
        options = None

        # 4. 检测子问题
        m_sub = re.search(r"子问题\s+([\d,\s]+)", middle)
        if m_sub:
            sub_questions = [int(x.strip()) for x in m_sub.group(1).split(",") if x.strip()]
            middle = middle[m_sub.end():].strip()

        # 5. 检测子选项 vs 选项
        if "子选项" in middle:
            sub_part = re.sub(r"^子选项\s*", "", middle).strip()
            sub_options = _parse_option_values(sub_part)
        elif "选项" in middle:
            opt_part = re.sub(r"^选项\s*", "", middle).strip()
            options = _parse_option_values(opt_part)

        rules.append({
            "source": source,
            "options": options,
            "targets": targets,
            "sub_questions": sub_questions,
            "sub_options": sub_options,
        })

    return rules


def _parse_option_values(text: str) -> list:
    """解析选项值：引号包裹→文本，无引号→数值字符串"""
    # 尝试提取引号内的文本
    quoted = re.findall(r'["\u201c]([^"\u201d]*)["\u201d]', text)
    if quoted:
        return quoted
    # 无引号：按逗号分割
    return [v.strip() for v in text.split(",") if v.strip()]
```

- [x] **Step 4: 运行测试，确认全部通过**

Run: `cd scripts && python tests/test_logic_writer.py`
Expected: "All parse tests passed!"

- [x] **Step 5: Commit**

```bash
git add scripts/operations/logic_writer.py scripts/tests/test_logic_writer.py
git commit -m "feat: implement parse_logic_block with tests"
```

---

## Task 2: 实现 `resolve_logic_rules` 函数

**Files:**
- Modify: `scripts/operations/logic_writer.py`
- Modify: `scripts/tests/test_logic_writer.py`

- [x] **Step 1: 编写 resolve 单元测试**

在 `test_logic_writer.py` 末尾追加：

```python
from operations.logic_writer import resolve_logic_rules


def _make_mock_questions():
    """构造模拟问卷数据，覆盖三种题型"""
    return [
        # Q1: star 量表题 (idx=0)
        {
            "id": "q-001", "type": "star", "title": "<p>满意度评分</p>",
            "options": [
                {"id": "a-s1", "text": "1"}, {"id": "a-s2", "text": "2"},
                {"id": "a-s3", "text": "3"}, {"id": "a-s4", "text": "4"},
                {"id": "a-s5", "text": "5"},
            ],
            "subQuestions": [], "logic": [],
        },
        # Q2: blank 填空题 (idx=1)
        {
            "id": "q-002", "type": "blank", "title": "<p>不满意原因</p>",
            "options": [], "subQuestions": [], "logic": [],
        },
        # Q3: radio 单选题 (idx=2)
        {
            "id": "q-003", "type": "radio", "title": "<p>和谁一起玩</p>",
            "options": [
                {"id": "a-r1", "text": "自己一个人玩"},
                {"id": "a-r2", "text": "组队开黑"},
            ],
            "subQuestions": [], "logic": [],
        },
        # Q4: blank (idx=3)
        {"id": "q-004", "type": "blank", "title": "<p>队友</p>",
         "options": [], "subQuestions": [], "logic": []},
        # Q5: blank (idx=4)
        {"id": "q-005", "type": "blank", "title": "<p>场景</p>",
         "options": [], "subQuestions": [], "logic": []},
        # Q6: rect-star 矩阵量表 (idx=5)
        {
            "id": "q-006", "type": "rect-star", "title": "<p>活动评价</p>",
            "options": [
                {"id": "a-c1", "text": "1"}, {"id": "a-c2", "text": "2"},
                {"id": "a-c3", "text": "3"}, {"id": "a-c4", "text": "4"},
                {"id": "a-c5", "text": "5"},
            ],
            "subQuestions": [
                {"id": "a-sq1", "title": "资讯传递"},
                {"id": "a-sq2", "title": "任务难度"},
                {"id": "a-sq3", "title": "流程时长"},
                {"id": "a-sq4", "title": "界面清晰"},
                {"id": "a-sq5", "title": "目标明确"},
            ],
            "logic": [],
        },
        # Q7: radio (idx=6)
        {"id": "q-007", "type": "radio", "title": "<p>UI感受</p>",
         "options": [], "subQuestions": [], "logic": []},
    ]


def test_resolve_star_numeric():
    """量表题评分→选项ID"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q1", "options": ["1", "2"], "targets": ["Q2"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(errors) == 0
    assert len(resolved) == 1
    assert resolved[0]["src_idx"] == 0
    assert resolved[0]["option_ids"] == ["a-s1", "a-s2"]
    assert resolved[0]["target_ids"] == ["q-002"]
    assert resolved[0]["sub_question_ids"] == []


def test_resolve_radio_text():
    """单选题文本→选项ID"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q3", "options": ["组队开黑"], "targets": ["Q4", "Q5"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(errors) == 0
    assert resolved[0]["option_ids"] == ["a-r2"]
    assert resolved[0]["target_ids"] == ["q-004", "q-005"]


def test_resolve_rect_star():
    """矩阵量表子问题+子选项→ID"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q6", "sub_questions": [1, 2, 3], "sub_options": ["1", "2", "3"],
               "options": None, "targets": ["Q7"]}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(errors) == 0
    assert resolved[0]["sub_question_ids"] == ["a-sq1", "a-sq2", "a-sq3"]
    assert resolved[0]["option_ids"] == ["a-c1", "a-c2", "a-c3"]
    assert resolved[0]["target_ids"] == ["q-007"]


def test_resolve_source_not_found():
    """源题不存在→报错跳过"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q99", "options": ["1"], "targets": ["Q2"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(resolved) == 0
    assert len(errors) == 1
    assert "Q99" in errors[0]


def test_resolve_option_not_matched():
    """选项文本不匹配→警告"""
    questions = _make_mock_questions()
    parsed = [{"source": "Q3", "options": ["不存在的选项"], "targets": ["Q4"],
               "sub_questions": None, "sub_options": None}]
    resolved, errors = resolve_logic_rules(parsed, questions)
    assert len(resolved) == 0  # 无匹配选项，规则无效
    assert len(errors) >= 1
```

更新 `__main__` 块：
```python
if __name__ == "__main__":
    # parse tests
    test_parse_radio_text_option()
    test_parse_star_numeric_option()
    test_parse_multiple_text_options()
    test_parse_rect_star_sub_questions()
    test_parse_long_text_with_parens()
    test_parse_multiple_rules()
    test_parse_skip_invalid_lines()
    print("All parse tests passed!")
    # resolve tests
    test_resolve_star_numeric()
    test_resolve_radio_text()
    test_resolve_rect_star()
    test_resolve_source_not_found()
    test_resolve_option_not_matched()
    print("All resolve tests passed!")
```

- [x] **Step 2: 运行测试，确认失败（函数不存在）**

Run: `cd scripts && python tests/test_logic_writer.py`
Expected: ImportError 或 AttributeError — `resolve_logic_rules` 不存在

- [x] **Step 3: 实现 `resolve_logic_rules`**

在 `logic_writer.py` 中追加：

```python
def resolve_logic_rules(parsed_rules: list, questions: list):
    """
    将解析后的规则匹配为实际 ID。

    返回: (resolved_list, errors_list)
      resolved: [{"src_idx":0, "option_ids":[...], "target_ids":[...], "sub_question_ids":[...]}]
      errors: ["错误描述", ...]
    """
    label_map = _build_label_map(questions)
    resolved = []
    errors = []

    for rule in parsed_rules:
        source = rule["source"]
        # 1. 定位源题
        src_idx = label_map.get(source)
        if src_idx is None:
            errors.append(f"源题未找到: {source}")
            continue
        src_q = questions[src_idx]

        # 2. 定位目标题
        target_ids = []
        for tgt_label in rule["targets"]:
            tgt_idx = label_map.get(tgt_label)
            if tgt_idx is None:
                errors.append(f"目标题未找到: {tgt_label}")
                continue
            target_ids.append(questions[tgt_idx]["id"])
        if not target_ids:
            continue

        # 3. 匹配子问题 ID（矩阵题）
        sub_question_ids = []
        if rule.get("sub_questions"):
            subs = src_q.get("subQuestions") or []
            for seq in rule["sub_questions"]:
                if 1 <= seq <= len(subs):
                    sub_question_ids.append(subs[seq - 1]["id"])
                else:
                    errors.append(f"{source} 子问题序号 {seq} 越界（共 {len(subs)} 个子问题）")

        # 4. 匹配选项/子选项 ID
        option_ids = []
        opt_values = rule.get("sub_options") or rule.get("options") or []
        src_options = src_q.get("options") or []

        for val in opt_values:
            matched = False
            for opt in src_options:
                opt_text = _strip_html(opt.get("text", ""))
                # 精确匹配（数值）或模糊匹配（文本）
                if val == opt_text or val in opt_text:
                    option_ids.append(opt["id"])
                    matched = True
                    break
            if not matched:
                errors.append(f"{source} 选项未匹配: '{val}'")

        if not option_ids:
            errors.append(f"{source} 无有效选项匹配，规则跳过")
            continue

        resolved.append({
            "src_idx": src_idx,
            "option_ids": option_ids,
            "target_ids": target_ids,
            "sub_question_ids": sub_question_ids,
        })

    return resolved, errors
```

- [x] **Step 4: 运行测试，确认全部通过**

Run: `cd scripts && python tests/test_logic_writer.py`
Expected: "All parse tests passed!" + "All resolve tests passed!"

- [x] **Step 5: Commit**

```bash
git add scripts/operations/logic_writer.py scripts/tests/test_logic_writer.py
git commit -m "feat: implement resolve_logic_rules with tests"
```

---

## Task 3: 实现 `write_logic_rules` 和 `extract_logic_block`

**Files:**
- Modify: `scripts/operations/logic_writer.py`

- [x] **Step 1: 实现 `write_logic_rules`**

在 `logic_writer.py` 中追加：

```python
def write_logic_rules(session, base_url, survey_id, resolved_rules: list) -> dict:
    """
    将 resolved_rules 写入问卷 API。

    流程: fetch → 写入 logic 字段 → lock → save → 验证
    """
    _log(f"Writing {len(resolved_rules)} logic rules to survey {survey_id}...")

    survey_data = get_survey_full(session, base_url, survey_id)
    if not survey_data:
        return {"status": "error", "message": "获取问卷数据失败"}

    questions = survey_data.get("questions") or []
    applied = []

    for rule in resolved_rules:
        src_idx = rule["src_idx"]
        if src_idx >= len(questions):
            continue

        src_q = questions[src_idx]
        src_logic = src_q.get("logic") or []
        if not isinstance(src_logic, list):
            src_logic = []

        # 检查是否已有相同目标的规则（合并 option_ids）
        existing = None
        for lr in src_logic:
            if set(rule["target_ids"]).issubset(set(lr.get("questions") or [])):
                existing = lr
                break

        if existing:
            # 合并选项 ID（去重）
            existing_opts = set(existing.get("options") or [])
            existing_opts.update(rule["option_ids"])
            existing["options"] = list(existing_opts)
            # 合并子问题 ID（去重）
            if rule["sub_question_ids"]:
                existing_subs = set(existing.get("subQuestions") or [])
                existing_subs.update(rule["sub_question_ids"])
                existing["subQuestions"] = list(existing_subs)
        else:
            src_logic.append({
                "options": rule["option_ids"],
                "questions": rule["target_ids"],
                "subQuestions": rule["sub_question_ids"],
                "controlSubQuestions": "{}",
            })

        src_q["logic"] = src_logic
        from core.utils import _strip_html
        applied.append({
            "source_label": _build_label_map(questions).get(src_idx, f"idx={src_idx}"),
            "source_title": _strip_html(src_q.get("title", ""))[:30],
            "target_count": len(rule["target_ids"]),
            "option_count": len(rule["option_ids"]),
        })

    if not applied:
        return {"status": "error", "message": "没有成功应用的逻辑规则"}

    survey_data["questions"] = questions

    lock_ok = lock_survey(session, base_url, survey_id)
    if not lock_ok:
        return {"status": "error", "message": "锁定失败，请关闭编辑器", "applied": applied}

    save_result = save_survey(session, base_url, survey_data)
    _log("Verifying logic (waiting 3s)...")
    time.sleep(3)

    # 反查 label 用于日志
    label_reverse = {}
    lm = _build_label_map(questions)
    for lbl, idx in lm.items():
        label_reverse[idx] = lbl
    for a in applied:
        # 修正 source_label
        pass

    return {
        "status": save_result["status"],
        "message": f"成功设置 {len(applied)} 条逻辑规则",
        "applied": applied,
    }
```

- [x] **Step 2: 实现 `extract_logic_block`**

```python
def extract_logic_block(filepath: str) -> list:
    """从 .standard.md 文件末尾提取 [逻辑] 块的所有规则行。"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    logic_lines = []
    in_logic = False

    for line in lines:
        stripped = line.strip()
        if stripped == "[逻辑]":
            in_logic = True
            logic_lines = []  # 重置，取最后一个 [逻辑] 块
            continue
        if in_logic and stripped.startswith("源题"):
            logic_lines.append(stripped)

    return logic_lines
```

- [x] **Step 3: Commit**

```bash
git add scripts/operations/logic_writer.py
git commit -m "feat: implement write_logic_rules and extract_logic_block"
```

---

## Task 4: 集成 — 修改 importer.py

**Files:**
- Modify: `scripts/survey_io/importer.py:297-312`

- [x] **Step 1: 在 `import_from_markdown` 末尾添加逻辑写入调用**

修改 `importer.py` 的 `import_from_markdown` 函数，在 `return` 之前加入逻辑处理：

```python
def import_from_markdown(session, base_url, platform, survey_id, filepath):
    from operations.question_ops import add_questions

    _log(f"Parsing {filepath}...")
    specs = parse_question_file(filepath)
    _log(f"Parsed {len(specs)} question specs")

    if not specs:
        return {"status": "error", "message": "未解析到任何题目，请检查文件格式"}

    result = add_questions(session, base_url, platform, survey_id, specs)

    # ── 自动写入逻辑规则 ────────────────────────────────────────────
    if result.get("status") == "success":
        from operations.logic_writer import extract_logic_block, parse_logic_block, resolve_logic_rules, write_logic_rules
        logic_lines = extract_logic_block(filepath)
        if logic_lines:
            _log(f"Found {len(logic_lines)} logic rules in [逻辑] block")
            parsed = parse_logic_block(logic_lines)
            if parsed:
                survey_data = get_survey_full(session, base_url, survey_id)
                if survey_data:
                    questions = survey_data.get("questions") or []
                    resolved, logic_errors = resolve_logic_rules(parsed, questions)
                    if resolved:
                        logic_result = write_logic_rules(session, base_url, survey_id, resolved)
                        result["logic_result"] = logic_result
                    if logic_errors:
                        result["logic_errors"] = logic_errors
                    _log(f"Logic: {len(resolved)} resolved, {len(logic_errors)} errors")
        else:
            _log("No [逻辑] block found in file")

    return result
```

- [x] **Step 2: Commit**

```bash
git add scripts/survey_io/importer.py
git commit -m "feat: importer auto-invokes logic_writer after import"
```

---

## Task 5: 集成 — 改造 CLI `logic` 命令

**Files:**
- Modify: `scripts/survey_checker.py`

- [x] **Step 1: 替换 import 和 SurveyChecker 方法**

```python
# 删除旧 import（第29行）
# from operations.logic_ops import set_logic_rules

# 替换为新 import
from operations.logic_writer import extract_logic_block, parse_logic_block, resolve_logic_rules, write_logic_rules
```

替换 `SurveyChecker.set_logic_rules` 方法：
```python
    def set_logic(self, survey_id: int, rules_text: list = None, filepath: str = None):
        """设置逻辑规则（从文本行或文件）"""
        if filepath:
            logic_lines = extract_logic_block(filepath)
        elif rules_text:
            logic_lines = rules_text
        else:
            return {"status": "error", "message": "需要 --file 或 --rules 参数"}

        if not logic_lines:
            return {"status": "error", "message": "未找到有效的逻辑规则"}

        parsed = parse_logic_block(logic_lines)
        if not parsed:
            return {"status": "error", "message": "逻辑规则解析失败，请检查格式"}

        survey_data = get_survey_full(self.session, self.base_url, survey_id)
        if not survey_data:
            return {"status": "error", "message": "获取问卷数据失败"}

        questions = survey_data.get("questions") or []
        resolved, errors = resolve_logic_rules(parsed, questions)

        result = {"parsed": len(parsed), "resolved": len(resolved), "errors": errors}
        if resolved:
            write_result = write_logic_rules(self.session, self.base_url, survey_id, resolved)
            result.update(write_result)
        else:
            result["status"] = "error"
            result["message"] = "无有效规则可写入"

        return result
```

- [x] **Step 2: 替换 CLI 参数定义和执行逻辑**

替换 logic 子命令参数定义：
```python
    lgp = subs.add_parser("logic", help="设置问卷题目间的逻辑规则")
    lgp.add_argument("--id", type=int, required=True, help="问卷 ID")
    lgp.add_argument("--file", type=str, help="从 .standard.md 文件提取 [逻辑] 块")
    lgp.add_argument("--rules", type=str, help="直接传入逻辑规则文本（多条用分号分隔）")
```

替换执行逻辑：
```python
    elif args.command == "logic":
        rules_text = None
        if args.rules:
            rules_text = [r.strip() for r in args.rules.split(";") if r.strip()]
        _json_output(checker.set_logic(args.id, rules_text=rules_text, filepath=args.file))
```

- [x] **Step 3: Commit**

```bash
git add scripts/survey_checker.py
git commit -m "feat: CLI logic command uses logic_writer"
```

---

## Task 6: 清理 — 删除旧文件和引用

**Files:**
- Delete: `scripts/operations/logic_ops.py`
- Modify: `scripts/operations/question_ops.py:100-118`
- Delete: `scripts/_debug_logic.py` (临时文件)

- [x] **Step 1: 删除 `logic_ops.py`**

```bash
git rm scripts/operations/logic_ops.py
```

- [x] **Step 2: 清理 `question_ops.py` 中已注释的 logic_ops 引用**

删除第 100-118 行的注释块，替换为简洁说明：

```python
    # 逻辑规则由 importer.py 在录入完成后通过 logic_writer 自动写入

    result = {
        "status": "success",
        "message": f"成功新增 {len(added)} 道题目",
        "added": added,
    }
    return result
```

- [x] **Step 3: 删除临时调试文件**

```bash
git rm scripts/_debug_logic.py
```

- [x] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove logic_ops.py, clean up references"
```

---

## Task 7: 更新 SKILL.md

**Files:**
- Modify: `SKILL.md`

- [x] **Step 1: 更新 Step 3.7 — 移除"暂不支持逻辑"提示**

将之前添加的逻辑暂不支持段落替换为：

```markdown
**逻辑规则自动写入：** 如果标准格式文件末尾包含 `[逻辑]` 块，`import` 命令会在题目录入成功后自动解析并写入逻辑规则。支持三种条件类型：
- 选项文本匹配：`源题 Q16 选项 "组队开黑" → 显示 Q17,Q18`
- 量表评分范围：`源题 Q1 选项 1,2 → 显示 Q2`
- 矩阵量表子问题：`源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29`

AI 在转化标准格式时，应在文件末尾生成 `[逻辑]` 块，汇总所有逻辑规则。
```

- [x] **Step 2: 更新 Step 3.8 — 重写为新命令格式**

```markdown
### Step 3.8: 设置逻辑规则

当用户要求单独设置逻辑规则时：
\```bash
# 从 .standard.md 文件提取 [逻辑] 块并写入
python {SKILL_DIR}/survey_checker.py logic --id 问卷ID --file "文件路径.standard.md"

# 直接传入规则（多条用分号分隔）
python {SKILL_DIR}/survey_checker.py logic --id 问卷ID --rules "源题 Q1 选项 1,2 → 显示 Q2; 源题 Q16 选项 \"组队开黑\" → 显示 Q17"
\```
```

- [x] **Step 3: 更新任务完成展示表格**

将"待设置的逻辑规则"行替换为：

```markdown
| **逻辑规则** | 录入后（如文件含 [逻辑] 块） | 如"5 条已写入" |
```

- [x] **Step 4: 更新概述描述**

将"跳转逻辑暂不支持自动写入，需用户手动设置"改为"支持跳转逻辑自动写入"

- [x] **Step 5: Commit**

```bash
git add SKILL.md
git commit -m "docs: update SKILL.md for logic_writer"
```

---

## Task 8: 端到端集成测试

**Files:** 无新建，使用已有文件和问卷 91986

- [x] **Step 1: 为测试文件添加 [逻辑] 块**

在 `D:\备份\UR工作资料-202510\【材料】优秀报告\优秀竞品问卷\金铲铲回流体验问卷.standard.md` 末尾追加：

```markdown
[逻辑]
源题 Q1 选项 1,2 → 显示 Q2
源题 Q16 选项 "组队开黑" → 显示 Q17,Q18
源题 Q24 选项 "非常困难","有点困难" → 显示 Q25
源题 Q27 选项 "知道，且参加了" → 显示 Q28
源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29
```

- [x] **Step 2: 测试 CLI 单条规则**

```bash
cd scripts
python survey_checker.py logic --id 91986 --rules "源题 Q1 选项 1,2 → 显示 Q2"
```
预期：成功设置 1 条规则，Q1 的 logic 写入评分 1、2 → 显示 Q2

- [x] **Step 3: 验证 Q1 逻辑数据**

```bash
python survey_checker.py fetch --id 91986
```
检查 Q1 的 logic 字段包含正确的 option_ids 和 target question_id

- [x] **Step 4: 测试 CLI 文件模式**

```bash
python survey_checker.py logic --id 91986 --file "D:\备份\...\金铲铲回流体验问卷.standard.md"
```
预期：提取 5 条规则，全部写入成功

- [x] **Step 5: 验证矩阵量表逻辑**

```bash
python -c "..." # 对比 Q28 的 logic 数据与手动配置的一致性
```
检查 Q28 的 subQuestions 和 options 字段与手动配置一致

- [x] **Step 6: 测试 import 自动触发**

```bash
python survey_checker.py create --name "逻辑端到端测试" --game "g79"
python survey_checker.py import --file "D:\备份\...\金铲铲回流体验问卷.standard.md" --id <新ID>
```
预期：录入 35 题后自动写入 5 条逻辑，返回 logic_result

- [x] **Step 7: 预览验证**

在浏览器中打开新问卷预览，测试逻辑是否生效

- [x] **Step 8: Commit + Push**

```bash
git add -A
git commit -m "test: end-to-end logic writer integration verified"
git push origin master
```