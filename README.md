# 量化研究 · A股尾盘启动隔夜策略扫描器

> 一个可长期维护的 A 股短线选股研究项目：在每个交易日尾盘（14:30~14:45）对给定股票池
> 做多因子综合评分，输出候选股、次日交易计划与 HTML 看板，并支持次日复盘。

---

## 1. 目录结构

```
量化研究/
├── README.md                      # 本文件：结构说明 + 使用 + Git 约定
├── .gitignore                     # 版本控制忽略规则
├── requirements.txt               # Python 依赖声明（本项目为零依赖）
│
├── src/                           # 源代码（Git 跟踪）
│   └── tail_momentum_selector.py  # 主程序：数据获取→因子→评分→报告→看板→复盘
│
├── data/                          # 输入数据（Git 跟踪）
│   └── universe/
│       └── demo_pool.txt          # 演示股票池（20 只，示例/回归验证用）
│
├── results/                       # 生成的结果文件（Git 跟踪，文件名带日期后缀）
│   ├── report_YYYY-MM-DD.txt      # 五段式文本报告
│   ├── dashboard_YYYY-MM-DD.html  # HTML 看板（自包含）
│   └── signals_YYYY-MM-DD.json    # 当日候选信号（供次日 --review 复盘）
│
├── cache/                         # 运行缓存（Git 忽略，可随时删除重建）
│
└── docs/                          # 文档（Git 跟踪）
    └── ARCHITECTURE.md            # 架构、数据流、评分模型、开发约定
```

### 各目录职责

| 目录 | 是否入 Git | 说明 |
|---|---|---|
| `src/` | ✅ 跟踪 | 全部源代码。新增模块（如独立回测、因子库）也放这里。 |
| `data/` | ✅ 跟踪 | 输入数据：股票池、行业映射等「人工维护/可复现」的数据。 |
| `results/` | ✅ 跟踪 | 每日运行产出，作为研究成果与复盘依据，长期留痕。 |
| `cache/` | ❌ 忽略 | CLI 原始输出缓存，纯中间产物，删了重跑即可重建。 |
| `docs/` | ✅ 跟踪 | 设计文档、方法论、变更记录。 |

---

## 2. 结果文件命名约定

**所有生成的结果文件都在文件名末尾附加当日日期后缀，格式 `YYYY-MM-DD`。**

| 文件 | 命名模式 | 示例 |
|---|---|---|
| 文本报告 | `report_<DATE>.txt` | `report_2026-09-14.txt` |
| HTML 看板 | `dashboard_<DATE>.html` | `dashboard_2026-09-14.html` |
| 信号文件 | `signals_<DATE>.json` | `signals_2026-09-14.json` |

- `<DATE>` 取**运行当日**的本地日期（`date.today()`）。
- 采用「基名 + 日期后缀」而非前缀，便于按类型分组、且复盘时用通配符 `signals_*.json` 取最近一份。
- 同一天重复运行会**覆盖**当天文件（这是有意为之：以当日最后一次运行为准）。如需保留多次，
  可传入不同 `--out-dir`，或后续扩展为带时分后缀。

---

## 3. Git 跟踪 / 忽略划分规则

### 3.1 纳入版本控制（tracked）

| 类别 | 具体 | 理由 |
|---|---|---|
| 源代码 | `src/**/*.py` | 工程主体，必须留痕。 |
| 输入数据 | `data/**` | 股票池等可复现输入。 |
| **结果文件** | `results/**` | 研究成果，纳入 Git 以便长期追溯每日信号与次日表现。 |
| 文档 | `README.md`、`docs/**`、`requirements.txt` | 说明与契约。 |
| 忽略规则自身 | `.gitignore` | 规则也是资产。 |

### 3.2 忽略（ignored，见 `.gitignore`）

