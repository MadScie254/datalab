"""Roll parsed transactions up into totals and spot missing messages."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Sequence

from .parser import INFLOW, OUTFLOW, Transaction


@dataclass(frozen=True)
class BalanceGap:
    """Two consecutive messages whose balances don't add up.

    Usually means an SMS is missing between them (deleted, never
    delivered, or a transaction type the parser doesn't recognise).
    """

    after_code: str
    before_code: str
    expected: Decimal
    reported: Decimal

    @property
    def unexplained(self) -> Decimal:
        return self.reported - self.expected


def find_balance_gaps(transactions: Sequence[Transaction]) -> List[BalanceGap]:
    gaps = []
    previous = None
    for txn in transactions:
        if txn.balance is None or txn.amount is None:
            previous = None
            continue
        if previous is not None:
            expected = previous.balance + txn.net_effect
            if abs(expected - txn.balance) > Decimal("0.01"):
                gaps.append(BalanceGap(previous.code, txn.code, expected, txn.balance))
        previous = txn
    return gaps


def summarize(transactions: Sequence[Transaction], top_n: int = 5) -> Dict:
    known = [t for t in transactions if t.amount is not None]
    money_in = sum((t.amount for t in known if t.direction == INFLOW), Decimal("0"))
    money_out = sum((t.amount for t in known if t.direction == OUTFLOW), Decimal("0"))
    fees = sum((t.cost for t in known), Decimal("0"))

    by_kind: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "total": Decimal("0")})
    for t in known:
        by_kind[t.kind]["count"] += 1
        by_kind[t.kind]["total"] += t.amount

    spend = Counter()
    for t in known:
        if t.direction == OUTFLOW:
            spend[t.counterparty or t.kind] += t.amount

    stamps = [t.timestamp for t in known if t.timestamp]
    return {
        "transactions": len(transactions),
        "unrecognised": len(transactions) - len(known),
        "first": min(stamps) if stamps else None,
        "last": max(stamps) if stamps else None,
        "money_in": money_in,
        "money_out": money_out,
        "fees": fees,
        "net": money_in - money_out - fees,
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1]["total"])),
        "top_spend": spend.most_common(top_n),
        "balance_gaps": find_balance_gaps(transactions),
    }


def format_summary(summary: Dict) -> str:
    def money(value: Decimal) -> str:
        sign = "-" if value < 0 else ""
        return f"{sign}Ksh {abs(value):,.2f}"

    lines = []
    span = ""
    if summary["first"] and summary["last"]:
        span = f"  ({summary['first']:%d %b %Y} to {summary['last']:%d %b %Y})"
    lines.append(f"{summary['transactions']} transactions{span}")
    if summary["unrecognised"]:
        lines.append(f"  {summary['unrecognised']} message(s) not recognised; run with --export to inspect")
    lines.append("")
    lines.append(f"  Money in   {money(summary['money_in']):>16}")
    lines.append(f"  Money out  {money(summary['money_out']):>16}")
    lines.append(f"  Fees       {money(summary['fees']):>16}")
    lines.append(f"  Net        {money(summary['net']):>16}")

    lines.append("")
    lines.append("By type")
    for kind, stats in summary["by_kind"].items():
        lines.append(f"  {kind:<12}{stats['count']:>4}  {money(stats['total']):>16}")

    if summary["top_spend"]:
        lines.append("")
        lines.append("Where the money went")
        for name, total in summary["top_spend"]:
            lines.append(f"  {name[:28]:<28}{money(total):>16}")

    gaps = summary["balance_gaps"]
    lines.append("")
    if gaps:
        lines.append(f"Balance gaps: {len(gaps)} (a message is probably missing)")
        for gap in gaps:
            lines.append(
                f"  between {gap.after_code} and {gap.before_code}: "
                f"unexplained {money(gap.unexplained)}"
            )
    else:
        lines.append("Balance check: every balance follows from the one before it")
    return "\n".join(lines)
