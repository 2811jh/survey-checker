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

    # style
    stp = subs.add_parser("style", help="为问卷题目应用样式：红色关键词/插入图片")
    stp.add_argument("--id", type=int, required=True)
    stp.add_argument("--questions", default=None, help="题目范围,逗号分隔(如Q1,Q3)")
    stp.add_argument("--red", action="store_true", help="自动标记关键词（默认红色）")
    stp.add_argument("--color", default=None, help="关键词颜色：预设名(red/blue/green/orange/purple/brown/gray/black)或HEX值(#ba372a)，默认red")
    stp.add_argument("--image", default=None, help="图片CDN URL,插入到题干")
    stp.add_argument("--image-height", type=int, default=80)
    stp.add_argument("--image-target", choices=["title","sub"], default="title")
    stp.add_argument("--dry-run", action="store_true")

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

    elif args.command == "style":
        from operations.text_styler import (
            apply_red_keywords, build_image_html_for_title, build_image_html_for_sub,
        )
        from core.utils import _build_label_map

        survey_data = get_survey_full(checker.session, checker.base_url, args.id)
        if not survey_data:
            _json_output({"status": "error", "message": "获取问卷数据失败"})
            sys.exit(1)

        questions = survey_data.get("questions") or []
        label_map = _build_label_map(questions)

        target_labels = None
        if args.questions:
            target_labels = {l.strip() for l in args.questions.split(",") if l.strip()}

        change_log = []
        for idx, q in enumerate(questions):
            q_type = q.get("type", "")
            if q_type in ("imply", "paging"):
                continue
            q_label = next((lbl for lbl, i in label_map.items() if i == idx), None)
            if target_labels is not None and q_label not in target_labels:
                continue

            changed = False
            entry = {"label": q_label, "type": q_type, "changes": []}

            # 颜色关键词标记
            if args.red:
                new_title, new_opts, new_subs = apply_red_keywords(
                    q.get("title", ""),
                    q.get("options"),
                    q.get("subQuestions"),
                    color=args.color,
                )
                if new_title != q.get("title", ""):
                    q["title"] = new_title
                    entry["changes"].append("title 标红")
                    changed = True
                if new_opts:
                    for i2, (old_o, new_o) in enumerate(zip(q.get("options") or [], new_opts)):
                        if old_o.get("text") != new_o.get("text"):
                            questions[idx]["options"][i2] = new_o
                            entry["changes"].append(f"option[{i2}] 标红")
                            changed = True
                if new_subs:
                    for i2, (old_s, new_s) in enumerate(zip(q.get("subQuestions") or [], new_subs)):
                        if old_s.get("title") != new_s.get("title"):
                            questions[idx]["subQuestions"][i2] = new_s
                            entry["changes"].append(f"sub[{i2}] 标红")
                            changed = True

            # 图片插入
            if args.image:
                img_url = args.image
                img_h = args.image_height
                existing = q.get("title", "")
                if args.image_target == "title" and img_url not in existing:
                    img_html = build_image_html_for_title(img_url, img_h)
                    cut = len(existing)
                    for tag in ['<br>', '<img ', '<p>']:
                        pos = existing.find(tag)
                        if pos != -1 and pos < cut:
                            cut = pos
                    q["title"] = existing[:cut] + img_html + existing[cut:]
                    entry["changes"].append(f"title 插入图片 height={img_h}px")
                    changed = True
                elif args.image_target == "sub":
                    for i2, sub in enumerate(q.get("subQuestions") or []):
                        sub_title = sub.get("title", "") if isinstance(sub, dict) else ""
                        if img_url not in sub_title:
                            img_html = build_image_html_for_sub(img_url, img_h)
                            questions[idx]["subQuestions"][i2]["title"] = sub_title + img_html
                            entry["changes"].append(f"sub[{i2}] 插入图片")
                            changed = True

            if changed:
                change_log.append(entry)

        if not change_log:
            _json_output({"status": "no_change", "message": "没有题目需要修改"})
            sys.exit(0)

        if args.dry_run:
            _json_output({"status": "dry_run", "would_modify": len(change_log), "log": change_log})
            sys.exit(0)

        lock_survey(checker.session, checker.base_url, args.id)
        save_result = save_survey(checker.session, checker.base_url, survey_data)
        if save_result.get("status") != "success":
            _json_output({"status": "error", "message": save_result.get("message", "保存失败")})
            sys.exit(1)
        _json_output({
            "status": "success",
            "message": f"成功为 {len(change_log)} 道题应用样式",
            "modified": len(change_log),
            "log": change_log,
        })


if __name__ == "__main__":
    main()
