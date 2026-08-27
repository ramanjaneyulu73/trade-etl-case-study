"""Simulates a feed of trade messages arriving from upstream booking systems.

Produces a JSON-lines file per run under data/incoming/. Each run mixes in a
deliberate share of new trades, version amendments, same-version corrections,
out-of-order (stale) versions, and already-matured trades so the downstream
dbt validation rules all get exercised.
"""
import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

fake = Faker()

INSTRUMENT_TYPES = ["FX_FORWARD", "IRS", "BOND", "EQUITY_SWAP", "CDS"]
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "INR", "AUD", "CHF"]
STATUSES = ["NEW", "AMENDED"]
SOURCE_SYSTEMS = ["MURK", "CALYPSO", "SUMMIT", "INTERNAL_BLOTTER"]

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "incoming"


def random_trade(trade_id=None, version=1, maturity_offset_days=None):
    trade_date = datetime.now(timezone.utc).date() - timedelta(days=random.randint(0, 5))
    if maturity_offset_days is None:
        maturity_offset_days = random.randint(30, 1825)
    maturity_date = trade_date + timedelta(days=maturity_offset_days)
    return {
        "trade_id": trade_id or f"TRD-{uuid.uuid4().hex[:10].upper()}",
        "version": version,
        "trade_date": trade_date.isoformat(),
        "maturity_date": maturity_date.isoformat(),
        "counterparty": fake.company(),
        "instrument_type": random.choice(INSTRUMENT_TYPES),
        "notional": round(random.uniform(10_000, 50_000_000), 2),
        "currency": random.choice(CURRENCIES),
        "price": round(random.uniform(0.5, 150.0), 4),
        "status": random.choice(STATUSES) if version == 1 else "AMENDED",
        "source_system": random.choice(SOURCE_SYSTEMS),
        "event_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_batch(n_new, n_amend_higher, n_amend_same, n_amend_stale, n_matured, existing_trade_ids):
    batch = []

    for _ in range(n_new):
        t = random_trade()
        batch.append(t)
        existing_trade_ids.append((t["trade_id"], t["version"]))

    for _ in range(n_amend_higher):
        if not existing_trade_ids:
            break
        trade_id, version = random.choice(existing_trade_ids)
        t = random_trade(trade_id=trade_id, version=version + 1)
        batch.append(t)
        existing_trade_ids.append((trade_id, version + 1))

    for _ in range(n_amend_same):
        if not existing_trade_ids:
            break
        trade_id, version = random.choice(existing_trade_ids)
        t = random_trade(trade_id=trade_id, version=version)
        batch.append(t)

    for _ in range(n_amend_stale):
        if not existing_trade_ids:
            break
        trade_id, version = random.choice(existing_trade_ids)
        if version <= 1:
            continue
        t = random_trade(trade_id=trade_id, version=version - 1)
        batch.append(t)

    for _ in range(n_matured):
        t = random_trade(maturity_offset_days=-random.randint(1, 90))
        batch.append(t)

    random.shuffle(batch)
    return batch


def main():
    parser = argparse.ArgumentParser(description="Generate a simulated batch of trade messages")
    parser.add_argument("--count", type=int, default=200, help="approximate number of trades to emit")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    total = args.count
    n_matured = max(1, int(total * 0.03))
    n_amend_stale = max(1, int(total * 0.03))
    n_amend_same = max(1, int(total * 0.05))
    n_amend_higher = max(1, int(total * 0.15))
    n_new = total - (n_matured + n_amend_stale + n_amend_same + n_amend_higher)

    batch = build_batch(n_new, n_amend_higher, n_amend_same, n_amend_stale, n_matured, existing_trade_ids=[])

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    out_path = DATA_DIR / f"trades_{run_id}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for record in batch:
            f.write(json.dumps(record) + "\n")

    print(f"Wrote {len(batch)} trade records to {out_path}")


if __name__ == "__main__":
    main()
