#!/usr/bin/env python3
"""Play 01: Fresh Capital + Open GTM Role.

Two free public signals, no API keys:
  1. SEC Form D: a private company legally reported a new raise (EDGAR daily index).
  2. A live job post for the role your product serves (Greenhouse, Lever, Ashby public APIs).

Usage:
  SEC_USER_AGENT="Your Name you@example.com" python3 run.py --days 7
  python3 run.py --days 14 --roles "security|compliance|soc 2"

Writes out/<date>/accounts.csv, summary.json and briefs.md next to this file.
Python 3.9+, standard library only.
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
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SEC = "https://www.sec.gov/Archives/"
SEC_DELAY_S = 0.12  # SEC fair access: stay under 10 requests per second
TECH_GROUPS = {"Other Technology", "Computers", "Telecommunications"}
# Pooled funds and SPVs file Form D too; skip them before fetching.
FUND_RE = re.compile(
    r"\b(l\.?p\.?|fund|funds|partners|capital|holdings|investors?|spv|series|opportunit\w*|"
    r"ventures?|trust|reit|properties|realty|lending|credit|income|acquisition|master|feeder|"
    r"co-invest\w*|offshore|portfolio|equity|estate|apartments|housing)\b", re.I)
SUFFIX_RE = re.compile(r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|pbc)\b\.?", re.I)
DEFAULT_ROLES = (r"revenue operations|revops|sales operations|go-to-market|\bgtm\b|growth|demand gen|"
                 r"marketing|account executive|sales development|\bsdr\b|\bbdr\b|head of sales|"
                 r"founding (sales|account)|business development")
ATS_WORKERS = 6
# Buckets for every open role found, checked in this order (first match wins).
ROLE_BUCKETS = [
    ("FDE & solutions", r"forward[- ]deployed|deployment (engineer|strategist)|solutions? (engineer|architect)|implementation (engineer|manager)"),
    ("GTM engineering", r"gtm (engineer|ops|operations|systems)|go-to-market (engineer|operations)|growth engineer|revenue operations|revops|sales operations|marketing operations"),
    ("Product", r"product (manager|lead|owner|designer|director)|head of product|\bvp,? product|group product"),
    ("Marketing", r"marketing|demand gen|content|brand|communications|\bpr\b|community|growth (lead|manager|marketer)"),
    ("Sales", r"account executive|\bsales\b|business development|\bsdr\b|\bbdr\b|account manager|partnerships?|customer success"),
]


def one_per_company(rows: list[dict]) -> list[dict]:
    """A company can file several Form Ds in a week; keep its latest filing so it counts once."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r["cik"] not in latest or r["filed"] > latest[r["cik"]]["filed"]:
            latest[r["cik"]] = r
    return list(latest.values())


def bucket(title: str) -> str:
    for name, pattern in ROLE_BUCKETS:
        if re.search(pattern, title, re.I):
            return name
    return "Other"


