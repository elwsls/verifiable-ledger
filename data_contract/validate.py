#!/usr/bin/env python3
"""
validate.py — 记账 AI-first 数据契约校验器（零依赖）

用法：python3 validate.py example.json
校验：
  1. 科目名合法、type 合法、open/close 日期格式
  2. 每笔交易 ≥2 笔 postings，科目均已声明且当日已 open
  3. 每笔交易借贷合计为 0（双式平衡，JSON Schema 无法表达的算术规则）
退出码：0=通过  1=校验失败  2=用法错误
"""
import json
import re
import sys

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ACCOUNT_RE = re.compile(r"^[A-Z][A-Za-z-]*(:[A-Za-z][A-Za-z-]*)*$")
VALID_TYPES = {"asset", "liability", "equity", "income", "expense"}


def check(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"无法读取 {path}: {e}")
        return 2

    errors = []
    if data.get("format") != "bookkeeping-data-contract-v0.1":
        errors.append("format 必须为 bookkeeping-data-contract-v0.1")
    if data.get("currency") != "CNY":
        errors.append("currency 必须为 CNY")

    accounts = data.get("accounts", {})
    for name, spec in accounts.items():
        if not ACCOUNT_RE.match(name):
            errors.append(f"科目名非法: {name}")
        if spec.get("type") not in VALID_TYPES:
            errors.append(f"科目 {name} type 非法: {spec.get('type')}")
        for k in ("open_date", "close_date"):
            v = spec.get(k)
            if v and not DATE_RE.match(v):
                errors.append(f"科目 {name} {k} 非日期: {v}")

    for i, tx in enumerate(data.get("transactions", [])):
        tx_date = tx.get("date", "")
        if not DATE_RE.match(tx_date):
            errors.append(f"交易[{i}] date 非法: {tx_date}")
        postings = tx.get("postings", [])
        if len(postings) < 2:
            errors.append(f"交易[{i}] postings 少于 2 笔")
        total = 0.0
        for p in postings:
            acct = p.get("account")
            if acct not in accounts:
                errors.append(f"交易[{i}] 科目未声明: {acct}")
            else:
                open_d = accounts[acct].get("open_date", "0001-01-01")
                close_d = accounts[acct].get("close_date") or "9999-12-31"
                if not (open_d <= tx_date <= close_d):
                    errors.append(f"交易[{i}] 科目 {acct} 在 {tx_date} 未 open")
            if not isinstance(p.get("amount"), (int, float)):
                errors.append(f"交易[{i}] {acct} 金额非数字")
            if p.get("currency") != "CNY":
                errors.append(f"交易[{i}] {acct} 币种非法")
            total += p.get("amount", 0)
        if abs(total) > 0.001:
            errors.append(f"交易[{i}] 借贷不平衡: 合计 {total:.4f}")

    if errors:
        print(f"校验失败（{len(errors)} 处）:")
        for e in errors:
            print("  -", e)
        return 1
    n_tx = len(data.get("transactions", []))
    print(f"通过：{n_tx} 笔交易、{len(accounts)} 个科目，借贷均平衡。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python3 validate.py <ledger.json>")
        sys.exit(2)
    sys.exit(check(sys.argv[1]))
