#!/usr/bin/env python3
"""Append confirmed closing quotes to the cloud daily-K seed."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path


DATA_DIR = Path(os.environ["APP_DATA_DIR"])
SEED_DIR = Path(os.environ["TDX_BRIDGE_DIR"]) / "klines"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, payload) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    watchlist = load_json(DATA_DIR / "watchlist.json").get("items") or []
    updated = 0
    skipped = []
    for item in watchlist:
        code = str(item.get("code") or "")
        seed_path = SEED_DIR / f"{code}_daily.json"
        quote_path = DATA_DIR / "cache" / f"quote_{code}.json"
        if not seed_path.exists() or not quote_path.exists():
            skipped.append(code)
            continue

        seed = load_json(seed_path)
        quote = (load_json(quote_path).get("payload") or {})
        quote_date = str(quote.get("quoteTime") or "").replace("-", "")
        price = quote.get("price")
        if len(quote_date) != 8 or price is None:
            skipped.append(code)
            continue

        rows = seed.get("klines") or []
        previous = next(
            (row for row in reversed(rows) if str(row.get("date")) < quote_date),
            None,
        )
        previous_close = (previous or {}).get("close") or quote.get("previousClose")
        pct_change = (
            round((price - previous_close) / previous_close * 100, 4)
            if previous_close
            else quote.get("pctChange")
        )
        quote_source = str(quote.get("source") or "cloud-quote")
        closing_bar = {
            "date": quote_date,
            "open": quote.get("open") or price,
            "high": quote.get("high") or price,
            "low": quote.get("low") or price,
            "close": price,
            "volume": quote.get("volume"),
            "amount": quote.get("amount"),
            "pctChange": pct_change,
            "turnoverRate": quote.get("turnoverRate"),
            "source": f"{quote_source}-cloud-close",
        }
        rows = [row for row in rows if str(row.get("date")) != quote_date]
        rows.append(closing_bar)
        rows.sort(key=lambda row: str(row.get("date") or ""))
        seed["klines"] = rows[-520:]
        seed["source"] = f"tdx-seed+{quote_source}-cloud-close"
        seed["generatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        atomic_write(seed_path, seed)
        updated += 1

    print(
        json.dumps(
            {"ok": updated > 0, "updated": updated, "skipped": skipped},
            ensure_ascii=False,
        )
    )
    return 0 if updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