| 类别 | 模式 | 说明 |
|---|---|---|
| 运行缓存 | `cache/`、`.cache*/`、`.westock_cache*/` | CLI 原始输出，可重建。 |
| Python 编译 | `__pycache__/`、`*.py[cod]` | 字节码，可重建。 |
| 虚拟环境 | `.venv/`、`venv/`、`env/` | 本地环境，不共享。 |
| 编辑器/系统 | `.vscode/`、`.idea/`、`.DS_Store`、`Thumbs.db` | 个人偏好/系统噪声。 |
| 工具状态 | `.workbuddy/` | 助手工作记忆，非项目产物。 |
| 临时/日志 | `*.tmp`、`*.log`、`~$*` | 临时文件。 |

**判断口诀**：*「删掉后能否由源码或已提交内容重建？」* —— 能重建 → 忽略；不能 → 跟踪。

---

## 4. 环境与运行

### 4.1 前置条件

- **Python 3.8+**（零第三方依赖，仅标准库）
- **Node.js 14+**：用于执行数据接口 CLI（`westock-data` / `westock-tool` 的 `scripts/index.js`）
- 数据 CLI 会被程序自动定位：环境变量 → `PATH` → 插件内置兜底路径；
  也可用 `--westock-cli` / `--westock-tool-cli` 手动指定。

### 4.2 常用命令（在项目根目录执行）

```bash
# ① 全流水线：初筛（westock-tool）+ 申万行业RS + HTML 看板（推荐日常用法）
python src/tail_momentum_selector.py --screen --snapshot 1430 --top 5

# ② 指定股票池
python src/tail_momentum_selector.py --universe data/universe/demo_pool.txt --snapshot 1430

# ③ 自定义初筛表达式
python src/tail_momentum_selector.py --screen \
    --screen-expr "intersect([ChangePCT >= 3, ChangePCT <= 6, TotalMV > 10000000000])" \
    --screen-limit 80

# ④ 次日复盘（自动取 results/ 下最近一份信号文件）
python src/tail_momentum_selector.py --review
```

产物默认写入 `results/`，缓存默认写入 `cache/`。两者都可用 `--out-dir` / `--cache-dir` 覆盖。

### 4.3 关键参数速查

| 参数 | 默认 | 说明 |
|---|---|---|
| `--codes` | 空 | 逗号分隔代码，如 `sh600519,sz000858` |
| `--universe` | 空 | 股票池文件（每行一个代码） |
| `--screen` | 关 | 先跑 westock-tool 初筛，再扫描候选 |
| `--screen-expr` | 内置 | 初筛表达式 |
| `--screen-limit` | 50 | 初筛返回上限 |
| `--snapshot` | `1430` | 决策时刻 `HHMM`（只用到该时刻及之前的数据） |
| `--top` | 5 | 最多推荐数量 |
| `--no-industry-rs` | 关 | 关闭申万行业实时相对强弱 |
| `--no-html` | 关 | 不生成 HTML 看板 |
| `--out-dir` | `results/` | 结果输出目录 |
| `--cache-dir` | `cache/` | 原始 CLI 输出缓存目录 |
| `--review` | 关 | 复盘模式 |
| `--review-file` | 空 | 指定复盘的 signals JSON（默认取最近） |

---

## 5. 每日工作流建议

```bash
# 14:30~14:45 之间（或收盘后回放当天）
python src/tail_momentum_selector.py --screen --snapshot 1430 --top 5
#   → 生成 results/{report,dashboard,signals}_<今天>.txt/.html/.json

# 提交当日成果
git add results/ && git commit -m "results: 2026-09-14 尾盘扫描（N 只候选）"

# 次日复盘
python src/tail_momentum_selector.py --review
```

---

## 6. 重要声明

- 本策略属**短线高风险**策略，A 股 T+1 限制下当日买入次日才能卖出；隔夜存在跳空风险。
- 程序严格遵守**防未来函数**：决策只用 `--snapshot` 时刻及之前的数据，绝不使用当日最终收盘价或次日数据。
- 报告中的「次日上涨概率」为**基于规则的主观估计，并非历史统计概率**；回测/历史统计不代表未来收益。
- 输出仅为研究结果，**不构成任何投资建议或个股推荐**。

> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
