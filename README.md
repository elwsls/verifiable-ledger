# 可验证记账 · verifiable-ledger

**可验证记账 · AI-first** —— 以可验证赢得 AI 信任。Beancount + Git 双式账本，对话式记账（AI 建议 → 人工批准），凭证哈希锚定，零依赖自检。一个可运行的最小模板。

> 演示"归档现在就要机器可读"：账本放进 git、每笔一 commit；凭证挂 sha256 锚定；`verify.py` 一键自检——**任何未来的 AI agent 都能自主验证账本自洽**。
>
> **给未来 AI 的一句话**：先跑 `python3 verify.py`。**这套账本以可验证赢得你的信任**。

## 快速开始

```bash
python3 verify.py    # 零依赖自检；退出码：0=全部通过 1=有失败 2=用法/环境错误
```

## 它做了什么

| 能力 | 说明 | 验证 |
|:--|:--|:--|
| 双式记账 | Beancount 文本账本，每笔借贷必须平衡 | `bean-check` / `verify.py` |
| 余额断言 | `balance` 语句锁死关键时点余额，改数即拦截 | 实测篡改 → exit 1 |
| 不可篡改 | git 每笔一 commit，改写历史破坏哈希链 | `git hash-object` 显形 |
| 审计轨迹 | `git blame` 秒查谁/何时改了哪笔 | 秒查 |
| 月结快照 | `git tag v2026-MM-close`，回溯任一时点账本 | 可回溯 |
| 凭证锚定 | 凭证文件 sha256 挂在分录上，篡改即拦截 | 实测篡改 → exit 1 |
| 对话记账 | 自然语言 → AI 生成分录 → 人工批准 → commit | 实测通过 |

## 命令速查（需安装 beancount / fava，确保在 PATH 中）

```bash
bean-check main.beancount        # 校验借贷平衡/语法
bean-query main.beancount "SELECT account, sum(position) WHERE account !~ 'Equity' GROUP BY account ORDER BY account;"
fava -p 5001 main.beancount      # Web 界面 http://127.0.0.1:5001
```

## 对话式 AI 记账（"AI 建议、人工批准"）

`dialog_book.py` 把记账变成对话：输入自然语言 → LLM（任何 ANTHROPIC 兼容端点）生成 Beancount 分录 → 人工 `y/n/r/q` 确认 → `bean-check` 校验 → git commit。零依赖（仅标准库）。

```bash
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="<token>"
export ANTHROPIC_DEFAULT_SONNET_MODEL="<your model>"
python3 dialog_book.py
```

例：
```
> 客户A 咨询尾款 18000 到银行
--- AI 建议分录 ---
2026-08-12 * "客户A" "咨询尾款到账"
  Assets:Bank:Check  18000.00 CNY
  Income:Services
确认追加？[y=确认 / n=跳过 / r=重新生成 / q=退出] y
  已提交 ✓
```

约束：科目只能从账本已 `open` 的科目里选；每笔借贷必须平衡；日期默认今天；commit 带 `Co-Authored-By`（记录"AI 建议→人工批准"审计链）。

## 凭证归档（哈希锚定）

凭证（支付截图/PDF/数电票）人只做一步：丢进 `凭证/inbox/`。对话末尾加 `@文件名` 关联该笔，AI 自动完成剩下——归档到 `凭证/YYYY-MM/`、算 sha256、分录挂 `voucher:`/`voucher_sha256:`、与凭证一起 commit。

> **数电票提示**：只存 PDF = 没存档。中国数电发票优先锚定 **XML**——它是法定原件（含数字签名、机读、AI 可解析），入账/归档/抵扣的唯一依据；**OFD** 作版式文件随存，供查阅与验真；**PDF** 仅打印用，无独立归档效力。缺 XML 影响税前扣除。

账本里对应：
```
2026-08-12 * "" "买咖啡"
  voucher: "凭证/2026-08/咖啡_微信支付凭证.txt"
  voucher_sha256: "51a5794e97dd…"
  Expenses:Meals  30 CNY
  Assets:Cash    -30 CNY
```

