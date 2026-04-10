# 跳转逻辑自动设置工具 设计文档

**Goal:** 实现问卷跳转逻辑的自动解析与写入，支持选项文本匹配、量表评分范围、矩阵量表子问题三种条件类型，替代现有 `logic_ops.py`

**Architecture:** 新建 `logic_writer.py` 作为独立模块，提供三步流水线：文本解析(parse) → ID匹配(resolve) → API写入(write)。从 `importer.py` 录入完成后自动调用，也支持 CLI 独立调用。删除旧 `logic_ops.py`。

**Tech Stack:** Python 3, requests, re (正则解析)

---

## 1. 背景与现状

### 现有问题

- `logic_ops.py` 的 `set_logic_rules()` 接受 JSON 格式输入 (`sourceLabel` + `selectedOptionTexts` + `goToLabel`)
- `importer.py` 解析的 `[跳转逻辑]` 生成的格式 (`when_options` + `show_questions`) 与 `set_logic_rules` 不兼容
- 量表题条件("评分 1-2 分")无法转化为选项文本匹配
- 矩阵量表题(`rect-star`)的子问题逻辑完全不支持
- `add_questions` 中的逻辑写入已被禁用

### 目标

- 统一逻辑格式为结构化关键词格式
- 支持三种条件类型：选项文本、评分数值、矩阵子问题+子选项
- 录入题目后自动写入逻辑（路径 A/B/C 均支持）
- CLI 独立命令可用（路径 D 检查后写入）

---

## 2. 标准逻辑格式规范

### 位置

`.standard.md` 文件中有两处逻辑信息：

1. **题目级 `[跳转逻辑]`**：跟在每道题后面，作为人类可读的备注（AI 转化时生成）
2. **文件级 `[逻辑]`**：放在文件末尾所有题目之后，作为机器解析的执行依据

**工具只解析文件末尾的 `[逻辑]` 块。** 题目级的 `[跳转逻辑]` 仅供参考，不做执行解析。

### 语法

```
[逻辑]
源题 Q{n} [子问题 {序号,...}] 选项|子选项 {值,...} → 显示 Q{n}[,Q{m}...]
```

### 示例

```
[逻辑]
源题 Q1 选项 1,2 → 显示 Q2
源题 Q3 选项 "QQ（如QQ群、QQ空间、QQ游戏中心、兴趣部落等）" → 显示 Q4
源题 Q3 选项 "微信（如公众号、朋友圈、微信群、微信游戏中心、视频号等）" → 显示 Q5
源题 Q16 选项 "组队开黑" → 显示 Q17,Q18
源题 Q24 选项 "非常困难","有点困难" → 显示 Q25
源题 Q27 选项 "知道，且参加了" → 显示 Q28
源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29
```

### 解析规则

| 元素 | 语法 | 说明 |
|------|------|------|
| 源题 | `源题 Q{n}` | 必填，引用题号标签 |
| 子问题 | `子问题 {n},{m},...` | 可选，矩阵题专用，序号从 1 开始 |
| 选项（文本） | `选项 "文本1","文本2"` | 带引号，模糊匹配选项文本（`in` 匹配） |
| 选项（数值） | `选项 1,2,3` | 不带引号，精确匹配评分值/选项文本 |
| 子选项（数值） | `子选项 1,2,3` | 矩阵题列选项值，与 `子问题` 搭配使用 |
| 目标 | `→ 显示 Q{n}` 或 `→ 显示 Q{n},Q{m}` | 支持多目标 |

### 三种场景映射

| 场景 | 标准格式写法 | API logic 字段 |
|------|------------|---------------|
| 单选/多选 → 显示 | `源题 Q16 选项 "组队开黑" → 显示 Q17` | `{options:[opt_id], questions:[q_id], subQuestions:[]}` |
| 量表 → 显示 | `源题 Q1 选项 1,2 → 显示 Q2` | `{options:[score1_id, score2_id], questions:[q_id], subQuestions:[]}` |
| 矩阵量表 → 显示 | `源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29` | `{options:[col_opt_ids], questions:[q_id], subQuestions:[sub_ids]}` |

---

## 3. 模块设计

### 3.1 新建文件：`operations/logic_writer.py`

三个核心函数 + 一个辅助函数：

#### `parse_logic_block(lines: list[str]) -> list[dict]`

**职责**：将 `[逻辑]` 块的每行文本解析为结构化字典。

**输入**：文本行列表（不含 `[逻辑]` 标记行本身）

