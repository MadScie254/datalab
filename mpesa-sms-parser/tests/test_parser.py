import contextlib
import io
import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from mpesa_parser import find_balance_gaps, parse_message, parse_text, summarize
from mpesa_parser.cli import main

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "messages.txt"

RECEIVED = ("QK12ABCD34 Confirmed.You have received Ksh1,500.00 from JOHN KAMAU 0712000111 "
            "on 12/10/24 at 3:45 PM  New M-PESA balance is Ksh2,345.67.")
SENT = ("QK56EFGH78 Confirmed. Ksh500.00 sent to JANE WANJIRU 0722000222 on 12/10/24 at 4:00 PM. "
        "New M-PESA balance is Ksh1,838.67. Transaction cost, Ksh7.00.")
PAYBILL = ("QK90IJKL12 Confirmed. Ksh1,000.00 sent to KPLC PREPAID for account 54321098765 "
           "on 12/10/24 at 5:00 PM New M-PESA balance is Ksh838.67. Transaction cost, Ksh0.00.")
BUY_GOODS = ("QK34MNOP56 Confirmed. Ksh250.00 paid to NAIVAS SUPERMARKET. on 12/10/24 at 6:00 PM."
             "New M-PESA balance is Ksh588.67. Transaction cost, Ksh0.00.")
WITHDRAW = ("QK78QRST90 Confirmed.on 13/10/24 at 7:00 PMWithdraw Ksh200.00 from 123456 - ALPHA "
            "AGENCIES New M-PESA balance is Ksh359.67. Transaction cost, Ksh29.00.")
DEPOSIT = ("QK11UVWX22 Confirmed. On 14/10/24 at 9:00 AM Give Ksh3,000.00 cash to ALPHA AGENCIES "
           "New M-PESA balance is Ksh3,359.67.")
AIRTIME = ("QK33YZAB44 confirmed.You bought Ksh100.00 of airtime on 14/10/24 at 10:30 AM."
           "New M-PESA balance is Ksh3,259.67. Transaction cost, Ksh0.00.")


class ParseMessageTests(unittest.TestCase):
    def test_received_splits_name_and_phone(self):
        t = parse_message(RECEIVED)
        self.assertEqual(t.code, "QK12ABCD34")
        self.assertEqual((t.kind, t.direction), ("received", "in"))
        self.assertEqual(t.amount, Decimal("1500.00"))
        self.assertEqual(t.counterparty, "JOHN KAMAU")
        self.assertEqual(t.phone, "0712000111")
        self.assertEqual(t.balance, Decimal("2345.67"))
        self.assertEqual(t.cost, Decimal("0"))
        self.assertEqual(t.timestamp, datetime(2024, 10, 12, 15, 45))

    def test_masked_phone(self):
        t = parse_message(RECEIVED.replace("0712000111", "0712***111"))
        self.assertEqual((t.counterparty, t.phone), ("JOHN KAMAU", "0712***111"))

    def test_sent_with_fee(self):
        t = parse_message(SENT)
        self.assertEqual((t.kind, t.direction), ("sent", "out"))
        self.assertEqual(t.counterparty, "JANE WANJIRU")
        self.assertEqual(t.cost, Decimal("7.00"))
        self.assertEqual(t.net_effect, Decimal("-507.00"))

    def test_paybill_is_not_mistaken_for_send(self):
        t = parse_message(PAYBILL)
        self.assertEqual(t.kind, "paybill")
        self.assertEqual(t.counterparty, "KPLC PREPAID")
        self.assertEqual(t.account, "54321098765")
        self.assertEqual(t.phone, "")

    def test_buy_goods_strips_trailing_dot(self):
        t = parse_message(BUY_GOODS)
        self.assertEqual((t.kind, t.counterparty), ("buy_goods", "NAIVAS SUPERMARKET"))

    def test_withdrawal_separates_agent_number(self):
        t = parse_message(WITHDRAW)
        self.assertEqual(t.kind, "withdrawal")
        self.assertEqual((t.counterparty, t.account), ("ALPHA AGENCIES", "123456"))
        self.assertEqual(t.timestamp, datetime(2024, 10, 13, 19, 0))

    def test_deposit_is_inflow(self):
        t = parse_message(DEPOSIT)
        self.assertEqual((t.kind, t.direction, t.amount), ("deposit", "in", Decimal("3000.00")))

    def test_airtime(self):
        t = parse_message(AIRTIME)
        self.assertEqual((t.kind, t.amount), ("airtime", Decimal("100.00")))

    def test_four_digit_year(self):
        t = parse_message(SENT.replace("12/10/24", "12/10/2024"))
        self.assertEqual(t.timestamp, datetime(2024, 10, 12, 16, 0))

    def test_unrecognised_message_keeps_code(self):
        t = parse_message("QK55CDEF66 Confirmed. Reversal of transaction QK00 has been processed.")
        self.assertEqual((t.code, t.kind, t.amount), ("QK55CDEF66", "unknown", None))

    def test_text_without_code_is_ignored(self):
        self.assertIsNone(parse_message("Your data bundle expires today."))


class ParseTextTests(unittest.TestCase):
    def test_messages_run_together_on_one_line(self):
        txns = parse_text(RECEIVED + " " + SENT + PAYBILL)
        self.assertEqual([t.kind for t in txns], ["received", "sent", "paybill"])

    def test_duplicates_dropped_by_default(self):
        blob = "\n".join([SENT, SENT, RECEIVED])
        self.assertEqual(len(parse_text(blob)), 2)
        self.assertEqual(len(parse_text(blob, dedupe=False)), 3)

    def test_sorted_oldest_first(self):
        txns = parse_text("\n".join([AIRTIME, RECEIVED, WITHDRAW]))
        self.assertEqual([t.kind for t in txns], ["received", "withdrawal", "airtime"])


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.txns = parse_text(SAMPLE.read_text(encoding="utf-8"))

    def test_sample_totals(self):
        s = summarize(self.txns)
        self.assertEqual(s["transactions"], 12)
        self.assertEqual(s["money_in"], Decimal("7250.00"))
        self.assertEqual(s["money_out"], Decimal("5600.00"))
        self.assertEqual(s["fees"], Decimal("50.00"))
        self.assertEqual(s["net"], Decimal("1600.00"))

    def test_sample_has_one_missing_message(self):
        gaps = find_balance_gaps(self.txns)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].before_code, "TJM7KL3N6N")
        self.assertEqual(gaps[0].unexplained, Decimal("-500.00"))

    def test_consistent_chain_has_no_gaps(self):
        chain = parse_text("\n".join([RECEIVED, SENT, PAYBILL, BUY_GOODS, WITHDRAW, DEPOSIT, AIRTIME]))
        self.assertEqual(find_balance_gaps(chain), [])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main([str(SAMPLE), *args])
        return code, buf.getvalue()

    def test_summary(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("12 transactions", out)
        self.assertIn("Balance gaps: 1", out)

    def test_csv_export(self):
        code, out = self.run_cli("--export", "csv")
        lines = out.strip().splitlines()
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("code,kind,direction,amount"))
        self.assertEqual(len(lines), 13)

    def test_json_export(self):
        code, out = self.run_cli("--export", "json")
        rows = json.loads(out)
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["counterparty"], "JOHN KAMAU")


if __name__ == "__main__":
    unittest.main()