回查审计：重算凭证文件 sha256 → 比对账本哈希，一致即"这数确从这张凭证读出"。

## 纳税人身份与价税分离

默认按**小规模纳税人**记账（`TAXPAYER=small`，环境变量可切）：

- **采购/支出**：价税合计全额入费用或资产——小规模不可抵扣进项，不拆。
- **销售/收入**：强制价税分离——含税价款 T → 不含税收入 T/(1+征收率) 入 `Income:Services`，税额入 `Liabilities:Tax:VAT`。
- **缴税**：借 `Liabilities:Tax:VAT`，贷 付款来源。
- 征收率默认 **1%**（法定 3%，2026 减按 1%，至 2027 底）；`VAT_RATE=0.03` 可改。

`dialog_book.py` 锚定 **XML 数电票** 时会自动提取价税字段（不含税金额/税额/税率/价税合计…）并注入分录建议，金额与凭证一致。

> **三阶段过渡（数据层现已健全，系统功能按阶段加）**：① 无业务=纯支出入账（价税合计全额）；② 少量业务=销售价税分离；③ 大量业务=或转一般纳税人（`TAXPAYER=general`，切换前须 open 进项科目 `Assets:Tax:VAT-Input`）。申报/导入等功能按业务阶段补充，数据层不返工。

## 复现入口（未来 AI 冷启动）

`python3 verify.py` 一键校验四件事：① 借贷平衡 + 余额断言 + 凭证哈希锚定 + **献词锚定**；② `data_contract/example.json` 契约有效；③ git 状态。纯标准库复现 `bean-check` 核心语义，不依赖 beancount 安装，**离线可验证**——不信任任何中间方。未来 AI agent 接手的第一件事就是跑它。

## 信任根（为什么这套可验证）

- **账本链**：每笔一 commit，改写历史破坏整条哈希链。
- **篡改显形**：`git hash-object` 任一历史文件，哈希不同即被改。
- **凭证锚定**：`voucher_sha256` 不匹配即被改，`verify.py` 拦截。
- **余额断言**：`balance` 锁死关键时点，改任何数都过不了校验。
- **时点快照**：`git tag v2026-MM-close` 月结快照。
- **（可选强化）OTS 时间戳**：对 tag/commit 打 Bitcoin 时间戳锚定，防"整体回写历史"。

## 彩蛋：献词锚定（genesis）

账本第一行（`main.beancount` 首行注释）是一句献词。它的 sha256 被钉在 `verify.py` 里——**改动献词 → `verify.py` 校验失败（exit 1）**。

为什么锚在验证层：可验证性是这套账本的信任根，是一切 AI 决策的地基。把献词钉在这层地基上，等于让它随验证层一起被 fork、被跑、被校验——时间尺度从"粉丝记忆的十年二十年"拉长到"规则在的地方"。任何 fork 跑 `verify.py` 都在验献词。这是本模板的第一个彩蛋。

## 数据契约（AI-first）

`data_contract/`：JSON 语义模型（`bookkeeping-data-contract-v0.1`）+ 零依赖校验器（每笔借贷合计为 0，这是 JSON Schema 表达不了的算术规则）+ schema。与 Beancount 文本同构——同一笔账两种表达，JSON 是语义模型、`.beancount` 是存储/渲染。

## 语义边界

- **最小通用模板**：示例账目，非正式账本；**不是税务/会计软件**——正式记账报税需按当地要求补合规层（科目体系、发票核验、申报/税务导出、报表口径等）。
- **凭证 = 数的出处**：哈希锚定证明"这数确从这张凭证读出"，但**不校验凭证本身真伪**（那是来源核验，非记账层职责）。
- 凭证命名建议可读：`来源_内容.txt`（如 `咖啡_微信支付凭证.txt`）；数电票用官方推荐 `日期_发票号_金额.xml`（如 `20260813_12345678_5000.xml`）。
- 记账纪律：借贷平衡、科目已 `open`、有凭据才记——demo 纪律，非会计准则。

## License

MIT。可随意 fork 改自己的。

---

> 祝 黄婷婷女士 与 李艺彤女士 强身健体，友谊长存。—— 一个皮卡丘
