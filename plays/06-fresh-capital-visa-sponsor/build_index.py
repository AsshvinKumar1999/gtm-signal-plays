#!/usr/bin/env python3
"""Play 06, step 1: turn the DOL H-1B disclosure file into a small sponsor index.

Source: U.S. Department of Labor, OFLC "LCA Disclosure Data" (free, quarterly):
  https://www.dol.gov/agencies/eta/foreign-labor/performance
Download (about 250 MB; DOL wants a contact in the User-Agent, like SEC):
  curl -fL -A "Your Name you@example.com" -o data/LCA_Disclosure_Data_FY2026_Q3.xlsx \
       https://www.dol.gov//media/LCA_Disclosure_Data_FY2026_Q3.xlsx
Run:
  uv run --with python-calamine python build_index.py data/LCA_Disclosure_Data_FY2026_Q3.xlsx

Keeps only H-1B applications with CASE_STATUS "Certified". An LCA is the employer's
wage filing that comes before an H-1B petition: it shows intent to sponsor, not a visa granted.
Writes data/sponsors.json keyed by tax ID (FEIN digits) and by normalized employer name.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SUFFIX_RE = re.compile(r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|pbc|lp|llp)\b\.?", re.I)
PER_YEAR = {"Year": 1, "Month": 12, "Bi-Weekly": 26, "Week": 52, "Hour": 2080}


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", SUFFIX_RE.sub("", (s or "").lower()))


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    from python_calamine import CalamineWorkbook

    src = Path(sys.argv[1])
    rows = CalamineWorkbook.from_path(str(src)).get_sheet_by_index(0).iter_rows()
    head = [str(h) for h in next(rows)]
    col = {h: i for i, h in enumerate(head)}
    need = ["CASE_STATUS", "VISA_CLASS", "EMPLOYER_NAME", "EMPLOYER_FEIN", "JOB_TITLE", "SOC_TITLE",
            "WORKSITE_STATE", "WAGE_RATE_OF_PAY_FROM", "WAGE_UNIT_OF_PAY", "DECISION_DATE"]
    missing = [n for n in need if n not in col]
    if missing:
        sys.exit(f"Columns missing from {src.name}: {missing}")

    emp = defaultdict(lambda: {"names": Counter(), "titles": Counter(), "soc": Counter(), "states": Counter(),
                               "wages": [], "n": 0, "last": ""})
    total = kept = 0
    for r in rows:
        total += 1
        if r[col["VISA_CLASS"]] != "H-1B" or r[col["CASE_STATUS"]] != "Certified":
            continue
        fein = digits(str(r[col["EMPLOYER_FEIN"]]))
        name = str(r[col["EMPLOYER_NAME"]] or "").strip()
        key = fein if len(fein) == 9 else "name:" + norm_name(name)
        e = emp[key]
        e["n"] += 1
        e["names"][name] += 1
        e["titles"][str(r[col["JOB_TITLE"]] or "").strip()] += 1
        e["soc"][str(r[col["SOC_TITLE"]] or "").strip()] += 1
        e["states"][str(r[col["WORKSITE_STATE"]] or "").strip()] += 1
        e["last"] = max(e["last"], str(r[col["DECISION_DATE"]] or "")[:10])
        try:
            wage = float(r[col["WAGE_RATE_OF_PAY_FROM"]]) * PER_YEAR.get(str(r[col["WAGE_UNIT_OF_PAY"]]), 0)
            if wage > 0:
                e["wages"].append(wage)
        except (TypeError, ValueError):
            pass
        kept += 1

    by_fein, by_name = {}, {}
    for key, e in emp.items():
        rec = {"name": e["names"].most_common(1)[0][0], "certified_h1b": e["n"], "last_decision": e["last"],
               "top_titles": [t for t, _ in e["titles"].most_common(6)], "top_soc": [t for t, _ in e["soc"].most_common(3)],
               "states": [s for s, _ in e["states"].most_common(4)],
               "median_wage": round(statistics.median(e["wages"])) if e["wages"] else None}
        if not key.startswith("name:"):
            rec["fein"] = key
            by_fein[key] = rec
        for n in e["names"]:
            by_name.setdefault(norm_name(n), rec)
    out = src.parent / "sponsors.json"
    out.write_text(json.dumps({"source": src.name, "rows_read": total, "certified_h1b": kept,
                               "employers": len(emp), "by_fein": by_fein, "by_name": by_name}))
    print(f"rows {total:,} · certified H-1B {kept:,} · employers {len(emp):,} · wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
