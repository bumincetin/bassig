#!/usr/bin/env python3
"""Merge the translation parts into the catalogues the application loads.

Run after editing anything in translations/_parts/:
    python translations/build.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "_parts"
LANGUAGES = ("tr", "it")


def build():
    summary = {}
    for code in LANGUAGES:
        merged, duplicates = {}, []
        for path in sorted(PARTS.glob(f"{code}_*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if key in merged and merged[key] != value:
                    duplicates.append((path.name, key))
                merged[key] = value
        target = HERE / f"{code}.json"
        target.write_text(
            json.dumps(dict(sorted(merged.items())), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8")
        summary[code] = {"entries": len(merged), "conflicts": duplicates}
        print(f"{target.name}: {len(merged)} entries"
              + (f"  ({len(duplicates)} conflicting duplicate(s))" if duplicates else ""))
        for name, key in duplicates[:5]:
            print(f"   conflict in {name}: {key!r}")
    return summary


if __name__ == "__main__":
    build()
    sys.exit(0)
