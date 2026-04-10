#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网易问卷质量检查工具 — 重构后的薄入口（Phase 4）

所有核心实现均委托给 scripts/ 子模块：
  core/        认证、HTTP 客户端、通用工具、常量
  survey_io/   数据抓取（fetcher）、文本解析导入（importer）
  operations/  survey_ops / question_ops / logic_writer / builder / calibrate

向后兼容：原有调用方式完全不变。
"""

import argparse
import json
import sys

from core.utils import _log, _strip_html, _json_output
from core.constants import PLATFORMS, DEFAULT_PLATFORM
from core.auth import ensure_auth, check_auth
from core.client import make_session
from survey_io.fetcher import (
    get_survey_full, get_question_detail,
    search_surveys, fetch_survey,
)
from survey_io.importer import parse_question_file
from operations.survey_ops import copy_survey, create_survey, lock_survey, save_survey
from operations.question_ops import clear_questions, add_questions, modify_questions
from operations.logic_writer import (
    extract_logic_block, parse_logic_block,
    resolve_logic_rules, write_logic_rules,
)
from operations.calibrate import calibrate


# ─── SurveyChecker 包装类（向后兼容公共接口） ─────────────────────────────────

class SurveyChecker:
    """
    向后兼容的包装类。
    实现全部委托给 operations / survey_io 子模块，
    本类只负责存储 session/base_url/platform，并把方法签名适配为原来的形式。
    """

    def __init__(self, platform: str = DEFAULT_PLATFORM):
        self.platform = platform
        self.platform_config = PLATFORMS[platform]
        self.base_url = self.platform_config["base_url"]
        self.session = make_session(platform)

    # ── 认证 ──────────────────────────────────────────────────────────────────

    def check_auth(self) -> bool:
        return check_auth(self.session, self.platform)

    def _ensure_auth(self) -> bool:
        return ensure_auth(
            self.session, self.platform,
            reload_session_fn=lambda: setattr(self, "session", make_session(self.platform)),
        )

    def _auto_refresh_cookie(self) -> bool:
        from core.auth import refresh_cookie
        return refresh_cookie(self.platform)

    # ── 搜索 / 抓取 ────────────────────────────────────────────────────────────

    def search_surveys(self, keyword: str, page: int = 1):
        return search_surveys(self.session, self.base_url, keyword, page)

    def fetch_survey(self, survey_id=None, survey_name=None, select_index=None):
        return fetch_survey(
            self.session, self.base_url,
            survey_id=survey_id,
            survey_name=survey_name,
            select_index=select_index,
        )

    # ── 问卷 CRUD ──────────────────────────────────────────────────────────────

    def copy_survey(self, source_id: int, new_name: str = None):
        return copy_survey(self.session, self.base_url, self.platform, source_id, new_name)

    def create_survey(self, name: str, game_name: str, lang: str = "简体中文",
                      delivery_range: int = 0, direct_area: int = 0):
        return create_survey(
            self.session, self.base_url, self.platform,
            name=name, game_name=game_name, lang=lang,
            delivery_range=delivery_range, direct_area=direct_area,
        )

    def lock_survey(self, survey_id: int):
        return lock_survey(self.session, self.base_url, survey_id)

    def save_survey(self, survey_data: dict):
        return save_survey(self.session, self.base_url, survey_data)

    # ── 题目操作 ───────────────────────────────────────────────────────────────

    def clear_questions(self, survey_id: int, keep_imply: bool = False):
        return clear_questions(self.session, self.base_url, survey_id, keep_imply)

    def add_questions(self, survey_id: int, question_specs: list):
        return add_questions(self.session, self.base_url, self.platform, survey_id, question_specs)

    def modify_questions(self, survey_id: int, modifications: list):
        return modify_questions(self.session, self.base_url, survey_id, modifications)

    # ── 逻辑规则 ───────────────────────────────────────────────────────────────

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

    # ── 校准（自动修复） ────────────────────────────────────────────────────────

    def calibrate(self, survey_id: int, dry_run: bool = False):
        return calibrate(self.session, self.base_url, survey_id, dry_run)

    def autofix(self, survey_id: int, dry_run: bool = False):
        """autofix 别名 → calibrate（向后兼容）"""
        return self.calibrate(survey_id, dry_run)

    # ── 静态工具 ───────────────────────────────────────────────────────────────

    @staticmethod
    def parse_question_file(file_path: str) -> list:
        return parse_question_file(file_path)

    # ── 低级数据访问 ────────────────────────────────────────────────────────────

    def get_survey_full(self, survey_id: int):
        return get_survey_full(self.session, self.base_url, survey_id)

    def get_question_detail(self, survey_id: int):
        return get_question_detail(self.session, self.base_url, survey_id)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _load_json_arg(raw: str):
    """解析 --json 参数：支持 @文件路径 或内联 JSON 字符串"""
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(
        description="网易问卷质量检查工具 — 获取问卷内容（支持国内/国外双平台）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--platform", "-p", choices=["cn", "global"], default="cn",
        help="问卷平台：cn=国内(survey-game.163.com)，global=国外(survey-game.easebar.com)。默认 cn",
    )
    subs = parser.add_subparsers(dest="command", help="可用命令")

    # check
    subs.add_parser("check", help="检查认证是否有效（失败时自动刷新）")

    # search
    sp = subs.add_parser("search", help="按名称搜索问卷")
    sp.add_argument("--name", required=True)
    sp.add_argument("--page", type=int, default=1)

    # fetch
    fp = subs.add_parser("fetch", help="抓取问卷完整内容（题目+选项+逻辑）")
    fp.add_argument("--id", type=int)
    fp.add_argument("--name")
    fp.add_argument("--select", type=int)

    # modify
    mp = subs.add_parser("modify", help="修改问卷题目设置（通过JSON）")
    mp.add_argument("--id", type=int, required=True)
    mp.add_argument("--json", required=True)

    # calibrate + autofix（别名）
    for cmd in ("calibrate", "autofix"):
        cp = subs.add_parser(cmd, help="问卷校准：按 R1-R8 固定规则自动扫描并修复")
        cp.add_argument("--id", type=int, required=True)
        cp.add_argument("--dry-run", action="store_true")

    # copy
    copyp = subs.add_parser("copy", help="复制问卷")
    copyp.add_argument("--id", type=int, required=True)
    copyp.add_argument("--name", default=None)

    # create
    crp = subs.add_parser("create", help="创建新的空白问卷")
    crp.add_argument("--name", required=True)
    crp.add_argument("--game", required=True)
    crp.add_argument("--lang", default="简体中文")
    crp.add_argument("--internal", action="store_true")
    crp.add_argument("--europe", action="store_true")

    # add
    addp = subs.add_parser("add", help="向问卷新增题目")
    addp.add_argument("--id", type=int, required=True)
    addp.add_argument("--json", required=True)

    # logic
    lgp = subs.add_parser("logic", help="设置问卷题目间的逻辑规则")
    lgp.add_argument("--id", type=int, required=True)
    lgp.add_argument("--file", type=str, help="从 .standard.md 文件提取 [逻辑] 块")
    lgp.add_argument("--rules", type=str, help="直接传入逻辑规则文本（多条用分号分隔）")

    # import
    imp = subs.add_parser("import", help="从文本文件解析题目并录入问卷")
    imp.add_argument("--id", type=int, required=True)
    imp.add_argument("--file", required=True)
    imp.add_argument("--dry-run", action="store_true")

    # clear
    clp = subs.add_parser("clear", help="清空问卷所有题目")
    clp.add_argument("--id", type=int, required=True)
    clp.add_argument("--keep-imply", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    checker = SurveyChecker(platform=args.platform)

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
        _json_output(checker.search_surveys(args.name, args.page))

    elif args.command == "fetch":
        _json_output(checker.fetch_survey(
            survey_id=args.id, survey_name=args.name, select_index=args.select,
        ))

    elif args.command == "modify":
        mods = _load_json_arg(args.json)
        if not isinstance(mods, list):
            mods = [mods]
        _json_output(checker.modify_questions(args.id, mods))

    elif args.command in ("calibrate", "autofix"):
        _json_output(checker.calibrate(args.id, dry_run=args.dry_run))

    elif args.command == "copy":
        _json_output(checker.copy_survey(args.id, new_name=args.name))

    elif args.command == "create":
        _json_output(checker.create_survey(
            name=args.name, game_name=args.game, lang=args.lang,
            delivery_range=1 if args.internal else 0,
            direct_area=1 if args.europe else 0,
        ))

    elif args.command == "add":
        specs = _load_json_arg(args.json)
        if not isinstance(specs, list):
            specs = [specs]
        _json_output(checker.add_questions(args.id, specs))

    elif args.command == "logic":
        rules_text = None
        if args.rules:
            rules_text = [r.strip() for r in args.rules.split(";") if r.strip()]
        _json_output(checker.set_logic(args.id, rules_text=rules_text, filepath=getattr(args, 'file', None)))

    elif args.command == "clear":
        _json_output(checker.clear_questions(args.id, keep_imply=args.keep_imply))

    elif args.command == "import":
        _log(f"Parsing file: {args.file}")
        specs = parse_question_file(args.file)
        _log(f"Parsed {len(specs)} questions")
        if args.dry_run:
            _json_output({
                "status": "parsed", "count": len(specs),
                "questions": [
                    {
                        "type": s.get("type"),
                        "title": _strip_html(s.get("title", ""))[:60],
                        "options": len(s.get("options") or s.get("subQuestions") or []),
                        "required": s.get("required"),
                    }
                    for s in specs
                ],
            })
        else:
            from survey_io.importer import import_from_markdown
            _json_output(import_from_markdown(
                checker.session, checker.base_url, checker.platform,
                args.id, args.file,
            ))


if __name__ == "__main__":
    main()
