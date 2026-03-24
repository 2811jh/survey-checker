# 📋 Survey Checker

> 网易问卷（survey-game.163.com）全流程自动化管理 AI Skill

一个 [Agent Skills](https://github.com/vercel-labs/skills) 格式的 AI 编程助手技能，覆盖问卷从**创建 → 录入 → 检查 → 修复**的完整生命周期。

---

## 🚀 安装

### 第 1 步：安装前置软件

需要先安装以下 3 个软件，已装过的可以跳过：

| # | 软件 | 下载地址 | 注意事项 |
|---|------|----------|----------|
| 1 | [Git](https://git-scm.com/download/win) | https://git-scm.com/download/win | 安装时保持默认选项即可 |
| 2 | [Node.js](https://nodejs.org/) | https://nodejs.org/ | 选 **LTS（长期支持版）** |
| 3 | [Python 3](https://www.python.org/downloads/) | https://www.python.org/downloads/ | ⚠️ 安装时**务必勾选** "Add Python to PATH" |

> 💡 三个软件都装完后，**关掉所有已打开的命令行窗口**，重新打开才能生效。

### 第 2 步：打开命令行

按键盘 `Win + R`，输入 `cmd`，按回车。打开的黑色窗口就是命令行。

### 第 3 步：安装 skill

在命令行中粘贴以下命令，回车执行：

```bash
npx skills add 2811jh/survey-checker
```

过程中如果提示 `Ok to proceed? (y)`，输入 `y` 回车即可。

### 第 4 步：安装 Python 依赖

继续在命令行中执行：

```bash
pip install requests openpyxl playwright
```

```bash
playwright install chromium
```

> ✅ 全部完成！现在可以在 AI 助手中使用 survey-checker 了。

---

## ✨ 功能全景

### 🔍 质量检查
- **错别字检查** — 逐题扫描错别字、同音字混淆、标点错误
- **逻辑检查** — 互斥设置、必填一致性、跳转逻辑、选项区间重叠
- **设计专业性评估** — 量表一致性、题目措辞、问卷结构

### ✏️ 自动修复（R1-R6 规则引擎）
| 规则 | 检查内容 | 自动修复 |
|------|----------|:---:|
| R1 | 多选题 ≥8 选项 → 每行 2 列布局 | ✅ |
| R2 | 多选题全部随机 + 特殊项不随机 | ✅ |
| R3 | 排他选项（如"以上都没有"）→ 互斥 | ✅ |
| R4 | 文本题 → 非必填 | ✅ |
| R5 | 从属关系题 → 检查显示逻辑 | ⚠️ 仅报告 |
| R6 | 非文本题 → 必填（尊重"非必填"标注） | ✅ |

```bash
# 一键扫描 + 修复
py -3 survey_checker.py autofix --id 91112

# 仅扫描不修改
py -3 survey_checker.py autofix --id 91112 --dry-run
```

### 📝 问卷创建 & 题目录入
- **复制问卷** — 基于已有问卷快速创建新版本
- **题目录入** — 支持标准 txt 自动解析或 AI 智能解析任意格式
- **新增题目** — 支持单选/多选/填空/评分/矩阵/说明/分页/隐含题等全题型
- **逻辑设置** — 用题号标签或题目标题配置显示/跳转逻辑

```bash
# 复制问卷
py -3 survey_checker.py copy --id 91044 --name "新问卷名称"

# 从 txt 文件批量录入题目
py -3 survey_checker.py import --file "题目清单.txt" --id 91112

# 设置逻辑规则
py -3 survey_checker.py logic --id 91112 --json '[{"sourceLabel":"Q1","selectedOptionTexts":["1","2","3"],"goToLabel":"Q6"}]'
```

### 📊 报告生成
- **Excel 报告** — 带颜色编码的多 Sheet 专业检查报告

### 🔐 自动认证
- **Playwright 浏览器自动化** — 无需手动管理 Cookie
- 首次登录后自动保存 session，后续全自动

---

## 📖 使用方式

安装后，在你的 AI 编程助手中直接说：

| 场景 | 示例表达 |
|------|----------|
| 检查问卷 | "帮我检查问卷 91112"、"问卷有没有错别字？" |
| 自动修复 | "帮我修复所有问题"、"执行 autofix" |
| 复制问卷 | "复制国内问卷(91044)"、"基于上期问卷创建新版" |
| 录入题目 | "把这份题目清单录入问卷"、"导入 xxx.txt 到 91112" |
| 修改设置 | "帮我把 Q6 设为非必填"、"把所有'最近30天'改成'最近1个月'" |
| 设置逻辑 | "当 Q1 选了 1-3 分时显示 Q6" |

---

## 🔧 CLI 命令一览

| 命令 | 功能 | 示例 |
|------|------|------|
| `check` | 检查认证状态 | `py -3 survey_checker.py check` |
| `search` | 搜索问卷 | `py -3 survey_checker.py search --name "回流玩家"` |
| `fetch` | 抓取问卷内容 | `py -3 survey_checker.py fetch --id 91112` |
| `autofix` | R1-R6 自动扫描修复 | `py -3 survey_checker.py autofix --id 91112` |
| `modify` | 修改问卷设置 | `py -3 survey_checker.py modify --id 91112 --json '[...]'` |
| `copy` | 复制问卷 | `py -3 survey_checker.py copy --id 91044` |
| `import` | 从 txt 文件录入题目 | `py -3 survey_checker.py import --file "题目.txt" --id 91112` |
| `add` | 从 JSON 新增题目 | `py -3 survey_checker.py add --id 91112 --json @questions.json` |
| `logic` | 设置逻辑规则 | `py -3 survey_checker.py logic --id 91112 --json '[...]'` |

---

## 📄 题目文件格式

`import` 命令支持的标准 txt 格式：

```
6[量表题]您对这款游戏的满意度如何？
[提示文案]非常不满意//一般//非常满意
[评分]5星

7[多选题]您不满意的原因是？
选项A
选项B
其他
我没有不满意的地方

8[填空题]（非必填）您还有什么建议？

9[分页符]null

10[隐含问题]uid
[变量类型]1
[变量名称]uid
```

**支持题型**：量表题、矩形量表题、矩形单选题、多选题、单选题、填空题、多项填空题、分页符、描述说明、隐含问题

**自动应用规则**：解析时自动设置互斥/随机/布局/必填等，无需手动配置。

非标准格式（Word/Excel/对话文字）由 AI 智能解析后通过 `add` 命令录入。

---

## 📁 项目结构

```
survey-checker/
├── SKILL.md                  # AI 助手指令（工作流程 + R1-R6 规则引擎）
├── scripts/
│   ├── survey_checker.py     # 核心 Python 脚本（9 个 CLI 命令）
│   ├── generate_report.py    # Excel 报告生成器
│   └── requirements.txt      # Python 依赖
├── README.md
├── LICENSE
└── .gitignore
```

---

## 🔐 安全说明

- `config.json`（Cookie）和 `.browser_profile/`（浏览器 session）**不会上传到 GitHub**
- 首次使用时会打开浏览器窗口，登录后自动保存到本地
- 后续使用自动复用已保存的 session
- **修改前必须经用户确认**，save 后自动验证是否真正生效

---

## 📄 License

MIT