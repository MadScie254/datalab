"""Command-line entry point: ``python -m mpesa_parser messages.txt``."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import List, Optional

from .parser import parse_text
from .summary import format_summary, summarize

FIELDS = ["code", "kind", "direction", "amount", "counterparty", "phone",
          "account", "timestamp", "balance", "cost"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mpesa-parse",
        description="Turn M-PESA confirmation SMS into a summary, CSV or JSON.",
    )
    p.add_argument("input", help="text file of SMS messages, or - for stdin")
    p.add_argument("--export", choices=["csv", "json"],
                   help="write every transaction instead of the summary")
    p.add_argument("-o", "--output", help="file to write to (default: stdout)")
    p.add_argument("--include-raw", action="store_true",
                   help="keep the original SMS text in exported rows")
    p.add_argument("--keep-duplicates", action="store_true",
                   help="don't drop repeated transaction codes")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8") as fh:
            text = fh.read()

    transactions = parse_text(text, dedupe=not args.keep_duplicates)
    if not transactions:
        print("No M-PESA messages found.", file=sys.stderr)
        return 1

    out = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        if args.export == "csv":
            fields = FIELDS + (["raw"] if args.include_raw else [])
            writer = csv.DictWriter(out, fieldnames=fields)
            writer.writeheader()
            for txn in transactions:
                writer.writerow(txn.to_dict(include_raw=args.include_raw))
        elif args.export == "json":
            rows = [txn.to_dict(include_raw=args.include_raw) for txn in transactions]
            json.dump(rows, out, indent=2)
            out.write("\n")
        else:
            out.write(format_summary(summarize(transactions)) + "\n")
        out.flush()
    except BrokenPipeError:
        # Output piped into something like `head` that stopped reading early.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
