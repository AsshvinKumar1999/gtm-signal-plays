#!/usr/bin/env python3
"""Play 06: Fresh Capital + Visa Sponsor (for job seekers).

Joins three free public sources:
  1. Play 01 output: tech companies that just filed a Form D with the SEC, and their open roles.
  2. Each company's tax ID (EIN), read from the header of that same SEC filing.
  3. DOL H-1B wage filings (LCAs), indexed by build_index.py into data/sponsors.json.

A company matches when its EIN appears in the DOL data (exact), or, if the filing has no EIN,
when its name matches exactly after removing Inc/LLC/Corp (marked "name-only, check by hand").

Usage:
  SEC_USER_AGENT="Your Name you@example.com" python3 run.py --play01 ../01-fresh-capital-open-role/out/<run>
  python3 run.py --play01 <dir> --roles "product manager|solutions engineer"
Python 3.9+, standard library only. Writes out/<date>/sponsors.csv, roles.csv, summary.json.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SEC_DELAY_S = 0.12
SUFFIX_RE = re.compile(r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|pbc|lp|llp)\b\.?", re.I)
STOP = {"senior", "staff", "lead", "principal", "junior", "associate", "manager", "director", "head", "with",
        "team", "remote", "the", "and", "for", "level", "intern", "global", "group"}


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", SUFFIX_RE.sub("", (s or "").lower()))


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) >= 4 and w not in STOP}


def fetch(url: str, ua: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read(6000)  # the SGML header with the EIN is at the top
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt == 0:
                time.sleep(2)
                continue
            return None
        except (urllib.error.URLError, OSError):
            return None
    return None


def filing_ein(filing_url: str, ua: str) -> str:
    raw = fetch(filing_url, ua)
    time.sleep(SEC_DELAY_S)
    m = re.search(rb"EIN:\s*(\d{9})", raw or b"")
    ein = m.group(1).decode() if m else ""
    return "" if ein in ("", "000000000") else ein


def main() -> int:
    ap = argparse.ArgumentParser(description="Play 06: Fresh Capital + Visa Sponsor")
    ap.add_argument("--play01", required=True, help="a Play 01 output folder with accounts.csv and jobs.csv")
    ap.add_argument("--sponsors", default=str(Path(__file__).resolve().parent / "data" / "sponsors.json"))
    ap.add_argument("--roles", default="", help="optional regex for the roles you want")
    ap.add_argument("--out", help="output folder (default: out/<today>)")
    args = ap.parse_args()
    ua = os.environ.get("SEC_USER_AGENT", "")
    if "@" not in ua:
        sys.exit("Set SEC_USER_AGENT='Your Name your@email.com' (SEC requires a contact).")
    src = Path(args.play01)
    if not (src / "accounts.csv").exists() or not (src / "jobs.csv").exists():
        sys.exit(f"{src} needs accounts.csv and jobs.csv from Play 01's run.py")
    sp = Path(args.sponsors)
    if not sp.exists():
        sys.exit(f"{sp} not found. Run build_index.py first.")
    index = json.loads(sp.read_text())

    accounts = list(csv.DictReader(open(src / "accounts.csv")))
    jobs = list(csv.DictReader(open(src / "jobs.csv")))
    want = re.compile(args.roles, re.I) if args.roles else None
    print(f"[1] Tech companies from Play 01: {len(accounts)}; open roles: {len(jobs)}", flush=True)

    sponsors, ein_found = [], 0
    for i, a in enumerate(accounts, 1):
        ein = filing_ein(a["filing_url"], ua)
        ein_found += bool(ein)
        rec, how = (index["by_fein"].get(ein), "EIN") if ein else (None, "")
        if not rec:
            rec = index["by_name"].get(norm_name(a["company"]))
            how = "name-only" if rec else ""
        if rec:
            sponsors.append({**a, "ein": ein, "match": how, "h1b_certified": rec["certified_h1b"],
                             "h1b_last_decision": rec["last_decision"], "h1b_titles": " | ".join(rec["top_titles"]),
                             "h1b_states": " ".join(rec["states"]), "h1b_median_wage": rec["median_wage"] or "",
                             "dol_employer_name": rec["name"]})
        if i % 50 == 0:
            print(f"    checked {i}/{len(accounts)}; sponsors so far {len(sponsors)}", flush=True)
    print(f"[2] Sponsored H-1B workers before (DOL): {len(sponsors)} "
          f"({sum(s['match'] == 'EIN' for s in sponsors)} by EIN, {sum(s['match'] == 'name-only' for s in sponsors)} name-only)", flush=True)

    by_company = {s["company"]: s for s in sponsors}
    roles = []
    for j in jobs:
        s = by_company.get(j["company"])
        if not s or (want and not want.search(j["title"])):
            continue
        # "similar" = shares at least 2 meaningful words with one title they filed H-1B paperwork for
        same_kind = any(len(words(j["title"]) & words(t)) >= 2 for t in s["h1b_titles"].split(" | "))
        roles.append({"company": j["company"], "title": j["title"], "bucket": j["bucket"], "location": j["location"],
                      "url": j["url"], "raised_usd": j["raised_usd"], "form_d_filed": j["form_d_filed"],
                      "h1b_certified": s["h1b_certified"], "similar_title_sponsored": "yes" if same_kind else "",
                      "h1b_titles": s["h1b_titles"], "match": s["match"]})
    hiring = {r["company"] for r in roles}
    print(f"[3] Sponsors that are hiring now: {len(hiring)}; open roles there: {len(roles)} "
          f"({sum(r['similar_title_sponsored'] == 'yes' for r in roles)} look like jobs they sponsored before)")

    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "out" / str(dt.date.today())
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("sponsors.csv", sponsors), ("roles.csv", roles)):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["company"])
            w.writeheader()
            w.writerows(rows)
    sponsor_cos = {s["company"] for s in sponsors}
    similar_cos = {r["company"] for r in roles if r["similar_title_sponsored"] == "yes"}
    summary = {"play01_run": str(src), "dol_source": index["source"], "tech_companies": len(accounts), "ein_found": ein_found,
               "tier1_similar_role_open": len(similar_cos), "tier2_other_roles_open": len(hiring - similar_cos),
               "tier3_no_open_roles_found": len(sponsor_cos - hiring),
               "sponsors": len(sponsors), "by_ein": sum(s["match"] == "EIN" for s in sponsors),
               "sponsors_hiring": len(hiring), "roles_at_sponsors": len(roles),
               "roles_similar_to_sponsored": sum(r["similar_title_sponsored"] == "yes" for r in roles),
               "roles_regex": args.roles, "run_at": dt.datetime.now().isoformat(timespec="seconds")}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Wrote {out}/sponsors.csv, roles.csv, summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
