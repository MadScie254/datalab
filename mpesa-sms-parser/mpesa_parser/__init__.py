"""Parse Safaricom M-PESA confirmation SMS into structured transactions."""

from .parser import INFLOW, OUTFLOW, Transaction, iter_messages, parse_message, parse_text
from .summary import BalanceGap, find_balance_gaps, format_summary, summarize

__all__ = [
    "INFLOW", "OUTFLOW", "Transaction", "iter_messages", "parse_message", "parse_text",
    "BalanceGap", "find_balance_gaps", "format_summary", "summarize",
]
__version__ = "0.1.0"
