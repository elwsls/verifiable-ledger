#!/usr/bin/env python3
"""
dialog_book.py — 对话式 AI 记账（"AI 建议、人工批准"工作流）

用法：python3 dialog_book.py [账本文件]
  默认账本：同目录 main.beancount

流程：
  1. 输入自然语言记账描述（如 "客户A 咨询尾款 18000 到银行")
  2. 调 LLM 生成 Beancount 分录建议（AI 只建议）
  3. 显示分录 → 人工确认 y/n（含金额/科目/日期修正提示）
  4. 确认后：bean-check 校验 → 追加到账本 → git commit
  5. 输入 q 退出

零依赖（仅标准库）。LLM 走 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN 兼容端点。
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

LEDGER = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.beancount")
VOUCHER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "凭证")
INBOX_DIR = os.path.join(VOUCHER_DIR, "inbox")

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic").rstrip("/")
AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
MODEL = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "deepseek-v4-flash")
MAX_RETRY = 2

# 纳税人身份与征收率：small=小规模（当前）；general=一般纳税人（切换前须 open 进项科目 Assets:Tax:VAT-Input）
TAXPAYER = os.environ.get("TAXPAYER", "small")
# 小规模征收率：法定 3%，2026 减按 1%（政策至 2027 底）；可配 VAT_RATE=0.03
VAT_RATE = float(os.environ.get("VAT_RATE", "0.01"))


def call_llm(system: str, user: str) -> str:
    """调用 Anthropic 兼容 Messages API，返回 assistant 文本。"""
    body = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{BASE_URL}/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": AUTH_TOKEN,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return "".join(block.get("text", "") for block in data.get("content", []))


def ledger_accounts() -> str:
    """提取账本中已声明的科目列表（供 LLM 参考，避免乱造科目）。"""
    accts = []
    for line in open(LEDGER, encoding="utf-8"):
        line = line.strip()
        if re.match(r"\d{4}-\d{2}-\d{2} open\s", line):
            accts.append(line.split("open")[1].strip().split()[0])
    return "\n".join(accts)


def extract_code_block(text: str) -> str:
    """从 LLM 回复中提取 beancount 代码块（```beancount 或裸分录）。"""
    m = re.search(r"```(?:beancount)?\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    return text.strip()


def validate_balances(entries: str) -> bool:
    """校验分录文本每笔借贷合计为 0（简易解析）。返回 True 若平衡。"""
    for block in entries.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        date = re.match(r"(\d{4}-\d{2}-\d{2})\s*\*", block)
        if not date:
            continue
        amounts = re.findall(r"([+-]?\d+(?:\.\d+)?)\s*(CNY|USD)", block)
        postings = [a for a in amounts if a[1] == "CNY"]
        total = sum(float(a[0]) for a in postings)
        if abs(total) > 0.01:
            print(f"  [警告] {date.group(1)} 该笔借贷不平衡，合计 {total:.2f} CNY")
            return False
    return True


def parse_voucher_ref(user_input: str):
    """提取末尾 '@文件名' 凭证引用。返回 (描述, 凭证文件名或 None)。约定：引用必须放在末尾。"""
    if "@" in user_input:
        desc, _, ref = user_input.rpartition("@")
        ref = ref.strip()
        if ref:
            return desc.strip(), ref
    return user_input, None


