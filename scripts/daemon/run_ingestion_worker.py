#!/usr/bin/env python3
"""Run one bounded Reloop outbox delivery batch."""

from __future__ import annotations

import argparse
import json

from reloop.ops.worker import run_once


def main() -> int:
    parser = argparse.ArgumentParser(description="Reloop ingestion outbox worker")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run_once(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
