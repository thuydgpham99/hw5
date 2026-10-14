"""Reset the working copy of the shop database from the untouched original.

    python backend/reset_db.py

Throws away everything a run did -- payments, approvals, drafts, purchase orders, ticket
status changes -- and puts the board back to three open tickets. The original
data/campus_customs.db is only ever read.

Deliberately NOT an MCP tool: no agent should be able to erase the shop's books, so this
is a human-run script.

The audit trail in output/audit_trail.json is left alone. It is append-only across runs,
including runs that were reset.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys

from config import ORIGINAL_DB, WORKING_DB


def reset() -> None:
    if not ORIGINAL_DB.exists():
        raise SystemExit(f"Original database missing at {ORIGINAL_DB} -- nothing to reset from.")

    shutil.copyfile(ORIGINAL_DB, WORKING_DB)

    conn = sqlite3.connect(f"file:{WORKING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    today = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()["date_today"]
    tickets = conn.execute(
        "SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"
    ).fetchall()
    cash = conn.execute("SELECT name, balance FROM cash_accounts").fetchall()
    invoices = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS owed FROM invoices WHERE status != 'paid'"
    ).fetchone()
    conn.close()

    print(f"Reset {WORKING_DB.name} from {ORIGINAL_DB.name}")
    print(f"  shop today : {today}")
    print(f"  tickets    : " + ", ".join(f"{r['n']} {r['status']}" for r in tickets))
    print(f"  cash       : " + ", ".join(f"{r['name']} {r['balance']:.2f}" for r in cash))
    print(f"  unpaid     : {invoices['n']} invoice(s), {invoices['owed']:.2f} owed")
    print("  payments   : 0 (the run starts with no money moved)")


if __name__ == "__main__":
    sys.exit(reset())
