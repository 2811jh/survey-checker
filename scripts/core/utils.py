# -*- coding: utf-8 -*-
"""工具函数：日志、HTML清洗、ID生成、标签映射"""
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
