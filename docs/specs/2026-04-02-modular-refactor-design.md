# survey_checker 模块化重构设计文档

**日期**：2026-04-02  
**状态**：待实施  
**背景**：`scripts/survey_checker.py` 已达 ~2600 行，单文件难以维护和测试，需要按职责拆分为多模块结构。

---

## 一、设计目标

1. **可维护性**：每个文件职责单一，100–300 行，易于理解和修改
2. **向后兼容**：`SurveyChecker` 类的所有公开方法签名保持不变，调用方无需修改
3. **平台差异集中**：国内/国外差异仅在少数几处（配置、preview 触发等），不重复代码
4. **可测试性**：每个模块可独立单元测试，不依赖完整的 session/auth

---

## 二、方案选择

### 方案 A（❌ 不采用）：按平台拆分
```
cn_survey.py / global_survey.py
```
问题：~80% 代码重复，每次 bugfix 要改两处。

### 方案 B（✅ 采用）：按职责纵向拆分
平台差异通过 `platform` 配置 + 少量 `if self.platform == "global"` 处理，不重复逻辑。

---

## 三、目标文件结构

```
scripts/
├── survey_checker.py          # ★ 对外入口（保持不变的公开接口 + CLI）
│                               #   仅做组装：实例化各子模块，代理方法调用
│
├── core/
│   ├── __init__.py
│   ├── auth.py                # Cookie 管理、自动刷新（Playwright）
│   ├── client.py              # 底层 HTTP session 封装（requests.Session）
│   └── utils.py               # _strip_html, _gen_id, _log 等工具函数
│
├── operations/
│   ├── __init__.py
│   ├── survey_ops.py          # copy_survey, create_survey, save_survey, lock_survey
│   ├── question_ops.py        # add_questions, clear_questions, modify_questions
│   ├── builder.py             # _build_question_from_spec（spec → API 格式核心转换）
│   ├── calibrate.py           # calibrate / autofix（R1–R7 校准规则）
│   └── logic_ops.py           # set_logic_rules（显示/跳转逻辑）
│
└── io/
    ├── __init__.py
    ├── fetcher.py             # fetch_survey, search_surveys, get_survey_full
    └── importer.py            # import_from_markdown（Markdown → add_questions）
```

---

## 四、各模块职责说明

### 4.1 `core/auth.py`
- **职责**：管理 Cookie 的读取、保存、有效性检查和自动刷新
- **关键函数**：
  - `refresh_cookie(platform)` → 用 Playwright 打开浏览器，等待 Cookie，保存到 config json
  - `load_cookies(platform)` → 从 config json 读取 Cookie，返回 dict
  - `is_auth_valid(session, platform)` → 发送轻量 ping 请求，返回 True/False
- **平台差异**：通过 `PLATFORMS` 配置字典处理（不同的 cookie key、domain）

### 4.2 `core/client.py`
- **职责**：创建并配置 `requests.Session`，挂载 Cookie 和 headers
- **关键函数**：
  - `make_session(platform, cookies)` → 返回配置好的 Session 实例
  - `_make_headers(base_url)` → 生成标准 HTTP headers

### 4.3 `core/utils.py`
- **职责**：纯工具函数，无外部依赖
- **包含**：`_log`, `_strip_html`, `_gen_id`, `_build_label_map`

### 4.4 `operations/survey_ops.py`
- **职责**：问卷级别的 CRUD 操作
- **关键方法**：
  - `copy_survey(session, platform, source_id, new_name)` → 复制问卷，触发静态文件生成
  - `create_survey(session, platform, name, game_name, ...)` → 新建空白问卷
  - `save_survey(session, platform, survey_data)` → 保存整个问卷数据
  - `lock_survey(session, platform, survey_id)` → 编辑前加锁
- **平台差异集中点**：preview 触发逻辑（`if platform == "global"`）

### 4.5 `operations/question_ops.py`
- **职责**：题目的增删改操作
- **关键方法**：
  - `add_questions(session, platform, survey_id, specs)` → 新增题目
  - `clear_questions(session, platform, survey_id, keep_imply)` → 清空题目
  - `modify_questions(session, platform, survey_id, modifications)` → 修改题目
- **依赖**：`builder.py`（构建题目对象）、`survey_ops.py`（lock + save）

### 4.6 `operations/builder.py`
- **职责**：将用户提供的 spec 字典转换为平台 API 所需的完整 question 对象
- **关键函数**：
  - `build_question(spec, existing_questions)` → 入口，按 type 分派
  - `_build_radio(spec)`, `_build_checkbox(spec)`, `_build_star(spec)` 等子函数（按题型拆分）
  - `resolve_insert_position(spec, questions, label_map)` → 插入位置解析
- **说明**：此模块是当前代码最臃肿的地方（~400 行），拆分后每个题型函数约 20–50 行

### 4.7 `operations/calibrate.py`
- **职责**：R1–R7 校准规则的扫描和自动修复
- **关键方法**：
  - `calibrate(session, platform, survey_id, dry_run)` → 主入口
  - 每条规则独立为一个私有函数：`_check_r1_required`, `_check_r2_other_no_random`, 等
- **语言支持**：中文/英文/日文关键词统一在此文件顶部维护

### 4.8 `operations/logic_ops.py`
- **职责**：显示/跳转逻辑规则的设置
- **关键方法**：
  - `set_logic_rules(session, platform, survey_id, rules)` → 将 label/文本格式转换为 ID 格式并保存