def fetch(url: str, ua: str, timeout: int = 20) -> bytes | None:
    """GET a URL. Returns None on 404 or network failure; retries once on 429/503."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt == 0:
                time.sleep(2)
                continue
            return None  # SEC answers 403 (not 404) for missing files, e.g. weekend indexes
        except (urllib.error.URLError, OSError):  # includes socket.timeout on Python 3.9
            return None
    return None


def daily_index(day: dt.date, ua: str) -> list[dict]:
    q = (day.month - 1) // 3 + 1
    raw = fetch(f"{SEC}edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx", ua)
    time.sleep(SEC_DELAY_S)
    if not raw:
        return []  # weekend, holiday, or not published yet
    rows = []
    for line in raw.decode("latin-1").splitlines():
        if not line.startswith("D "):
            continue  # new filings only; "D/A" amendments are skipped
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 5:
            rows.append({"company": parts[1], "cik": parts[2], "filed": parts[3], "path": parts[4]})
    return rows


def parse_form_d(row: dict, ua: str) -> dict | None:
    acc = Path(row["path"]).stem.replace("-", "")
    url = f"{SEC}edgar/data/{int(row['cik'])}/{acc}/primary_doc.xml"
    raw = fetch(url, ua)
    time.sleep(SEC_DELAY_S)
    if not raw:
        return None
    try:
        x = ET.fromstring(raw)
    except ET.ParseError:
        return None
    t = lambda p: (x.findtext(p) or "").strip()
    group = t(".//industryGroup/industryGroupType")
    if group not in TECH_GROUPS:
        return None
    people = []
    for p in x.findall(".//relatedPersonInfo"):
        name = " ".join(filter(None, [p.findtext(".//firstName"), p.findtext(".//lastName")])).strip()
        roles = "/".join(r.text for r in p.findall(".//relationship") if r.text)
        if name:
            people.append(f"{name} ({roles})")
    return {
        "company": t(".//primaryIssuer/entityName") or row["company"],
        "cik": row["cik"], "filed": row["filed"], "state": t(".//issuerAddress/stateOrCountry"),
        "industry": group, "first_sale": t(".//dateOfFirstSale/value"),
        "amount_sold": t(".//totalAmountSold"), "offering_total": t(".//totalOfferingAmount"),
        "people": "; ".join(people[:4]),
        "filing_url": f"https://www.sec.gov/Archives/{row['path']}",
    }


def slugs(company: str) -> list[str]:
    base = SUFFIX_RE.sub(" ", company.lower()).replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    out = ["".join(words), "-".join(words)]
    if len(words) > 1 and words[-1] in {"ai", "labs", "technologies", "technology", "software", "hq", "io"}:
        out.append("".join(words[:-1]))
    return list(dict.fromkeys(s for s in out if len(s) >= 3))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", SUFFIX_RE.sub("", s.lower()))


def find_board(company: str, ua: str) -> dict | None:
    """Probe public ATS boards by slug; a malformed response counts as no board."""
    try:
        return _find_board(company, ua)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def _find_board(company: str, ua: str) -> dict | None:
    """Greenhouse boards can be name-verified; Lever and Ashby are slug matches only."""
    for slug in slugs(company):
        raw = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", ua)
        if raw:
            meta = json.loads(fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}", ua) or b"{}")
            jobs = [(j["title"], j["absolute_url"], (j.get("location") or {}).get("name", ""))
                    for j in json.loads(raw).get("jobs", [])]
            verified = _norm(meta.get("name", "")) == _norm(company)
            return {"ats": "greenhouse", "slug": slug, "jobs": jobs, "verified": verified}
        raw = fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json", ua)
        if raw and raw.strip().startswith(b"["):
            jobs = [(j["text"], j["hostedUrl"], (j.get("categories") or {}).get("location", ""))
                    for j in json.loads(raw)]
            return {"ats": "lever", "slug": slug, "jobs": jobs, "verified": False}
        raw = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", ua)
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict) and "jobs" in data:
                jobs = [(j["title"], j["jobUrl"], j.get("location", "")) for j in data["jobs"]]
                return {"ats": "ashby", "slug": slug, "jobs": jobs, "verified": False}
    return None


def score(acct: dict, board: dict | None, roles: re.Pattern) -> dict:
    hits = [j for j in (board or {}).get("jobs", []) if roles.search(j[0])]
    tier = 1 if hits else (2 if board else 3)
    return {**acct,
            "tier": tier,
            "ats": board["ats"] if board else "",
            "board_match": ("name-verified" if board and board["verified"] else "slug-only") if board else "",
            "open_jobs": len(board["jobs"]) if board else 0,
            "target_roles": " | ".join(h[0] for h in hits[:3]),
            "role_urls": " ".join(h[1] for h in hits[:3])}


def write_outputs(rows: list[dict], out: Path, meta: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["tier"], r["filed"]))
    with open(out / "accounts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["company"])
        w.writeheader()
        w.writerows(rows)
    (out / "summary.json").write_text(json.dumps(meta, indent=2))
    lines = [f"# Tier 1 briefs: {meta['window']}", ""]
    for r in (r for r in rows if r["tier"] == 1):
        lines += [f"## {r['company']} ({r['state']})",
                  f"- Raised: ${r['amount_sold'] or '?'} sold of ${r['offering_total'] or '?'}; "
                  f"first sale {r['first_sale'] or 'n/a'}; filed {r['filed']} ([Form D]({r['filing_url']}))",
                  f"- Hiring now ({r['ats']}, {r['board_match']}): {r['target_roles']}",
                  f"- People on the filing: {r['people'] or 'n/a'}",
                  f"- Role links: {r['role_urls']}", ""]
    (out / "briefs.md").write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description="Play 01: Fresh Capital + Open GTM Role")
    ap.add_argument("--days", type=int, default=7, help="calendar days of Form D filings to scan")
    ap.add_argument("--roles", default=DEFAULT_ROLES, help="regex for the job titles your product serves")
    ap.add_argument("--end", help="last filing date YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--out", help="output folder (default: out/<today> next to this file)")
    args = ap.parse_args()
    ua = os.environ.get("SEC_USER_AGENT", "")
    if "@" not in ua:
        sys.exit("Set SEC_USER_AGENT='Your Name your@email.com' (SEC requires a contact).")
    roles = re.compile(args.roles, re.I)
    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today() - dt.timedelta(days=1)
    days = [end - dt.timedelta(days=i) for i in range(args.days)]

    out = Path(args.out).resolve() if args.out else Path(__file__).resolve().parent / "out" / str(dt.date.today())
    cache = out / f"sec-cache-{days[-1]}-{days[0]}.json"
    if cache.exists():  # rerun of the same window: skip the slow, rate-limited SEC step
        saved = json.loads(cache.read_text())
        filings, operating, tech = saved["filings"], saved["operating"], saved["tech"]
        print(f"[1-2] Loaded SEC results from {cache.name}", flush=True)
    else:
        filings = [r for d in days for r in daily_index(d, ua)]
        if not filings:
            sys.exit("No Form D index loaded. Check SEC_USER_AGENT ('Your Name your@email.com') "
                     "and that the window includes business days.")
        operating = [r for r in filings if not FUND_RE.search(r["company"])]
        print(f"[1] Form D filings: {len(filings)} new; {len(operating)} after removing funds/SPVs", flush=True)
        tech = []
        for i, r in enumerate(operating, 1):
            parsed = parse_form_d(r, ua)
            if parsed:
                tech.append(parsed)
            if i % 100 == 0:
                print(f"    parsed {i}/{len(operating)}; tech so far {len(tech)}", flush=True)
        out.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"filings": filings, "operating": operating, "tech": tech}))
    operating, tech = one_per_company(operating), one_per_company(tech)
    print(f"    unique operating companies: {len(operating)}", flush=True)
    print(f"[2] Technology companies (one per company): {len(tech)}", flush=True)

    with ThreadPoolExecutor(ATS_WORKERS) as pool:
        boards = list(pool.map(lambda a: find_board(a["company"], ua), tech))
    rows = [score(a, b, roles) for a, b in zip(tech, boards)]
    jobs = [{"company": a["company"], "state": a["state"], "raised_usd": a["amount_sold"], "form_d_filed": a["filed"],
             "title": title, "bucket": bucket(title), "location": loc if isinstance(loc, str) else "",
             "url": url, "ats": b["ats"], "board_match": "name-verified" if b["verified"] else "slug-only"}
            for a, b in zip(tech, boards) if b for title, url, loc in b["jobs"]]
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "jobs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(jobs[0].keys()) if jobs else ["company"])
        w.writeheader()
        w.writerows(jobs)
    by_bucket = {name: sum(1 for j in jobs if j["bucket"] == name) for name, _ in ROLE_BUCKETS + [("Other", "")]}
    print(f"[5] Open roles at these companies: {len(jobs)} ({', '.join(f'{k} {v}' for k, v in by_bucket.items())})")
    tiers = {t: sum(1 for r in rows if r["tier"] == t) for t in (1, 2, 3)}
    print(f"[3] Public job board found: {tiers[1] + tiers[2]}", flush=True)
    print(f"[4] Tier 1 (raised + hiring the target role): {tiers[1]}; Tier 2: {tiers[2]}; Tier 3: {tiers[3]}")

    meta = {"window": f"{days[-1]} to {days[0]}", "run_at": dt.datetime.now().isoformat(timespec="seconds"),
            "form_d_new": len(filings), "operating": len(operating), "tech": len(tech),
            "with_board": tiers[1] + tiers[2], "tier1": tiers[1], "tier2": tiers[2], "tier3": tiers[3],
            "roles_regex": args.roles, "open_roles": len(jobs), "roles_by_bucket": by_bucket}
    write_outputs(rows, out, meta)
    print(f"Wrote {out}/accounts.csv, jobs.csv, summary.json, briefs.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
