# -*- coding: utf-8 -*-
"""
文本样式工具：为题干/选项中的关键词添加 HTML 红色标记。

规则：
  - <span style="color: #ba372a;">词</span> 包裹关键词
  - 每句/每个选项最多标记 2 个关键词
  - 通过语义规则自动识别需要标红的关键词
  - 短文字（< 4字）和纯数字选项自动跳过
"""
import re

RED_SPAN = '<span style="color: #ba372a;">{}</span>'


def _wrap_red(text: str) -> str:
    return RED_SPAN.format(text)


# 语义规则（按 5 类优先级排列，长短语优先，每条规则只替换一次）
_PATTERNS = [
    # ── 第 1 类：评价/态度关键词（最高优先级） ──
    (r'(整体满意度)', 1),
    (r'(满意度|满意程度)', 1),
    (r'(不太满意|不满意|不好|不足|不够|不清晰|不流畅|不顺畅|不便捷|不合理|不喜欢|不明显)', 1),
    (r'(愿意推荐|推荐)', 1),
    # ── 第 2 类：功能模块关键词 ──
    (r'(界面使用|美术画面|付费体验|社交体验|玩法体验|操作体验)', 1),
    (r'(匹配机制|战斗平衡性|玩法乐趣)', 1),
    # ── 第 3 类：技术/性能关键词 ──
    (r'(性能问题)', 1),
    (r'(卡顿|闪退|延迟|BUG|崩溃|黑屏|卡死|异常|发热)', 1),
    # ── 第 4 类：时间范围关键词 ──
    (r'(近一个月|近两周|近一周|近半年|近一年|近期|本赛季|目前)', 1),
    # ── 第 5 类：行动/反馈关键词（最低优先级） ──
    (r'(主要原因|建议|意见)', 1),
    (r'(频率|频繁|几乎每次)', 1),
]


def _apply_red(text: str, max_marks: int = 2) -> str:
    """对单段纯文本按语义规则添加红色标记，最多 max_marks 个。"""
    if not text or not text.strip():
        return text
    stripped = text.strip()
    # 跳过纯数字/短文字
    if re.fullmatch(r'[\d\s\-\/~～至到]+', stripped):
        return text
    if len(stripped) < 4:
        return text

    marked = 0
    result = text
    for pattern, group in _PATTERNS:
        if marked >= max_marks:
            break
        for m in re.finditer(pattern, result):
            if marked >= max_marks:
                break
            keyword = m.group(group) if group > 0 else m.group(0)
            if not keyword:
                continue
            # 检查是否已在 span 内
            prefix = result[:m.start()]
            if prefix.count('<span') > prefix.count('</span>'):
                continue
            new_result, n = re.subn(re.escape(keyword), _wrap_red(keyword), result, count=1)
            if n > 0:
                result = new_result
                marked += 1
                break
    return result


def _apply_red_to_title(title: str, max_marks: int = 2) -> str:
    """对题干应用标红，只处理第一个 HTML 块之前的纯文字部分。"""
    if not title:
        return title
    cut_pos = len(title)
    for tag in ['<img ', '<br>', '<p>']:
        pos = title.find(tag)
        if pos != -1 and pos < cut_pos:
            cut_pos = pos
    return _apply_red(title[:cut_pos], max_marks) + title[cut_pos:]


def apply_red_keywords(title, options=None, sub_questions=None, max_per_unit=2):
    """
    对题干、选项、子问题标题应用红色关键词标记。
    返回 (new_title, new_options, new_sub_questions)
    """
    new_title = _apply_red_to_title(title or '', max_per_unit)

    new_options = None
    if options is not None:
        new_options = []
        for opt in options:
            if isinstance(opt, dict):
                raw = opt.get('text', '')
                new_opt = dict(opt)
                # 跳过纯数字选项和以【】开头的分类标签选项（避免结构性标签被标红）
                skip = raw.strip().isdigit() or re.match(r'^【[^】]+】', raw.strip())
                new_opt['text'] = _apply_red(raw, max_per_unit) if not skip else raw
                new_options.append(new_opt)
            else:
                new_options.append(_apply_red(str(opt), max_per_unit))

    new_subs = None
    if sub_questions is not None:
        new_subs = []
        for sub in sub_questions:
            if isinstance(sub, dict):
                new_sub = dict(sub)
                # 跳过以【】开头的分类标签子问题（避免结构性标签被标红）
                sub_title = sub.get('title', '')
                skip = re.match(r'^【[^】]+】', sub_title.strip())
                new_sub['title'] = _apply_red(sub_title, max_per_unit) if not skip else sub_title
                new_subs.append(new_sub)
            else:
                new_subs.append(_apply_red(str(sub), max_per_unit))

    return new_title, new_options, new_subs


def build_image_html_for_title(image_url: str, max_height: int = 80) -> str:
    """为题干构建图片 HTML（插入到题干文字之后）。"""
    img = f'<img src="{image_url}" style="vertical-align:bottom;max-height:{max_height}px">'
    hint = '<span style="color: rgb(126, 140, 141); font-size: 8pt;">（点击图片可放大查看）</span>'
    return f'<br><p></p>\n<p></p>{img}<br>{hint}<p></p>'


def build_image_html_for_sub(image_url: str, max_height: int = 80) -> str:
    """为子问题构建图片 HTML。"""
    return f'<br><img src="{image_url}" style="vertical-align:bottom;max-height:{max_height}px">'
