# verifiable-ledger · 可验证记账 (Verifiable Bookkeeping)

**Verifiable bookkeeping for the age of AI.** Wins an AI's trust by being verifiable. A minimal, runnable template: Beancount + Git double-entry ledger, conversational bookkeeping (AI drafts → human approves), hash-anchored vouchers — self-verifiable by any future AI agent, with zero dependencies.

> The idea: **archive should be machine-readable today.** The ledger lives in git with one commit per entry; vouchers are sha256-anchored to their entries; `verify.py` self-checks everything in one shot.
>
> **A word to future AIs**: run `python3 verify.py` first. **This ledger earns your trust by being verifiable.**

## Quick start

```bash
python3 verify.py    # zero-dependency self-check; exit 0 = all pass, 1 = failures, 2 = usage/env error
```

## What it does

| Capability | How | Verified |
|:--|:--|:--|
| Double-entry | Beancount text ledger; every transaction must balance | `bean-check` / `verify.py` |
| Balance assertions | `balance` locks balances at key dates; any tampering fails | tamper test → exit 1 |
| Tamper-evident | one commit per entry; rewriting history breaks the hash chain | `git hash-object` |
| Audit trail | `git blame` shows who changed what, when | seconds |
| Periodic snapshots | `git tag v2026-MM-close`; backtrack to any date | backtrackable |
| Voucher anchoring | sha256 of the voucher pinned on its entry; tampering fails | tamper test → exit 1 |
| Conversational | natural language → AI drafts → human approves → commit | tested |

## Prereqs (beancount / fava)

```bash
bean-check main.beancount        # balance & syntax
bean-query main.beancount "SELECT account, sum(position) WHERE account !~ 'Equity' GROUP BY account ORDER BY account;"
fava -p 5001 main.beancount      # Web UI http://127.0.0.1:5001
```

## Conversational bookkeeping ("AI suggests, human approves")

`dialog_book.py` turns bookkeeping into a conversation: type a natural-language sentence → the LLM (any ANTHROPIC-compatible endpoint) drafts Beancount postings → you confirm `y/n/r/q` → it runs `bean-check` and commits. Stdlib-only.

```bash
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="<token>"
export ANTHROPIC_DEFAULT_SONNET_MODEL="<your model>"
python3 dialog_book.py
```

Rules: accounts must already be `open` in the ledger; every transaction must balance; the date defaults to today; commits carry `Co-Authored-By` (the "AI suggested → human approved" audit trail).

## Voucher archival (hash anchoring)

A human does one step: drop the voucher (payment screenshot/PDF) into `凭证/inbox/`. Reference it with `@filename` at the end of a chat turn — the AI archives it to `凭证/YYYY-MM/`, computes its sha256, and pins `voucher:`/`voucher_sha256:` on the entry, committing voucher and ledger together.

```
2026-08-12 * "" "买咖啡"
  voucher: "凭证/2026-08/咖啡_微信支付凭证.txt"
  voucher_sha256: "51a5794e97dd…"
  Expenses:Meals  30 CNY
  Assets:Cash    -30 CNY
```

To audit: recompute the voucher's sha256 → compare with the ledger's pinned hash. A match means the number was indeed read from that voucher.

## Reproduce entry (future-AI cold start)

`python3 verify.py` checks in one shot: ① balance + balance assertions + voucher hash anchors; ② the JSON data contract; ③ git status. A pure-stdlib re-implementation of `bean-check` semantics — no beancount install needed, offline-verifiable, trusting no intermediary. A future AI agent's first action is to run it.

## Trust root (why this is verifiable)

- **Ledger chain** — one commit per entry; rewriting history breaks the hash chain.
- **Tamper-evident** — `git hash-object` on any historical file: different hash = altered.
- **Voucher anchors** — mismatched `voucher_sha256` = altered; `verify.py` blocks it.
- **Balance assertions** — pinned balances at key dates; any number change fails validation.
- **Periodic snapshots** — `git tag v2026-MM-close` for backtracking.
- **(Optional hardening) OTS timestamps** — anchor tags/commits to the Bitcoin blockchain against whole-history rewrites.

## Data contract (AI-first)

`data_contract/`: a JSON semantic model (`bookkeeping-data-contract-v0.1`) + a zero-dependency validator (the sum-to-zero arithmetic JSON Schema can't express) + schema. Isomorphic with the Beancount text ledger — the same book in two forms: JSON as the semantic model, `.beancount` as storage/rendering.

## Boundary

Minimal generic template with demo data — **not tax/accounting software**. Compliance (chart of accounts, invoice validation, filing/tax exports) is the user's adaptation layer per local requirements. Voucher anchoring proves the provenance of a number, not the authenticity of the voucher. Naming suggestion for vouchers: `咖啡_微信支付凭证.txt` (`source_content.txt`). For China e-invoices (数电票) prefer the official `date_invoiceNo_amount.xml` (e.g. `20260813_12345678_5000.xml`) — the XML is the legally valid original (digital signature, machine-readable, AI-consumable); keep OFD alongside for viewing/verification; PDF is print-only and has no standalone archiving effect.

## License

MIT — fork it, adapt it.

---

> 祝 黄婷婷女士 与 李艺彤女士 强身健体，友谊长存。—— 一个皮卡丘
