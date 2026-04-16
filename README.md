# 📋 Survey Checker

> 网易问卷（国内 survey-game.163.com / 国外 survey-game.easebar.com）全流程自动化管理 AI Skill

一个 [Agent Skills](https://github.com/anthropics/courses/tree/master/tool_use) 格式的 AI 编程助手技能，覆盖问卷从**复制 → 录入 → 校准 → 检查 → 修复 → 报告**的完整生命周期。支持**国内 / 海外双平台**，统一接口，一键切换。

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

按键盘 `Win + R`，输入 `cmd`，按回车。

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

### � 问卷复制 & 题目录入
- **一键复制** — 基于已有问卷快速克隆，支持自定义名称
- **标准格式导入** — txt/md 标准格式文件自动解析，无需人工干预
- **AI 智能解析** — 任意格式（Word / Excel / 对话文字 / 截图）由 AI 理解后自动生成题目结构
- **全题型覆盖** — 单选 / 多选 / 填空 / 量表 / 矩阵量表 / 矩阵单选 / 说明 / 分页 / 隐含题
- **规则自动应用** — 录入时自动按 R1-R8 规则设置互斥、随机、布局、必填等
- **逻辑规则配置** — 用题号标签或题目标题设置显示/跳转逻辑

### 🔧 一键校准（calibrate）— R1-R8 规则引擎

扫描问卷并**自动修复**常见设置问题，一条命令搞定：

| 规则 | 检查内容 | 自动修复 |
|------|----------|:---:|
| **R1** | 多选题布局：≥8 选项 → 2 列，≥20 选项 → 3 列 | ✅ |
| **R2** | 多选题选项全部随机 + "其他"/互斥项固定不随机 | ✅ |
| **R3** | 排他选项（"以上都没有"等）→ 互斥 | ✅ |
| **R4** | 文本/填空题 → 非必填 | ✅ |
| **R5** | 从属关系题（评分→追问）→ 检查显示逻辑 | ⚠️ 仅报告 |
| **R6** | 非文本题 → 必填（尊重"非必填"标注） | ✅ |
| **R7** | 矩阵题子问题末尾异常标点 → 自动去除 | ✅ |
| **R8** | "其他"选项 → 自动开启输入框 (`hasOther=1`) | ✅ |

### � 三维度质量检查
- **错别字检查** — 逐题扫描错别字、同音字混淆、标点错误、格式不一致
- **逻辑检查** — 互斥设置、必填一致性、跳转逻辑、选项区间重叠、量表方向一致性
- **设计专业性评估** — 问卷长度、题目措辞、量表设计、人口学题位置、矩阵题拆分建议

### ✏️ 精确修改
- **题目级设置** — 修改 required / random / layout / randomColumn / title 等
- **选项级设置** — 修改 mutex / noRandom / hasOther / hidden 等
- **批量修改** — 一次修改多道题目，JSON 格式传入
- **修改后自动验证** — 保存后等待缓存刷新，重新拉取数据验证修改是否真正生效

### 📊 报告生成
- **Excel 报告** — 多 Sheet 结构化报告（总览 / 错别字 / 逻辑 / 设计 / 问卷原文）

### 🔐 自动认证
- **Playwright 浏览器自动化** — Cookie 过期自动弹出浏览器续期
- 首次登录后自动保存 session，后续全自动无需人工操作

---

## 📖 使用方式

安装后，在你的 AI 编程助手中直接说：

| 场景 | 示例表达 |
|------|----------|
| 检查问卷 | "帮我检查问卷 91112"、"问卷有没有错别字？" |
| 一键校准 | "校准 91112"、"calibrate 91112" |
| 复制问卷 | "复制问卷 91044"、"基于上期问卷创建新版" |
| 复制+录入 | "复制 91278 并上传 xxx.md" |
| 录入题目 | "把这份题目清单录入问卷"、"导入 xxx.txt 到 91112" |
| 修改设置 | "把 Q4 设为子问题随机"、"把 Q6 设为非必填" |
| 设置逻辑 | "当 Q1 选了 1-3 分时显示 Q6" |
| 清空题目 | "清空 91112 的所有题目" |

### 典型工作流

```
1. 复制模板问卷           →  "复制 91278 问卷"
2. 清空并录入新题目        →  "上传 xxx.md"
3. 自动校准设置           →  （录入完成后自动执行 calibrate）
4. 检查问卷质量           →  "帮我检查一下这份问卷"
5. 按需微调               →  "把 Q9 设为子问题随机"
6. 生成报告               →  "生成检查报告"
```

---

## 🔧 CLI 命令一览

所有命令均支持 `--platform` / `-p` 参数切换平台（默认 `cn`）：

```bash
# 国内平台（默认）
python survey_checker.py fetch --id 91112

# 海外平台
python survey_checker.py -p global fetch --id 44583
```

| 命令 | 功能 | 示例 |
|------|------|------|
| `check` | 检查认证状态 | `survey_checker.py check` |
| `search` | 搜索问卷 | `survey_checker.py search --name "回流玩家"` |
| `fetch` | 抓取问卷完整内容 | `survey_checker.py fetch --id 91112` |
| `copy` | 复制问卷 | `survey_checker.py copy --id 91044 --name "新版本"` |
| `create` | 创建空白问卷 | `survey_checker.py create --name "新问卷" --game "游戏名"` |
| `clear` | 清空问卷题目 | `survey_checker.py clear --id 91112 [--keep-imply]` |
| `import` | 从 txt/md 文件录入 | `survey_checker.py import --file "题目.md" --id 91112` |
| `add` | 从 JSON 新增题目 | `survey_checker.py add --id 91112 --json @questions.json` |
| `calibrate` | R1-R8 自动校准修复 | `survey_checker.py calibrate --id 91112 [--dry-run]` |
| `autofix` | calibrate 的别名 | `survey_checker.py autofix --id 91112` |
| `modify` | 修改问卷设置 | `survey_checker.py modify --id 91112 --json '[...]'` |
| `logic` | 设置逻辑规则 | `survey_checker.py logic --id 91112 --json '[...]'` |
| `style` | 文本样式标红 | `survey_checker.py style --id 91112 --red [--dry-run]` |

> 💡 所有写入操作（modify / calibrate / import / add / clear）执行前会自动锁定问卷，保存后自动验证。如果浏览器编辑器正在打开，需要先关闭才能执行。

---

## 📄 题目文件格式（标准格式 v2.0）

`import` 命令支持的标准 txt/md 格式。文件可包含 `[问卷标题]`/`[问卷说明]` 头部和 `[跳转逻辑]` 块：

```
[问卷标题]《我的世界》满意度调研
[问卷说明]感谢您参与本次调研！

1[隐含问题]uid（请务必确认app端拼接了相应参数）
[变量类型]1
[变量名称]uid

2[量表题]您对这款游戏的满意度如何？
[提示文案]非常不满意//一般//非常满意
[评分]5星
[跳转逻辑]
当 评分 1-3 分 → 显示 Q3
当 评分 4-5 分 → 显示 Q4

3[填空题]（非必填）您不满意的主要原因是？

4[多选题]您满意的方面有哪些？（可多选）
选项A
选项B
其他
以上都没有

5[矩形量表题]您对以下方面的满意度如何？
[提示文案]非常不满意//一般//非常满意
[评分]5星
子问题1
子问题2
子问题3

6[单选题]您是否参与过本次活动？
是
否
没有关注

7[分页符]null
```

**支持题型**：量表题、矩形量表题、矩形单选题、多选题、单选题、填空题、多项填空题、分页符、描述说明、隐含问题

**跳转逻辑语法**（`[跳转逻辑]` 块，写在题目末尾）：
- `当 <条件> → 显示 <Q编号>` — 满足条件时显示目标题
- `当 <条件> → 跳转到 <Q编号>` — 满足条件时跳转到目标题
- `当 <条件> → 结束问卷` — 满足条件时结束问卷
- 支持 `→` 和 `->` 两种箭头

**录入时自动应用规则**：
- 多选题自动设置 `random=1`（选项随机）
- "其他"选项自动设置 `hasOther=1`（开启输入框）+ `noRandom=1`（固定位置）
- 排他选项自动设置 `mutex=1` + `noRandom=1`
- ≥8 选项设 2 列布局，≥20 选项设 3 列布局（layout + maxRow 同步）
- 填空题自动 `required=0`，其他题型自动 `required=1`
- 矩阵题子问题末尾多余标点自动去除

**格式转化工具**：非标准格式（Excel / 无结构 txt 等）可通过 `convert_to_standard.py` 读取后由 AI 转化为标准格式再录入。

---

## 📁 项目结构

```
survey-checker/
├── SKILL.md                       # AI 助手指令（工作流程 + R1-R8 规则引擎）
├── scripts/
│   ├── survey_checker.py          # 薄入口（CLI + SurveyChecker 包装类）
│   ├── convert_to_standard.py     # 格式转化工具（任意文件 → 标准格式上下文）
│   ├── generate_report.py         # Excel 报告生成器
│   ├── requirements.txt           # Python 依赖
│   │
│   ├── core/                      # 基础层
│   │   ├── constants.py           #   平台配置、API 端点常量
│   │   ├── utils.py               #   日志、HTML 清理、ID 生成等通用工具
│   │   ├── auth.py                #   Cookie 加载/保存/检查/Playwright 自动刷新
│   │   └── client.py              #   HTTP Session 工厂（自动加载 Cookie）
│   │
│   ├── survey_io/                 # IO 层
│   │   ├── fetcher.py             #   问卷搜索、数据抓取、结构化输出
│   │   └── importer.py            #   txt/md 标准格式文件 → 题目 spec 解析
│   │
│   └── operations/                # 业务操作层
│       ├── builder.py             #   题目对象构建（全题型支持）
│       ├── survey_ops.py          #   问卷 CRUD（复制/创建/锁定/保存）
│       ├── question_ops.py        #   题目增删改（清空/新增/批量修改）
│       ├── logic_ops.py           #   显示逻辑规则设置
│       └── calibrate.py           #   R1-R8 规则扫描 + 自动修复引擎
│
├── README.md
├── LICENSE
└── .gitignore
```

### 架构设计

采用**职责分层**架构，三层之间单向依赖：

```
Operations（业务操作）  ──依赖──→  IO（数据读写）  ──依赖──→  Core（基础设施）
```

- **Core 层**：不依赖任何上层模块，提供认证、HTTP、工具函数
- **IO 层**：只依赖 Core 层，负责问卷数据的读取和文件解析
- **Operations 层**：依赖 Core + IO 层，实现所有业务逻辑

入口文件 `survey_checker.py` 是一个**薄包装**（~240 行），通过 `SurveyChecker` 类将所有子模块的函数式 API 封装为面向对象接口，保持向后兼容。

---

## 🌐 双平台支持

| 平台 | 地址 | CLI 参数 | Cookie 配置 |
|------|------|----------|-------------|
| 🇨🇳 国内 | survey-game.163.com | `-p cn`（默认） | `config.json` |
| 🌍 海外 | survey-game.easebar.com | `-p global` | `config_global.json` |

两个平台使用**独立的 Cookie 和浏览器 Profile**，互不干扰。代码逻辑完全共用，仅通过 `constants.py` 中的 `PLATFORMS` 配置区分。

---

## 🔐 安全说明

- `config.json` / `config_global.json`（Cookie）和 `.browser_profile*`（浏览器 session）**不会上传到 GitHub**
- 首次使用时会打开浏览器窗口，登录后自动保存到本地
- 国内和海外平台使用**独立的 Cookie 文件和浏览器 Profile**，互不影响
- 后续使用自动复用已保存的 session，Cookie 过期时自动续期
- **所有写入操作前必须经用户确认**，保存后自动验证是否真正生效

---

## 📄 License

MIT