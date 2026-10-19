# mpesa-sms-parser

Turns Safaricom M-PESA confirmation SMS into clean, structured data: a CSV or JSON row per transaction, a quick spending summary, and a balance check that tells you when a message is missing.

Pure Python standard library, no dependencies. Python 3.9+.

## Why

Most small businesses and individuals in Kenya keep their real ledger in their SMS inbox. Getting it into a spreadsheet usually means retyping. Export the messages from your phone (any SMS backup app that writes plain text works), point this at the file, and you get rows you can load into Excel, pandas or a database.

## Usage

```bash
# summary
python -m mpesa_parser samples/messages.txt

# every transaction as CSV / JSON
python -m mpesa_parser samples/messages.txt --export csv -o transactions.csv
python -m mpesa_parser samples/messages.txt --export json

# from stdin
cat inbox.txt | python -m mpesa_parser -
```

Or install it to get an `mpesa-parse` command:

```bash
pip install -e .
mpesa-parse inbox.txt --export csv
```

In code:

```python
from mpesa_parser import parse_text, summarize

txns = parse_text(open("inbox.txt").read())
for t in txns:
    print(t.timestamp, t.kind, t.amount, t.counterparty)
```

## Sample output

```
12 transactions  (01 Oct 2026 to 11 Oct 2026)

  Money in       Ksh 7,250.00
  Money out      Ksh 5,600.00
  Fees              Ksh 50.00
  Net            Ksh 1,600.00

By type
  received       3      Ksh 4,250.00
  deposit        1      Ksh 3,000.00
  withdrawal     1      Ksh 2,000.00
  buy_goods      2      Ksh 1,500.00
  sent           3      Ksh 1,000.00
  paybill        1      Ksh 1,000.00
  airtime        1        Ksh 100.00

Where the money went
  ALPHA AGENCIES WESTLANDS        Ksh 2,000.00
  JAVA HOUSE KIMATHI STREET       Ksh 1,250.00
  KPLC PREPAID                    Ksh 1,000.00
  JANE WANJIRU                      Ksh 800.00
  NAIVAS SUPERMARKET                Ksh 250.00

Balance gaps: 1 (a message is probably missing)
  between TJK3FG8H2H and TJM7KL3N6N: unexplained -Ksh 500.00
```

The sample file is synthetic. One message was left out on purpose so the balance check has something to find.

## What it recognises

| kind | example wording | extracted |
|---|---|---|
| `received` | *You have received Ksh1,500.00 from JOHN KAMAU 0712…* | name, phone (full or masked) |
| `sent` | *Ksh500.00 sent to JANE WANJIRU 0722…* | name, phone |
| `paybill` | *Ksh1,000.00 sent to KPLC PREPAID for account 5432…* | business, account number |
| `buy_goods` | *Ksh250.00 paid to NAIVAS SUPERMARKET.* | merchant |
| `withdrawal` | *Withdraw Ksh2,000.00 from 123456 - ALPHA AGENCIES* | agent name, agent number |
| `deposit` | *Give Ksh3,000.00 cash to ALPHA AGENCIES* | agent name |
| `airtime` | *You bought Ksh100.00 of airtime* | |

Every row also carries the transaction code, timestamp, new balance and transaction cost. Messages with a transaction code but an unfamiliar format come through as `kind=unknown` rather than being dropped, and repeated codes (common in SMS backups) are removed unless you pass `--keep-duplicates`.

## The balance check

Each confirmation SMS reports the new balance. Sorting by time and replaying amounts and fees, every balance should follow exactly from the previous one. When it doesn't, something happened between those two messages that the file doesn't contain: a deleted SMS, a reversal, or a message type the parser doesn't know yet. The summary lists each gap and the unexplained amount.

## Limitations

- English-language messages only. Swahili confirmations aren't handled yet.
- Safaricom changes the wording from time to time. If a format slips through as `unknown`, add a pattern in `mpesa_parser/parser.py` and a test.
- Fuliza, M-Shwari, reversals and Pochi la Biashara messages aren't parsed yet.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```
