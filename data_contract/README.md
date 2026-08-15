# data_contract/ — 记账 AI-first 数据契约（最小骨架 v0.1）

> 设计：复式记账数据契约（schema + 借贷校验规则）。与 Beancount 文本账本**同构**——同一笔账两种表达，JSON 是语义模型，`.beancount` 是存储/渲染。

## 文件

| 文件 | 作用 |
|:--|:--|
| `schema.json` | JSON Schema（draft 2020-12）：科目 / 凭证 / 复式记账结构声明化，任何 JSON Schema 工具可机器校验 |
| `validate.py` | 零依赖校验器：科目已声明且当日 open、每笔借贷合计为 0（求和是 JSON Schema 表达不了的算术规则） |
| `example.json` | 实例账本：期初 + 一月 5 笔，数字与 `main.beancount` 一月一致 |

## 用法

```bash
python3 validate.py example.json     # 通过 → 退出码 0
python3 validate.py <坏文件.json>    # 失败 → 退出码 1（逐条列出违规）
```

## 契约规则（借贷校验）

1. 顶层必须有 `"format": "bookkeeping-data-contract-v0.1"` 与 `"currency": "CNY"`（格式与币种锁死）。
2. 科目命名 `Assets:Bank:Check` 式，type ∈ asset/liability/equity/income/expense。
3. 每笔交易 ≥2 笔 postings，且引用科目必须已声明、当日已 open。
4. **每笔交易借贷合计必须为 0**（双式平衡）——即 Beancount 的 `bean-check` 语义。

## 与模板自检集成

根目录 `verify.py` 会通过 `sys.path` 引入本目录 `validate.py` 校验 `example.json`，作为模板冷启动自检的第 2 步（契约有效）。改契约结构时，`schema.json`（结构）+ `validate.py`（算术）两份要同步改。

## 与账本的分层关系

- **账本本体 = JSON 语义模型** ← `schema.json` + `example.json`（机器可精确消费、可校验）
- **存储/合规出口** ← `.beancount` 文本 + `bean-check`（现值；未来可补 XBRL/税务导出）
- **人读层** ← Fava Web / md 渲染（永不反向写回）

示例等价对照（同一笔，两种表达）：

```text
# main.beancount
2026-01-05 * "客户A" "咨询项目一期款"
  Assets:Bank:Check        20000.00 CNY
  Income:Services
```

```json
{ "date": "2026-01-05", "payee": "客户A", "narration": "咨询项目一期款",
  "postings": [
    { "account": "Assets:Bank:Check", "amount": 20000, "currency": "CNY" },
    { "account": "Income:Services", "amount": -20000, "currency": "CNY" } ] }
```
