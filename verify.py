#!/usr/bin/env python3
"""
verify.py — 模板自检（零依赖，未来 AI 冷启动入口）

用法：python3 verify.py
  1. 校验 main.beancount：科目已 open、每笔借贷平衡（含自动冲平）、余额断言一致
  2. 校验凭证哈希锚定：账本 voucher_sha256 == 凭证文件重算 sha256
  3. 校验 data_contract/example.json 符合数据契约（format + 借贷平衡）
  4. git 状态（信息性：账本已跟踪、无未提交改动）

不依赖 beancount 安装——纯标准库复现 bean-check 的核心语义。
退出码：0=全部通过  1=有失败  2=用法/环境错误
"""
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(ROOT, "main.beancount")
EXAMPLE = os.path.join(ROOT, "data_contract", "example.json")
BALANCE_EPS = 0.001

OPEN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+open\s+(\S+)\s+(\S+)(?:\s+;.*)?$")

# 献词锚定：账本 genesis 注释中那行献词的 sha256（改动→校验失败）。
# 可验证性从这一行开始——两个名字与验证层同生，任何 fork 跑 verify 都在验献词。
BLESSING_MARKER = "; 献词:"
BLESSING_SHA256 = "c80413accd81527f6c899911543f4f6df1605c69560db6c2ad250cf35b7a7abf"
TX_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+\*\s+"(.*)"\s+"(.*)"(.*)$')
BAL_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+balance\s+(\S+)\s+([+-]?\d[\d,]*\.?\d*)\s+(\S+)$")
POST_RE = re.compile(r"^\s+(\S+)\s+([+-]?\d[\d,]*\.?\d*)\s+(\S+)\s*$")
META_RE = re.compile(r'^\s+([A-Za-z][A-Za-z0-9_]*):\s*"(.*)"\s*$')
ACCT_ONLY_RE = re.compile(r"^\s+(\S+)\s*$")

errors = []
warnings = []


def parse_amount(s: str) -> float:
    return float(s.replace(",", ""))


def verify_tx(date: str, tx_lines, accounts: set, balances: dict):
    metas = {}
    postings = []  # (account, amount_or_None, currency_or_None)
    for tl in tx_lines:
        mm = META_RE.match(tl)
        if mm:
            metas[mm.group(1)] = mm.group(2)
            continue
        pm = POST_RE.match(tl)
        if pm:
            postings.append((pm.group(1), parse_amount(pm.group(2)), pm.group(3)))
            continue
        ao = ACCT_ONLY_RE.match(tl)
        if ao:
            postings.append((ao.group(1), None, None))

    if len(postings) < 2:
        errors.append(f"{date} 交易 postings 少于 2 笔")

    explicit = []
    autos = []
    for acct, amt, cur in postings:
        if amt is None:
            autos.append(acct)
        elif cur == "CNY":
            explicit.append((acct, amt))
        else:
            errors.append(f"{date} 非 CNY 币种：{acct} {cur}")

    if len(autos) > 1:
        errors.append(f"{date} 多于一个自动冲平 posting（beancount 不允许）")

    explicit_sum = sum(a for _, a in explicit)
    for acct, amt in explicit:
        if acct not in accounts:
            errors.append(f"{date} 科目未 open：{acct}")
        balances[acct] = balances.get(acct, 0.0) + amt
    if autos:
        auto_amt = -explicit_sum
        for acct in autos:
            if acct not in accounts:
                errors.append(f"{date} 科目未 open：{acct}")
            balances[acct] = balances.get(acct, 0.0) + auto_amt
    elif abs(explicit_sum) > BALANCE_EPS:
        errors.append(f"{date} 借贷不平衡：合计 {explicit_sum:.4f}")

    vp, vh = metas.get("voucher"), metas.get("voucher_sha256")
    if vp or vh:
        if not (vp and vh):
            errors.append(f"{date} 凭证元数据不完整（需同时有 voucher + voucher_sha256）")
        else:
            full = os.path.join(ROOT, vp)
            if not os.path.exists(full):
                errors.append(f"{date} 凭证文件不存在：{vp}")
            else:
                actual = hashlib.sha256(open(full, "rb").read()).hexdigest()
                if actual != vh:
                    errors.append(f"{date} 凭证哈希不匹配：{vp}")