### 4.9 `io/fetcher.py`
- **职责**：从平台读取问卷数据并整合为结构化输出
- **关键方法**：
  - `get_survey_full(session, platform, survey_id)` → 调用 detail 接口，返回原始完整数据
  - `search_surveys(session, platform, name)` → 按名称搜索，返回匹配列表
  - `fetch_survey(session, platform, survey_id, survey_name)` → 整合输出（含题目、选项、逻辑）

### 4.10 `io/importer.py`
- **职责**：解析 Markdown 文件并导入为问卷题目
- **关键方法**：
  - `parse_markdown(filepath)` → 解析 MD 文件，返回 spec 列表
  - `import_from_markdown(session, platform, survey_id, filepath)` → parse → add_questions

### 4.11 `survey_checker.py`（入口文件，保持不变）
- **职责**：
  1. `SurveyChecker` 类：组装上述所有子模块，提供统一的公开方法（向后兼容）
  2. CLI 入口：`argparse` 解析命令行参数，调用对应方法
- **原则**：此文件**不包含业务逻辑**，只做方法代理和初始化

---

## 五、数据流示意

```
用户调用
  gl.copy_survey(44583, "新名称")
        ↓
survey_checker.py  (SurveyChecker.copy_survey)
        ↓
operations/survey_ops.py  (copy_survey 函数)
    ├── io/fetcher.py  (get_survey_full → 获取源问卷信息)
    ├── core/client.py  (session.post → 调用复制 API)
    └── io/fetcher.py  (get_survey_full → 获取新问卷 URL)
        ↓
返回 {"status": "success", "new_id": ..., "preview_url": ...}
```

---

## 六、平台差异处理策略

平台差异**不拆文件**，通过以下方式集中处理：

| 差异点 | 处理方式 |
|--------|----------|
| Cookie key 不同 | `PLATFORMS` 配置字典（已有） |
| base_url 不同 | `PLATFORMS` 配置字典（已有） |
| preview 触发逻辑 | `survey_ops.py` 中 `if platform == "global"` |
| 复制接口 fallback | `survey_ops.py` 中 `if platform == "global"` |
| setting 接口行为不同 | 注释说明 + 条件判断 |

---

## 七、实施计划（分阶段）

### Phase 1：抽取工具层（低风险，无功能变更）
- [ ] 创建 `core/utils.py`，迁移 `_log`, `_strip_html`, `_gen_id`, `_build_label_map`
- [ ] 创建 `core/client.py`，迁移 `_make_headers`, `make_session`
- [ ] 验证：运行现有测试，确认无 regression

### Phase 2：抽取认证模块
- [ ] 创建 `core/auth.py`，迁移 `refresh_cookie`, `_ensure_auth`
- [ ] `survey_checker.py` 中改为调用 `auth.py`
- [ ] 验证：手动触发一次 Cookie 刷新，确认正常

### Phase 3：抽取 IO 层
- [ ] 创建 `io/fetcher.py`，迁移 `get_survey_full`, `search_surveys`, `fetch_survey`
- [ ] 验证：`fetch_survey(44583)` 返回结果与重构前一致

### Phase 4：抽取 builder（最复杂，独立处理）
- [ ] 创建 `operations/builder.py`，迁移 `_build_question_from_spec`
- [ ] 按题型拆分为子函数（radio/checkbox/star/rect-star/blank/paging/describe/imply）
- [ ] 验证：对已有问卷运行 add_questions，确认题目结构无变化

### Phase 5：抽取 operations 层
- [ ] 创建 `operations/survey_ops.py`：copy, create, save, lock
- [ ] 创建 `operations/question_ops.py`：add, clear, modify
- [ ] 创建 `operations/logic_ops.py`：set_logic_rules
- [ ] 创建 `operations/calibrate.py`：calibrate + R1–R7 规则函数
- [ ] 验证：逐一运行 copy/add/calibrate，确认行为一致

### Phase 6：抽取 Markdown 导入
- [ ] 创建 `io/importer.py`，迁移 `import_from_markdown`, `parse_markdown`
- [ ] 验证：用日文问卷 MD 文件运行一次导入

### Phase 7：清理入口文件
- [ ] `survey_checker.py` 只保留 `SurveyChecker` 类外壳 + CLI
- [ ] 所有方法改为调用对应子模块函数
- [ ] 全量回归测试

---

## 八、向后兼容保证

重构完成后，以下调用方式**必须继续有效**，无需任何修改：

```python
from survey_checker import SurveyChecker

cn = SurveyChecker('cn')
gl = SurveyChecker('global')

# 所有现有方法签名不变
gl.copy_survey(44583, new_name="副本")
gl.create_survey("新问卷", "h55na", lang="日文")
gl.add_questions(44710, specs=[...])
gl.calibrate(44710)
gl.fetch_survey(survey_id=44710)
gl.import_from_markdown(44710, "path/to/file.md")
```

CLI 用法不变：
```bash
python survey_checker.py fetch --id 44710
python survey_checker.py search --name "测试"
```

---

## 九、成功标准

- [ ] 所有文件 < 350 行
- [ ] 每个模块可被独立 import 而不触发副作用
- [ ] 所有现有公开方法签名向后兼容
- [ ] 国内/国外平台功能均正常（copy + preview URL 200，无协作群）
- [ ] `survey_checker.py` 入口文件 < 150 行（纯组装）
