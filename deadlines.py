"""Attach real comment deadlines and effective dates to store items.

    python deadlines.py --dry-run   # show what would be matched, change nothing
    python deadlines.py             # match and write back to store.json

Uses the Federal Register API, which exposes `comments_close_on` and
`effective_on` as structured fields. That's exact and free — no model call, no
document scraping, no guessing.

The catch is matching: our items mostly come from agency press releases, whose
titles are close to but not identical to the Federal Register document title. A
naive search is dangerous — querying "Lending to Individuals Not Legally
Authorized to Work" returns 4,340 hits whose top result is a rule about seasonal
migratory game bird hunting. Attaching that deadline would be confidently wrong,
which is worse than reporting nothing.

So every candidate is verified by title similarity before its dates are accepted,
and anything below the bar is left as-is.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import dedupe

STORE_PATH = "store.json"
API = "https://www.federalregister.gov/api/v1/documents.json"
UA = {"User-Agent": "RegWatch/1.0"}

# Two-tier gate. Title similarity alone must clear STRICT. A weaker title match
# is accepted only when the Federal Register document is published by the same
# agency we sourced the item from — agency agreement is strong corroboration, and
# it recovers real matches that phrasing differences push below the strict bar
# (an agency press release rarely uses the rule's formal title verbatim).
STRICT_THRESHOLD = 0.60
CORROBORATED_THRESHOLD = 0.40

# Our source labels -> substrings that appear in Federal Register agency names.
AGENCY_ALIASES = {
    "FDIC": ("federal deposit insurance",),
    "FDIC FILs": ("federal deposit insurance",),
    "OCC": ("comptroller of the currency",),
    "OCC Bulletins": ("comptroller of the currency",),
    "Federal Reserve": ("federal reserve",),
    "Fed SR/CA Letters": ("federal reserve",),
    "CFPB": ("consumer financial protection",),
    "CFPB Rules": ("consumer financial protection",),
    "FinCEN": ("financial crimes enforcement", "treasury"),
    "FinCEN Advisories": ("financial crimes enforcement", "treasury"),
    "OFAC": ("foreign assets control", "treasury"),
    "NCUA": ("national credit union",),
    "NCUA Press": ("national credit union",),
}


def agency_matches(sources, fr_agencies):
    """True if any of our source labels corresponds to a publishing agency."""
    names = " ".join(
        (a.get("name", "") + " " + a.get("raw_name", "")).lower()
        for a in (fr_agencies or [])
    )
    for src in sources or []:
        for alias in AGENCY_ALIASES.get(src, ()):
            if alias in names:
                return True
    return False

# Only these carry deadlines worth chasing. Press releases about bank failures
# or personnel don't have comment periods.
DEADLINE_TYPES = {"Final Rule", "Proposed Rule", "Notice"}


def search_fr(term, per_page=5):
    query = {
        "conditions[term]": term,
        "order": "relevance",
        "per_page": str(per_page),
        "fields[]": [
            "title", "type", "publication_date", "comments_close_on",
            "effective_on", "dates", "html_url", "agencies",
        ],
    }
    url = API + "?" + urllib.parse.urlencode(query, doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
        return json.load(r)


def best_match(title):
    """Return (record, score) for the closest Federal Register document, or (None, 0)."""
    # Long titles blow past the API's term handling; the leading clause carries
    # the distinguishing words anyway.
    term = " ".join(title.split()[:14])
    try:
        data = search_fr(term)
    except Exception:
        return None, 0.0

    best, best_score = None, 0.0
    for r in data.get("results", []):
        score = dedupe.similarity(title, r.get("title", ""))
        if score > best_score:
            best, best_score = r, score
    return best, best_score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, don't write")
    ap.add_argument("--all-types", action="store_true",
                    help="try every item, not just rules and notices")
    args = ap.parse_args()

    with open(STORE_PATH, encoding="utf-8") as f:
        store = json.load(f)

    targets = [
        r for r in store.values()
        if r.get("relevant")
        and not r.get("fr_checked")
        and (args.all_types or r.get("update_type") in DEADLINE_TYPES)
    ]
    print(f"{len(targets)} item(s) to check against the Federal Register\n")

    matched = dated = 0
    for i, rec in enumerate(targets, 1):
        title = rec.get("title", "")
        hit, score = best_match(title)
        time.sleep(0.4)  # be polite to a free public API

        corroborated = bool(hit) and agency_matches(rec.get("sources"), hit.get("agencies"))
        accepted = bool(hit) and (
            score >= STRICT_THRESHOLD
            or (score >= CORROBORATED_THRESHOLD and corroborated)
        )

        if not accepted:
            why = f"{score:.2f}{'+agency' if corroborated else ''}"
            print(f"[{i}/{len(targets)}] no match ({why})  {title[:48]}")
            if not args.dry_run:
                rec["fr_checked"] = True
            continue

        matched += 1
        close = hit.get("comments_close_on")
        eff = hit.get("effective_on")
        flag = "*" if (close or eff) else " "
        if close or eff:
            dated += 1
        print(f"[{i}/{len(targets)}]{flag}match {score:.2f}"
              f"{'+ag' if corroborated else '   '}  close={close or '-'} "
              f"eff={eff or '-'}  {title[:40]}")

        if not args.dry_run:
            rec["fr_checked"] = True
            rec["fr_url"] = hit.get("html_url")
            rec["fr_title"] = hit.get("title")
            rec["fr_match_score"] = round(score, 3)
            rec["comments_close_on"] = close
            rec["effective_on"] = eff
            rec["fr_dates_text"] = hit.get("dates")

    print(f"\n{matched} matched, {dated} carry a comment deadline or effective date")

    if args.dry_run:
        print("DRY RUN — store.json unchanged")
        return

    for r in store.values():
        r.setdefault("fr_checked", False)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    import os
    os.replace(tmp, STORE_PATH)
    print("store.json updated")


if __name__ == "__main__":
    main()
