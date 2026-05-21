# /// script
# requires-python = ">=3.11"
# dependencies = ["faker>=25.0"]
# ///
"""
Greedy Bank demo data generator for DQ Sentinel.

Seeded, reproducible. Emits 3 clean CSVs plus 5 pre-broken variant CSVs that
correspond to the break scenarios in PRD §8. All amounts AUD.

Usage (zero-config with uv):
    uv run demo-data/generate.py

Usage (plain pip):
    pip install -r demo-data/requirements.txt
    python demo-data/generate.py
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker

SEED = 20260520
OUT_DIR = Path(__file__).parent / "csv"

N_ACCOUNT_HOLDERS = 500
N_TRANSACTIONS = 2000
N_LOAN_PRODUCTS = 100

TODAY = date(2026, 5, 21)
# Short window so a 1-2 day data-loss break crosses the >30% deviation threshold
# defined in the bigquery-dq-checks spec.
TXN_WINDOW_DAYS = 5

# How many account_holders to null kyc_status on. ~20% = clearly above the
# >2x-baseline null-rate threshold (baseline kyc_status null rate is 0).
N_KYC_NULLS = 100

fake = Faker("en_AU")
Faker.seed(SEED)
random.seed(SEED)


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {len(rows):>5} rows → {path.relative_to(OUT_DIR.parent.parent)}")


def gen_account_holders() -> tuple[list[str], list[list[object]]]:
    header = ["account_id", "full_name", "email", "opened_at", "country_code", "kyc_status"]
    countries = ["AU", "AU", "AU", "AU", "NZ", "SG"]  # weighted AU
    statuses = ["verified"] * 9 + ["pending"]
    rows: list[list[object]] = []
    for i in range(1, N_ACCOUNT_HOLDERS + 1):
        opened = fake.date_between(start_date="-3y", end_date=TODAY)
        rows.append([
            f"ACC-{i:06d}",
            fake.name(),
            fake.unique.email(),
            opened.isoformat(),
            random.choice(countries),
            random.choice(statuses),
        ])
    return header, rows


def gen_transactions(account_ids: list[str]) -> tuple[list[str], list[list[object]]]:
    header = ["txn_id", "account_id", "amount_aud", "currency", "txn_date", "status", "channel"]
    channels = ["card", "card", "card", "transfer", "transfer", "direct_debit"]
    statuses = ["settled"] * 19 + ["pending"]
    rows: list[list[object]] = []
    txn_seq = 0
    for _ in range(N_TRANSACTIONS):
        days_ago = random.randint(0, TXN_WINDOW_DAYS - 1)
        txn_date = TODAY - timedelta(days=days_ago)
        txn_seq += 1
        # Amount distribution: 80% small (card txns), 20% larger transfers.
        if random.random() < 0.8:
            amt = round(random.uniform(5.0, 500.0), 2)
        else:
            amt = round(random.uniform(500.0, 15000.0), 2)
        rows.append([
            f"TXN-{txn_date.strftime('%Y%m%d')}-{txn_seq:05d}",
            random.choice(account_ids),
            amt,
            "AUD",
            txn_date.isoformat(),
            random.choice(statuses),
            random.choice(channels),
        ])
    return header, rows


LOAN_CATEGORIES = ["mortgage", "personal", "auto", "business", "credit_card"]
LOAN_NAME_PARTS = ["Standard", "Fixed 3yr", "Fixed 5yr", "Variable", "Green", "Premium", "Starter", "Pro"]


def gen_loan_products() -> tuple[list[str], list[list[object]]]:
    header = ["product_id", "product_name", "category", "base_apr", "is_active"]
    rows: list[list[object]] = []
    for i in range(1, N_LOAN_PRODUCTS + 1):
        cat = random.choice(LOAN_CATEGORIES)
        suffix = random.choice(LOAN_NAME_PARTS)
        rows.append([
            f"LP-{i:03d}",
            f"Greedy {cat.title().replace('_', ' ')} {suffix}",
            cat,
            round(random.uniform(4.5, 14.9), 2),
            random.choice([True, True, True, False]),
        ])
    return header, rows


def break_null_kyc(header: list[str], rows: list[list[object]]) -> tuple[list[str], list[list[object]]]:
    kyc_idx = header.index("kyc_status")
    # Null on a random subset (any age) so the demo simulates a source-side
    # ETL bug that dropped the column intermittently — more realistic than
    # "only recent accounts" and gives a chunky null-rate spike.
    target_indices = set(random.sample(range(len(rows)), k=min(N_KYC_NULLS, len(rows))))
    new_rows = []
    for i, r in enumerate(rows):
        if i in target_indices:
            r = list(r)
            r[kyc_idx] = ""
        new_rows.append(r)
    null_pct = 100 * len(target_indices) / len(rows)
    print(f"    break_null_kyc: nulled {len(target_indices)} kyc_status values ({null_pct:.0f}% null rate)")
    return header, new_rows


def break_duplicates(header: list[str], rows: list[list[object]]) -> tuple[list[str], list[list[object]]]:
    sample = random.sample(rows, 50)
    new_rows = rows + [list(r) for r in sample]
    print(f"    break_duplicates: appended {len(sample)} duplicate account rows")
    return header, new_rows


def break_data_loss(header: list[str], rows: list[list[object]]) -> tuple[list[str], list[list[object]]]:
    # Drop the two most-recent days to push deviation comfortably above the
    # >30% threshold in the bigquery-dq-checks spec.
    txn_date_idx = header.index("txn_date")
    drop_dates = {(TODAY - timedelta(days=i)).isoformat() for i in (0, 1)}
    new_rows = [r for r in rows if r[txn_date_idx] not in drop_dates]
    dropped = len(rows) - len(new_rows)
    drop_pct = 100 * dropped / len(rows)
    print(f"    break_data_loss: dropped {dropped} rows from {sorted(drop_dates)} ({drop_pct:.0f}% drop)")
    return header, new_rows


def break_distribution_shift(header: list[str], rows: list[list[object]]) -> tuple[list[str], list[list[object]]]:
    txn_date_idx = header.index("txn_date")
    amount_idx = header.index("amount_aud")
    cutoff = TODAY.isoformat()
    affected = 0
    new_rows = []
    for r in rows:
        if r[txn_date_idx] == cutoff:
            r = list(r)
            r[amount_idx] = round(float(r[amount_idx]) * 10, 2)
            affected += 1
        new_rows.append(r)
    print(f"    break_distribution_shift: 10x'd {affected} amounts on {cutoff}")
    return header, new_rows


def break_schema_rename(header: list[str], rows: list[list[object]]) -> tuple[list[str], list[list[object]]]:
    new_header = ["headline_apr" if c == "base_apr" else c for c in header]
    print("    break_schema_rename: renamed base_apr → headline_apr")
    return new_header, rows


def main() -> None:
    print(f"Generating Greedy Bank demo data (seed={SEED}, today={TODAY.isoformat()})...")

    ah_header, ah_rows = gen_account_holders()
    txn_header, txn_rows = gen_transactions([r[0] for r in ah_rows])
    lp_header, lp_rows = gen_loan_products()

    print("Clean:")
    _write_csv(OUT_DIR / "account_holders.csv", ah_header, ah_rows)
    _write_csv(OUT_DIR / "transactions.csv", txn_header, txn_rows)
    _write_csv(OUT_DIR / "loan_products.csv", lp_header, lp_rows)

    print("Broken variants:")
    h, r = break_null_kyc(ah_header, ah_rows)
    _write_csv(OUT_DIR / "account_holders__broken_nulls.csv", h, r)

    h, r = break_duplicates(ah_header, ah_rows)
    _write_csv(OUT_DIR / "account_holders__broken_dupes.csv", h, r)

    h, r = break_data_loss(txn_header, txn_rows)
    _write_csv(OUT_DIR / "transactions__broken_dataloss.csv", h, r)

    h, r = break_distribution_shift(txn_header, txn_rows)
    _write_csv(OUT_DIR / "transactions__broken_distshift.csv", h, r)

    h, r = break_schema_rename(lp_header, lp_rows)
    _write_csv(OUT_DIR / "loan_products__broken_schema.csv", h, r)

    print(f"\nDone. Output: {OUT_DIR}")
    print(f"Generated at: {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
