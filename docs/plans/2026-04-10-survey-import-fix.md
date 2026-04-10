# 问卷录入流程修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复问卷创建+录入流程中的三个核心问题，使通过 API 创建并录入的问卷与手动创建的行为完全一致

**Architecture:** 问题涉及三个层面：(1) `create_survey` 创建后缺少问卷级默认字段，导致预览不可用；(2) `add_questions` 中内嵌的逻辑写入存在 bug 且不可靠，应当禁用；(3) skill 指令中新建问卷的确认流程过于繁琐

**Tech Stack:** Python 3, requests, 网易问卷 API

---

## 代码架构概览

```
survey_checker.py          # CLI 入口 + SurveyChecker 包装类
├─ core/
│  ├─ auth.py              # Cookie 认证管理
│  ├─ client.py            # HTTP Session 工厂
│  ├─ constants.py         # 平台配置 + API 端点
│  └─ utils.py             # 日志、ID生成、标签映射
├─ survey_io/
│  ├─ fetcher.py           # 搜索/抓取问卷数据
│  └─ importer.py          # Markdown 解析 → spec 列表
├─ operations/
│  ├─ survey_ops.py        # 问卷级操作（create/copy/lock/save）
│  ├─ question_ops.py      # 题目增删改（clear/add/modify）
│  ├─ builder.py           # spec → 完整 question 对象
│  ├─ logic_ops.py         # 逻辑规则设置
│  └─ calibrate.py         # R1-R8 自动校准
```

**数据流：录入问卷**
```
用户文件 → convert_to_standard.py(AI读取) → AI转化 → .standard.md
→ importer.parse_question_file() → spec列表
→ question_ops.add_questions() → builder.build_question() → 构建question对象
→ survey_ops.lock_survey() + save_survey() → API写入
→ (内嵌) logic_ops.set_logic_rules() → 逻辑写入 [有BUG]
```

---

## 问题根因分析

### 问题 A：预览不可用（最严重）

**根因链路：**
1. `create_survey()` 调用 `/view/survey/add` API 创建空白问卷
2. API 返回的问卷只有基础字段（id, surveyName 等），70+ 个字段为 None
3. `add_questions()` 执行 `get_survey_full() → 修改 questions → save_survey()`
4. save 时把整个 survey_data（含 70 个 None 字段）写回服务端
5. 服务端存储了这些 None 值，覆盖了系统默认值
6. 预览渲染引擎依赖 `prefix`、`endDescription`、`customUrlType` 等字段，遇到 None 无法渲染

**手动创建为什么没问题？**
编辑器前端在首次保存时，会自动填充所有默认值（prefix、endDescription、closeDescription 等），所以通过编辑器保存后这些字段都有合理的值。

**影响范围：**
- `create_survey` → 新建问卷后预览不可用 ✅ 已确认
- `copy_survey` → 复制问卷继承了源问卷的完整数据，无此问题
- `add_questions` / `modify_questions` / `calibrate` → 这些操作也会 fetch→save 整个问卷数据，如果问卷本身字段缺失，save 后也会写入 None 值

### 问题 B：逻辑录入不可靠

**根因链路：**
1. `importer.py` 解析 `[跳转逻辑]` 文本 → `_parse_logic_lines()` → `spec["logic_rules"]`
2. `question_ops.add_questions()` 收集所有 spec 的 logic_rules → 调用 `logic_ops.set_logic_rules()`
3. `set_logic_rules()` 通过 `_build_label_map()` 定位源题和目标题
4. **BUG**：logic_rules 中的 `when_options` 是自然语言条件（如 "评分 1-2 分"），但 `set_logic_rules()` 的接口格式需要 `selectedOptionTexts`（选项文本精确匹配）—— 两套接口不兼容
5. 从 `add_questions` 内部调用时，题目刚插入还未 save，`_build_label_map` 基于刚 save 的数据重建，但 logic_rules 引用的 label（如 Q1→Q2）在 importer 解析时基于文件序号，与实际 label 不一定一致

**实际表现：** `import` 命令录入时所有逻辑规则都报 "来源题未找到: None"

### 问题 C：Skill 指令中新建流程确认项过多

**现状（Step 3.6a）：** 需确认 4 项（问卷名称、游戏名称、语言、投放范围）
**实际需求：** 只需确认问卷名称和所属游戏，其他全用默认值

---

## 修改任务

### Task 1: 修复 `create_survey` — 补全问卷默认字段