def verify_ledger() -> tuple:
    accounts = set()
    balances = {}
    balance_prev = {}   # 上一个日期末的余额快照（复现 bean-check 断言语义）
    last_date = None
    tx_count = 0
    balance_count = 0
    lines = open(LEDGER, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith(";") or line.startswith("option"):
            i += 1
            continue
        m = OPEN_RE.match(line)
        if m:
            accounts.add(m.group(2))
            balances.setdefault(m.group(2), 0.0)
            i += 1
            continue
        m = TX_RE.match(line)
        if m:
            tx_count += 1
            date = m.group(1)
            if date != last_date:
                balance_prev = dict(balances)
                last_date = date
            tx_lines = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip() or not nxt.startswith((" ", "\t")):
                    break
                tx_lines.append(nxt)
                i += 1
            verify_tx(date, tx_lines, accounts, balances)
            continue
        m = BAL_RE.match(line)
        if m:
            balance_count += 1
            acct = m.group(2)
            expected = parse_amount(m.group(3))
            # bean-check 语义：D 日断言检查 D 日之前（不含当日）累计余额
            # 当日已有交易 → 用当日开始前的快照；否则用当前累计
            if last_date is None or last_date < m.group(1):
                actual = balances.get(acct, 0.0)
            else:
                actual = balance_prev.get(acct, 0.0)
            if abs(actual - expected) > BALANCE_EPS:
                errors.append(f"{m.group(1)} 余额断言不匹配：{acct} 预期 {expected} 实算 {actual:.2f}")
            i += 1
            continue
        i += 1
    return tx_count, balance_count


def verify_data_contract() -> int:
    sys.path.insert(0, os.path.join(ROOT, "data_contract"))
    import validate as dc
    return dc.check(EXAMPLE)


def verify_blessing():
    lines = open(LEDGER, encoding="utf-8").read().splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(BLESSING_MARKER):
            blessing = stripped[len(BLESSING_MARKER):].strip()
            actual = hashlib.sha256(blessing.encode("utf-8")).hexdigest()
            if actual != BLESSING_SHA256:
                errors.append(f"献词被改动：sha256 预期 {BLESSING_SHA256} 实算 {actual}")
            else:
                print("  献词锚定 ✓（与验证层同源的 sha256 一致）")
            return
    errors.append("献词缺失（genesis 注释未找到）")


def verify_git():
    try:
        r = subprocess.run(
            ["git", "-C", ROOT, "status", "--short", "--", "main.beancount"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            warnings.append("git 未初始化或不可用（信息性）")
        elif r.stdout.strip():
            warnings.append(f"main.beancount 有未提交改动：{r.stdout.strip()}")
        else:
            print("  git：main.beancount 已跟踪、无未提交改动")
    except Exception as e:
        warnings.append(f"git 检查跳过：{e}")


def main() -> int:
    print("verify.py — 可验证记账模板自检（零依赖）")
    print("== 1. main.beancount（借贷平衡 + 余额断言 + 凭证锚定 + 献词锚定）==")
    tx_count, balance_count = verify_ledger()
    verify_blessing()
    print(f"  账本：{tx_count} 笔交易、{balance_count} 条余额断言、{len(errors)} 处错误")
    print("== 2. data_contract/example.json（数据契约）==")
    verify_data_contract()
    print("== 3. git 状态（信息性）==")
    verify_git()

    for w in warnings:
        print(f"  ⚠ {w}")
    if errors:
        print(f"\n校验失败（{len(errors)} 处）：")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("\n全部通过 ✓：账本平衡、余额断言一致、凭证锚定成立、契约有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