**输出**：
```python
[
    {
        "source": "Q1",              # 源题标签
        "options": ["1", "2"],        # 选项值列表
        "targets": ["Q2"],            # 目标题标签列表
        # 以下为矩阵题专用，不存在时为 None
        "sub_questions": None,        # 子问题序号列表 [1,2,3]
        "sub_options": None,          # 子选项值列表 ["1","2","3"]
    },
]
```

**解析逻辑**：
1. 正则提取：`^源题\s+(Q\d+)` → source
2. 可选提取：`子问题\s+([\d,\s]+)` → sub_questions
3. 关键词判断：遇到 `子选项` 或 `选项`
4. 选项值解析：引号包裹 → 文本值；无引号数字 → 数值
5. 目标提取：`→\s+显示\s+(Q[\d,\sQ]+)` → targets

#### `resolve_logic_rules(parsed_rules: list, questions: list) -> list[dict]`

**职责**：将标签和文本匹配为实际 ID。

**输入**：`parse_logic_block` 的输出 + 问卷的 questions 数组

**输出**：
```python
[
    {
        "src_idx": 0,                       # 源题在 questions 中的索引
        "option_ids": ["a-xxx", "a-yyy"],   # 匹配到的选项 ID
        "target_ids": ["q-zzz"],            # 匹配到的目标题 ID
        "sub_question_ids": [],             # 矩阵题：子问题 ID
    },
]
```

**ID 匹配策略**：

| 匹配对象 | 方法 |
|----------|------|
| source label → src_idx | `_build_label_map(questions)` |
| target label → target_id | `label_map[label]` → `questions[idx]["id"]` |
| 文本选项 → option_id | 遍历 `options`，`value in strip_html(opt["text"])` |
| 数值选项 → option_id | 遍历 `options`，`str(value) == strip_html(opt["text"])` |
| 子问题序号 → sub_question_id | `subQuestions[n-1]["id"]`（1-based） |

**错误处理**：
- 源题未找到 → 记录错误，跳过该规则
- 目标题未找到 → 记录错误，跳过该规则
- 选项未匹配 → 记录警告，该选项跳过（其他已匹配的选项仍生效）
- 子问题序号越界 → 记录错误，跳过该规则

#### `write_logic_rules(session, base_url, survey_id, resolved_rules: list) -> dict`

**职责**：将 resolved_rules 写入问卷 API。

**流程**：
1. `get_survey_full()` 获取最新数据
2. 遍历 resolved_rules，写入对应源题的 `logic` 数组
3. 如果目标题已有相同规则（同 target_id），合并 option_ids（去重）
4. `lock_survey()` → `save_survey()`
5. 等待 3s 后验证

**写入格式**（与 Q28 的实际数据一致）：
```python
{
    "options": rule["option_ids"],
    "questions": rule["target_ids"],
    "subQuestions": rule["sub_question_ids"],
    "controlSubQuestions": "{}",
}
```

#### `extract_logic_block(filepath: str) -> list[str]`

**辅助函数**：从 .standard.md 文件中提取 `[逻辑]` 块的所有行。

从文件末尾向前搜索 `[逻辑]` 标记行，提取其后所有以 `源题` 开头的行。

---

### 3.2 修改文件：`survey_io/importer.py`

**改动 1**：在 `import_from_markdown()` 末尾，题目录入成功后自动调用逻辑写入：

```python
def import_from_markdown(session, base_url, platform, survey_id, filepath):
    specs = parse_question_file(filepath)
    result = add_questions(session, base_url, platform, survey_id, specs)
    
    if result["status"] == "success":
        from operations.logic_writer import extract_logic_block, parse_logic_block, resolve_logic_rules, write_logic_rules
        logic_lines = extract_logic_block(filepath)
        if logic_lines:
            parsed = parse_logic_block(logic_lines)
            if parsed:
                survey_data = get_survey_full(session, base_url, survey_id)
                questions = survey_data.get("questions", []) or []
                resolved, errors = resolve_logic_rules(parsed, questions)
                if resolved:
                    logic_result = write_logic_rules(session, base_url, survey_id, resolved)
                    result["logic_result"] = logic_result
                if errors:
                    result["logic_errors"] = errors
    
    return result
```

**改动 2**：保留题目级 `[跳转逻辑]` 的解析（作为记录），但移除 `question_ops.py` 中已注释的调用代码。

---

### 3.3 修改文件：`survey_checker.py`

**改动**：替换 `logic` 子命令：

```python
# 旧
from operations.logic_ops import set_logic_rules

# 新
from operations.logic_writer import extract_logic_block, parse_logic_block, resolve_logic_rules, write_logic_rules
```