**Files:**
- Modify: `scripts/operations/survey_ops.py` (create_survey 函数，134-204行)

**分析：** 创建问卷后需要立即执行一次 fetch→补全→lock→save 流程，确保关键字段有默认值。

关键默认字段（从手动创建的问卷 91950 提取）：

| 字段 | 默认值 | 作用 |
|------|--------|------|
| prefix | 问卷前言文本 | 预览渲染必需 |
| prefixDiffStatus | 0 | 前言状态标记 |
| endDescription | 结束语文本 | 预览渲染必需 |
| closeDescription | 关闭说明文本 | 预览渲染必需 |
| endImgSrc | '/static/img/end.png' | 结束页图片 |
| closeImgSrc | '/static/img/close.png' | 关闭页图片 |
| customUrlType | 0 | URL 类型（0=系统生成）|
| endType | 0 | 结束页类型 |
| endURL | '' | 结束后跳转 |
| endButtonExist | 0 | 结束页按钮 |
| endButtonUrl | '' | 结束按钮链接 |
| closeButtonExist | 0 | 关闭页按钮 |
| closeButtonUrl | '' | 关闭按钮链接 |
| allowUserReadExamResult | 1 | 允许查看结果 |
| showExamResult | 1 | 显示测验结果 |
| redPackEnabled | 0 | 红包功能（0=关闭）|

- [ ] **Step 1: 在 `create_survey` 函数末尾（return 之前），添加"补全默认字段并保存"逻辑**

在 create_survey 的 `return` 语句之前（约第193行之后），添加一段代码：
```python
    # ── 补全默认字段（模拟编辑器首次保存行为）────────────────────────
    if new_id:
        import time as _time
        _log("Initializing survey defaults (simulating editor first-save)...")
        full_data = get_survey_full(session, base_url, new_id)
        if full_data:
            defaults = {
                "prefix": "为了给您提供更好的服务，希望您能抽出几分钟时间，将您的感受和建议告诉我们，我们非常重视每位用户的宝贵意见，期待您的参与！现在马上开始吧！",
                "prefixDiffStatus": 0,
                "endDescription": "您已完成本次问卷，感谢您的帮助与支持",
                "closeDescription": "该问卷已关闭，感谢您的关注",
                "endImgSrc": "/static/img/end.png",
                "closeImgSrc": "/static/img/close.png",
                "customUrlType": 0,
                "endType": 0,
                "endURL": "",
                "endButtonExist": 0,
                "endButtonUrl": "",
                "closeButtonExist": 0,
                "closeButtonUrl": "",
                "allowUserReadExamResult": 1,
                "showExamResult": 1,
                "redPackEnabled": 0,
            }
            for k, v in defaults.items():
                if full_data.get(k) is None:
                    full_data[k] = v
            
            lock_survey(session, base_url, new_id)
            save_result = save_survey(session, base_url, full_data)
            if save_result["status"] == "success":
                _log("Survey defaults initialized successfully")
            else:
                _log(f"Warning: defaults initialization failed: {save_result.get('message')}")
            
            # 触发预览 HTML 生成
            _time.sleep(1)
            try:
                from core.constants import API_SURVEY_PREVIEW
                pr = session.get(f"{base_url}{API_SURVEY_PREVIEW}", params={"id": new_id})
                pd = pr.json() if pr.text.strip() else {}
                if pd.get("resultCode") == 100:
                    _log(f"Preview generated: {pd.get('data', '')}")
                else:
                    _log(f"Preview generation warning: {pd.get('resultDesc', '')}")
            except Exception as e:
                _log(f"Preview generation error (non-fatal): {e}")
```

- [ ] **Step 2: 验证修复**

```bash
python survey_checker.py create --name "测试预览修复" --game "g79"
```
预期：创建成功，日志输出 "Survey defaults initialized successfully" 和 "Preview generated"
然后在浏览器中打开预览链接，确认能看到前言文本。

- [ ] **Step 3: 清理测试问卷**

删除之前创建的测试问卷 91946、91948。

---

### Task 2: 禁用 import 内置逻辑写入

**Files:**
- Modify: `scripts/operations/question_ops.py` (add_questions 函数，第 100-110 行)

**分析：** `add_questions` 在第 100-110 行收集 spec 中的 logic_rules 并调用 `set_logic_rules`。这条路径存在两个问题：
1. importer 解析的 logic_rules 格式（when_options）与 set_logic_rules 需要的格式（selectedOptionTexts）不兼容
2. 录入后题目的 label 可能与文件中引用的不一致