def entry_date(entries: str):
    """取分录第一笔交易日期，返回 YYYY-MM-DD 或 None。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", entries)
    return m.group(1) if m else None


VAT_XML_TAGS = {
    "Fpje": "不含税金额",
    "Se": "税额",
    "Hjse": "合计税额",
    "Jshj": "价税合计",
    "Hjje": "价税合计",
    "Sl": "税率",
    "Fph": "发票号码",
    "Kprq": "开票日期",
}


def extract_xml_tax(xml_path: str):
    """从数电票 XML 提取价税字段（宽松正则，容错各版本）。失败返回 None。"""
    try:
        text = open(xml_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    fields = {}
    for tag, label in VAT_XML_TAGS.items():
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text)
        if m and m.group(1).strip():
            fields[label] = m.group(1).strip()
    return fields or None


def archive_voucher(filename: str, tx_date: str):
    """把 inbox 凭证归档到 凭证/YYYY-MM/，返回 (相对路径, sha256, 是否复用)。

    幂等：凭证已在 凭证/*/ 归档过时直接复用（不重复移动、不重复改名、不产生副本）；
    inbox 与归档都没有才返回 (None, None, False)。
    """
    src = os.path.join(INBOX_DIR, filename)
    if os.path.exists(src):
        sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
        month = (tx_date or datetime.date.today().isoformat())[:7]
        dest_dir = os.path.join(VOUCHER_DIR, month)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, filename)
        if os.path.exists(dest):
            if hashlib.sha256(open(dest, "rb").read()).hexdigest() == sha:
                os.remove(src)  # 同名同内容已归档 → 复用，清掉 inbox 副本
                return os.path.join("凭证", month, filename), sha, True
            base, ext = os.path.splitext(filename)
            dest = os.path.join(dest_dir, f"{base}_{datetime.datetime.now():%H%M%S}{ext}")
        shutil.move(src, dest)
        return os.path.join("凭证", month, os.path.basename(dest)), sha, False
    for month_dir in sorted(os.listdir(VOUCHER_DIR)):
        if month_dir == "inbox" or not os.path.isdir(os.path.join(VOUCHER_DIR, month_dir)):
            continue
        existing = os.path.join(VOUCHER_DIR, month_dir, filename)
        if os.path.exists(existing):
            sha = hashlib.sha256(open(existing, "rb").read()).hexdigest()
            return os.path.join("凭证", month_dir, filename), sha, True
    return None, None, False


def attach_voucher(suggestion: str, voucher_rel: str, sha: str) -> str:
    """在交易头行后插入 voucher 元数据行（凭证路径 + sha256 锚定）。"""
    lines = suggestion.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"\d{4}-\d{2}-\d{2}\s*\*", line):
            lines.insert(i + 1, f'  voucher: "{voucher_rel}"')
            lines.insert(i + 2, f'  voucher_sha256: "{sha}"')
            break
    return "\n".join(lines)


def git_commit(message: str, extra_paths=()):
    subprocess.run(["git", "add", LEDGER, *extra_paths], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"{message}\n\nCo-Authored-By: DeepSeek V4 Flash <noreply@anthropic.com>"],
        check=True,
    )


def main():
    if not AUTH_TOKEN:
        print("错误：未设置 ANTHROPIC_AUTH_TOKEN")
        sys.exit(1)
    accounts = ledger_accounts()
    today = datetime.date.today().isoformat()
    if TAXPAYER == "general":
        tax_rules = (
            "价税分离规则（当前：一般纳税人）：\n"
            "  - 采购/支出：价税分离——不含税入费用或资产，进项税额（可抵扣）入 Assets:Tax:VAT-Input。\n"
            "  - 销售/收入：不含税入收入，销项税额入 Liabilities:Tax:VAT。\n"
        )
    else:
        tax_rules = (
            "价税分离规则（当前：小规模纳税人）：\n"
            "  - 采购/支出：价税合计全额入费用或资产，不拆进项（小规模不可抵扣）。\n"
            "  - 销售/收入：必须价税分离——含税价款 T 入银行/现金，收入=T/(1+征收率) 记 Income:Services，税额记 Liabilities:Tax:VAT。\n"
            f"  - 当前征收率 {VAT_RATE:.2%}（法定 3%，2026 减按 1%，至 2027 底）；描述金额未明示含税时按价税合计。\n"
            "  - 缴纳增值税：借 Liabilities:Tax:VAT，贷 付款来源。\n"
            "  - 销售额符合免税（月≤10万/季≤30万）时，免税额可转入 Income:Other。\n"
        )
    system = (
        "你是记账助手，只输出 Beancount 双式记账分录，不输出任何解释。\n"
        "可用科目（只能从以下科目中选择，禁止新建科目）：\n"
        f"{accounts}\n\n"
        "规则：\n"
        f"1. 日期用 {today}（今天），除非描述中给出明确日期。\n"
        "2. 每笔交易借贷合计必须为 0（双式平衡）。\n"
        "3. 收入记 Income:Services（贷），银行/现金借方。\n"
        "4. 支出记 Expenses:*（借），付款来源贷方。\n"
        "5. 用 `*` 标记已核销（clearance），格式：2026-08-12 * \"对手方\" \"说明\"\n"
        "6. 未指定来源时默认从 Assets:Bank:Check 支付。\n"
        + tax_rules
        + "只输出 beancount 代码块。"
    )
    os.makedirs(INBOX_DIR, exist_ok=True)
    pending = [f for f in os.listdir(INBOX_DIR) if not f.startswith(".")]
    print(f"对话记账启动。账本：{LEDGER} | 模型：{MODEL}")
    print(f"可用科目：\n{accounts}\n")
    print("凭证：丢进 凭证/inbox/，对话里在末尾用 '@文件名' 关联该笔并自动归档（凭证/YYYY-MM/ + sha256）。")
    print(f"  inbox 待归档：{', '.join(pending) if pending else '（空）'}\n")
    print("输入记账描述（或 q 退出）。例如：客户A 咨询尾款 18000 到银行；买键盘 650 用信用卡 @凭证图.png")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "退出"):
            break

        desc, voucher_ref = parse_voucher_ref(user_input)
        if voucher_ref and not os.path.exists(os.path.join(INBOX_DIR, voucher_ref)):
            print(f"  [错误] 凭证不在 inbox：{voucher_ref}")
            inbox_now = [f for f in os.listdir(INBOX_DIR) if not f.startswith(".")]
            print(f"  inbox 现有：{', '.join(inbox_now) if inbox_now else '（空）'}")
            continue
        llm_input = desc or user_input
        if voucher_ref and voucher_ref.lower().endswith(".xml"):
            tax = extract_xml_tax(os.path.join(INBOX_DIR, voucher_ref))
            if tax:
                print(f"  [XML] 凭证价税字段：{json.dumps(tax, ensure_ascii=False)}")
                llm_input += (
                    "\n[凭证 XML 已提取价税字段] " + json.dumps(tax, ensure_ascii=False)
                    + "\n价税合计、不含税金额、税额须与该凭证一致，按凭证做价税分离入账。"
                )
            else:
                print("  [XML] 未从该 XML 提取到价税字段；可在描述里给出不含税金额与税额。")

        suggestion = None
        for attempt in range(MAX_RETRY + 1):
            try:
                suggestion = extract_code_block(call_llm(system, llm_input))
                break
            except Exception as e:
                print(f"  LLM 调用失败（{e}），重试 {attempt + 1}/{MAX_RETRY}")
        if suggestion is None:
            print("  LLM 调用失败，跳过。")
            continue

        print("\n--- AI 建议分录 ---")
        print(suggestion)
        if not validate_balances(suggestion):
            print("  [提示] 上述分录借贷不平衡，建议检查或让 AI 重新生成。")

        while True:
            ans = input("\n确认追加？[y=确认 / n=跳过 / r=重新生成 / q=退出] ").strip().lower()
            if ans == "q":
                return
            if ans == "y":
                extra_paths = ()
                archived = ""
                if voucher_ref:
                    rel, sha, reused = archive_voucher(voucher_ref, entry_date(suggestion))
                    if rel is None:
                        print(f"  [错误] 凭证归档失败：{voucher_ref}")
                        break
                    suggestion = attach_voucher(suggestion, rel, sha)
                    extra_paths = (os.path.join(os.path.dirname(os.path.abspath(__file__)), rel),)
                    archived = f" 凭证 → {rel} ({sha[:12]}…)"
                    if reused:
                        archived += "（已归档，复用）"
                with open(LEDGER, "a", encoding="utf-8") as f:
                    f.write("\n" + suggestion + "\n")
                if subprocess.run(["bean-check", LEDGER]).returncode != 0:
                    print("  bean-check 校验失败！分录未提交，请检查账本。")
                    sys.exit(1)
                git_commit(f"记账：{(desc or user_input)[:60]}", extra_paths)
                print(f"  已提交 ✓{archived}")
                break
            elif ans == "r":
                suggestion = extract_code_block(call_llm(system, llm_input))
                print("\n--- AI 重新生成 ---")
                print(suggestion)
                validate_balances(suggestion)
            elif ans == "n":
                print("  已跳过（不追加）。")
                break
            else:
                print("  输入 y/n/r/q")


if __name__ == "__main__":
    main()
