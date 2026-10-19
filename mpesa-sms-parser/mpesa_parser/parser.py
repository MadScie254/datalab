"""Parse Safaricom M-PESA confirmation SMS messages into structured records.

Only the standard library is used, so the parser drops into any project
(ETL job, Django view, notebook) without pulling in dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator, List, Optional

INFLOW = "in"
OUTFLOW = "out"

_CUR = r"(?:Ksh|KES)\s?"
_AMT = r"[\d,]+(?:\.\d{1,2})?"

# A message starts with a 10-character transaction code followed by "Confirmed".
_CODE_RE = re.compile(r"\b([A-Z0-9]{10})\s+[Cc]onfirmed")
_WHEN_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(\d{1,2}:\d{2})\s*([AaPp][Mm])")
_BALANCE_RE = re.compile(r"balance is\s+" + _CUR + r"(" + _AMT + r")", re.I)
_COST_RE = re.compile(r"Transaction cost,?\s*" + _CUR + r"(" + _AMT + r")", re.I)

# Trailing phone number on a counterparty: full (0712345678 / 254712345678)
# or masked the way newer messages print it (0712***678).
_PHONE_TAIL_RE = re.compile(r"^(.*?)[\s,]+((?:\+?254|0)\d{9}|\+?\d{2,12}\*{2,}\d{2,4})$")
_AGENT_RE = re.compile(r"^(\d+)\s*-\s*(.+)$")


def _pattern(template: str) -> "re.Pattern[str]":
    return re.compile(template.replace("{AMT}", _CUR + r"(?P<amount>" + _AMT + r")"), re.I)


# Order matters: paybill must be tried before plain "sent to".
_PATTERNS = [
    ("received", INFLOW, _pattern(r"received\s+{AMT}\s+from\s+(?P<party>.+?)\s+on\s+\d")),
    ("paybill", OUTFLOW, _pattern(r"{AMT}\s+sent to\s+(?P<party>.+?)\s+for account\s+(?P<account>.+?)\s+on\s+\d")),
    ("sent", OUTFLOW, _pattern(r"{AMT}\s+sent to\s+(?P<party>.+?)\s+on\s+\d")),
    ("buy_goods", OUTFLOW, _pattern(r"{AMT}\s+paid to\s+(?P<party>.+?)\.?\s+on\s+\d")),
    ("withdrawal", OUTFLOW, _pattern(r"Withdraw\s+{AMT}\s+from\s+(?P<party>.+?)\s*New M-PESA")),
    ("deposit", INFLOW, _pattern(r"Give\s+{AMT}\s+cash to\s+(?P<party>.+?)\s*New M-PESA")),
    ("airtime", OUTFLOW, _pattern(r"bought\s+{AMT}\s+of airtime")),
]


@dataclass(frozen=True)
class Transaction:
    code: str
    kind: str
    direction: str
    amount: Optional[Decimal]
    counterparty: str
    phone: str
    account: str
    timestamp: Optional[datetime]
    balance: Optional[Decimal]
    cost: Decimal
    raw: str

    @property
    def net_effect(self) -> Decimal:
        """Change this transaction made to the wallet balance, fees included."""
        if self.amount is None:
            return Decimal("0")
        if self.direction == INFLOW:
            return self.amount
        return -(self.amount + self.cost)

    def to_dict(self, include_raw: bool = False) -> dict:
        row = {
            "code": self.code,
            "kind": self.kind,
            "direction": self.direction,
            "amount": _fmt(self.amount),
            "counterparty": self.counterparty,
            "phone": self.phone,
            "account": self.account,
            "timestamp": self.timestamp.isoformat(sep=" ") if self.timestamp else "",
            "balance": _fmt(self.balance),
            "cost": _fmt(self.cost),
        }
        if include_raw:
            row["raw"] = self.raw
        return row


def _fmt(value: Optional[Decimal]) -> str:
    return "" if value is None else f"{value:.2f}"


def _money(text: Optional[str]) -> Optional[Decimal]:
    if not text:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _parse_when(message: str) -> Optional[datetime]:
    match = _WHEN_RE.search(message)
    if not match:
        return None
    date, clock, meridiem = match.groups()
    year_fmt = "%Y" if len(date.rsplit("/", 1)[-1]) == 4 else "%y"
    try:
        return datetime.strptime(f"{date} {clock} {meridiem.upper()}", f"%d/%m/{year_fmt} %I:%M %p")
    except ValueError:
        return None


def _split_party(party: str, kind: str) -> tuple:
    """Return (name, phone, account) from the raw counterparty text."""
    party = party.strip(" .,")
    if kind == "withdrawal":
        agent = _AGENT_RE.match(party)
        if agent:
            return agent.group(2).strip(" .,"), "", agent.group(1)
    if kind in ("received", "sent"):
        tail = _PHONE_TAIL_RE.match(party)
        if tail:
            return tail.group(1).strip(" .,"), tail.group(2), ""
    return party, "", ""


def parse_message(message: str) -> Optional[Transaction]:
    """Parse one SMS. Returns None when the text has no transaction code."""
    text = re.sub(r"\s+", " ", message).strip()
    code_match = _CODE_RE.search(text)
    if not code_match:
        return None

    kind, direction = "unknown", ""
    amount: Optional[Decimal] = None
    name = phone = account = ""
    for candidate, flow, pattern in _PATTERNS:
        found = pattern.search(text)
        if not found:
            continue
        kind, direction = candidate, flow
        amount = _money(found.group("amount"))
        groups = found.groupdict()
        if groups.get("party"):
            name, phone, account = _split_party(groups["party"], kind)
        if groups.get("account"):
            account = groups["account"].strip(" .,")
        if kind == "airtime":
            name = "Safaricom Airtime"
        break

    cost_match = _COST_RE.search(text)
    balance_match = _BALANCE_RE.search(text)
    return Transaction(
        code=code_match.group(1),
        kind=kind,
        direction=direction,
        amount=amount,
        counterparty=name,
        phone=phone,
        account=account,
        timestamp=_parse_when(text),
        balance=_money(balance_match.group(1)) if balance_match else None,
        cost=_money(cost_match.group(1)) if cost_match else Decimal("0"),
        raw=text,
    )


def iter_messages(text: str) -> Iterator[str]:
    """Split a dump of SMS text (one per line, or run together) into messages."""
    starts = [m.start() for m in _CODE_RE.finditer(text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            yield chunk


def parse_text(text: str, dedupe: bool = True) -> List[Transaction]:
    """Parse every message in a block of text, oldest first.

    Exported SMS backups often repeat messages, so duplicates (same
    transaction code) are dropped unless ``dedupe`` is False.
    """
    seen = set()
    transactions = []
    for chunk in iter_messages(text):
        txn = parse_message(chunk)
        if txn is None:
            continue
        if dedupe and txn.code in seen:
            continue
        seen.add(txn.code)
        transactions.append(txn)
    return sorted(transactions, key=lambda t: (t.timestamp is None, t.timestamp or datetime.min))