CLI 接口改为：
```bash
# 从 .standard.md 文件提取 [逻辑] 块并写入
python survey_checker.py logic --id 91986 --file "问卷.standard.md"

# 直接传入单条规则
python survey_checker.py logic --id 91986 --rules "源题 Q1 选项 1,2 → 显示 Q2"
```

---

### 3.4 删除文件

- `operations/logic_ops.py` — 完全删除

### 3.5 清理引用

- `question_ops.py` 第 100-118 行 — 删除已注释的 logic_ops 引用代码
- `survey_checker.py` 第 29 行 — 移除 `from operations.logic_ops import ...`

---

### 3.6 更新 SKILL.md

**Step 3.7**：移除"暂不支持自动录入跳转逻辑"的提示，改为说明自动录入行为

**Step 3.8**：重写为新的 CLI 命令格式

**任务完成展示**：移除"待设置的逻辑规则"行，改为"逻辑规则 | N 条已写入"

---

## 4. 测试方案

### 4.1 单元测试：`parse_logic_block`

| 用例 | 输入 | 预期输出 |
|------|------|---------|
| 单选文本 | `源题 Q16 选项 "组队开黑" → 显示 Q17,Q18` | `{source:"Q16", options:["组队开黑"], targets:["Q17","Q18"]}` |
| 量表评分 | `源题 Q1 选项 1,2 → 显示 Q2` | `{source:"Q1", options:["1","2"], targets:["Q2"]}` |
| 多选项文本 | `源题 Q24 选项 "非常困难","有点困难" → 显示 Q25` | `{source:"Q24", options:["非常困难","有点困难"], targets:["Q25"]}` |
| 矩阵量表 | `源题 Q28 子问题 1,2,3 子选项 1,2,3 → 显示 Q29` | `{source:"Q28", sub_questions:[1,2,3], sub_options:["1","2","3"], targets:["Q29"]}` |
| 空行/无效行 | `这不是逻辑规则` | 跳过，返回空列表 |

### 4.2 单元测试：`resolve_logic_rules`

需要构造 mock questions 数据，测试：
- label 映射正确性
- 文本模糊匹配（`in` 匹配）
- 数值精确匹配
- 矩阵子问题序号→ID
- 错误处理（源题不存在、选项不匹配等）

### 4.3 集成测试：端到端写入

使用问卷 91986 作为测试对象：

**测试 1**：CLI 单条规则
```bash
python survey_checker.py logic --id 91986 --rules "源题 Q1 选项 1,2 → 显示 Q2"
```
预期：Q1 的 logic 字段写入评分 1、2 的 option_id，目标为 Q2 的 question_id

**测试 2**：CLI 文件模式
```bash
python survey_checker.py logic --id 91986 --file "金铲铲.standard.md"
```
预期：提取 [逻辑] 块，批量写入所有规则

**测试 3**：import 自动触发
```bash
python survey_checker.py create --name "逻辑测试" --game "g79"
python survey_checker.py import --file "金铲铲.standard.md" --id <新ID>
```
预期：录入 35 题后自动写入逻辑，返回 logic_result

**测试 4**：矩阵量表验证
写入 Q28 矩阵逻辑后，fetch 问卷数据，对比与手动配置的 91986 数据结构一致

### 4.4 验证检查清单

- [ ] Q1 (star) → 选项 1,2 → 显示 Q2 ✅
- [ ] Q16 (radio) → 选项 "组队开黑" → 显示 Q17,Q18 ✅
- [ ] Q24 (radio) → 选项 "非常困难","有点困难" → 显示 Q25 ✅
- [ ] Q27 (radio) → 选项 "知道，且参加了" → 显示 Q28 ✅
- [ ] Q28 (rect-star) → 子问题 1,2,3 子选项 1,2,3 → 显示 Q29 ✅
- [ ] 预览页面正常显示 ✅
- [ ] 逻辑在预览中正确生效（条件触发时显示/隐藏） ✅

---

## 5. 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `operations/logic_writer.py` | **新建** | 核心模块：parse + resolve + write |
| `operations/logic_ops.py` | **删除** | 被 logic_writer 替代 |
| `survey_io/importer.py` | **修改** | import_from_markdown 末尾调用 logic_writer |
| `survey_checker.py` | **修改** | CLI logic 命令改为调用新模块 |
| `operations/question_ops.py` | **修改** | 删除已注释的 logic_ops 引用 |
| `SKILL.md` | **修改** | 更新 Step 3.7、3.8、完成展示表格 |