**修改策略：** 注释掉内置逻辑写入，但保留代码结构，方便后续修复后启用。

- [ ] **Step 1: 注释掉 `add_questions` 中的逻辑写入代码**

将 `question_ops.py` 第 100-117 行的逻辑相关代码注释掉：

```python
    # ── 逻辑规则写入（暂时禁用，待 logic 工具完善后启用） ────────────
    # all_logic_rules = []
    # for spec in question_specs:
    #     if "logic_rules" in spec:
    #         all_logic_rules.extend(spec["logic_rules"])
    # 
    # logic_result = None
    # if all_logic_rules and verify_data:
    #     from operations.logic_ops import set_logic_rules
    #     _log(f"Configuring {len(all_logic_rules)} logic rules...")
    #     logic_result = set_logic_rules(session, base_url, survey_id, all_logic_rules)

    result = {
        "status": "success",
        "message": f"成功新增 {len(added)} 道题目",
        "added": added,
    }
    # if logic_result:
    #     result["logic_result"] = logic_result
    return result
```

- [ ] **Step 2: 验证修改**

```bash
python survey_checker.py import --file "test.standard.md" --id <问卷ID>
```
预期：录入成功，不再出现逻辑相关的错误日志

---

### Task 3: 更新 Skill 指令

**Files:**
- Modify: skill 指令文件（`survey-checker` 的 instructions）

**修改内容：**

#### 3a. Step 3.6a — 简化新建问卷确认流程

**原文（需替换）：**
```
用 `ask_user_question` 依次确认：
1. **问卷名称**（如"《我的世界》4月版本调研"）
2. **游戏名称**（如"我的世界"）
3. **语言**：简体中文（默认）/ 繁体中文 / English
4. **投放范围**：公开（默认）/ 内部
```

**替换为：**
```
用 `ask_user_question` 依次确认：
1. **问卷名称**（如"《我的世界》4月版本调研"）
2. **所属游戏**（如"g79"） — 对应问卷系统中的"所属游戏"下拉字段

其他设置均使用默认值，无需向用户确认：
- 问卷类型 = 普通问卷
- 问卷语言 = 简体中文
- 协作群 = 不添加
- 发布确认人 = 不添加
- 投放范围 = 全网络
- 投放区域 = 全球
```

#### 3b. Step 3.7 — 标注逻辑暂不自动录入

在 Step 3.7 的"第五步：执行录入"之后，增加说明：

```
**⚠️ 关于跳转逻辑：** 目前系统暂不支持自动录入跳转逻辑。标准格式文件中的 `[跳转逻辑]` 块会被保留作为记录，但不会写入问卷系统。

录入完成后，需提醒用户：
- 列出所有需要设置的逻辑规则（从标准格式文件中提取）
- 提供问卷编辑链接，引导用户在编辑器中手动设置
- 格式示例："Q1 评分 1-2 分 → 显示 Q2（需在 Q1 的「题目设置 → 逻辑设置」中配置）"
```

#### 3c. 任务完成后展示信息 — 增加逻辑提醒

在"任务完成后必须展示"表格中增加一行：

```
| **待设置的逻辑规则** | 录入后（如标准格式含逻辑） | 逐条列出，提醒用户手动设置 |
```

---

## 修改文件清单

| 文件 | 修改类型 | 涉及任务 |
|------|---------|---------|
| `scripts/operations/survey_ops.py` | 在 create_survey 末尾添加默认字段补全 + 预览触发 | Task 1 |
| `scripts/operations/question_ops.py` | 注释掉 add_questions 中的逻辑写入代码 | Task 2 |
| skill 指令文件 | 更新 Step 3.6a、Step 3.7、完成展示表格 | Task 3 |

---

## 不修改的部分

| 文件/模块 | 原因 |
|----------|------|
| `logic_ops.py` | 逻辑引擎本身的 label→ID 解析是正确的，问题出在 importer 的调用方式。后续设计专门工具时再优化 |
| `builder.py` | 题目构建逻辑正确，字段完整 |
| `importer.py` | 解析逻辑正确，`[跳转逻辑]` 的解析保留，只是不在 add_questions 中执行 |
| `calibrate.py` | 校准逻辑独立，无需修改 |
| `fetcher.py` | 数据抓取正确 |
| `survey_checker.py` CLI | 命令行接口无需修改，`logic` 命令仍可单独使用 |
