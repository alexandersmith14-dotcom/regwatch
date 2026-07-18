"""RegWatch source health check.

Run after pipeline.py. Answers one question: is every source we think we are
watching actually still delivering?

The failure this exists to catch is the quiet one. A source that 403s is loud —
fetcher.py already prints FAIL. A source that changes its page layout, or gets
dropped from the fetch, or has its listing frozen by the agency, looks exactly
like a normal day: the run goes green and the page just stops mentioning that
agency. Nobody notices for weeks.

  python health.py              # report, write health.json, exit non-zero if broken
  python health.py --report-only  # same report, always exit 0

Three checks, two severities. Only BROKEN sets a non-zero exit; QUIET is a
heads-up, because a false alarm on a daily automated check trains you to ignore
it.

  BROKEN  fetch error     fetcher.py could not retrieve the source this run
  BROKEN  not delivered   fetch ran, but nothing from this source reached the store
  QUIET   gone quiet      still delivering, but has published nothing in unusually long
"""
import argparse
import collections
import json
import os
import statistics
import sys
from datetime import date

import fetcher

STORE_PATH = "store.json"
FETCH_REPORT_PATH = "fetch_report.json"
HEALTH_PATH = "health.json"

# A source is "gone quiet" when its silence exceeds twice its own 90th-percentile
# publication gap. Per-source, because the sources are nothing like each other:
# OFAC's median gap between publications is 2 days, Fed SR/CA Letters' is 38 with
# a longest observed run of 387. A single fixed threshold either alarms constantly
# on the slow sources or never fires on the fast ones. Measured against the store
# on 2026-07-18, this rule flags nothing — every source sits well inside its own
# envelope — which is what a warning threshold should do on a healthy day.
QUIET_MULTIPLIER = 2

# Floor for the above. Without it, a fast, regular source like OFAC (p90 gap of 3
# days) would alarm after a single quiet week, which is a normal holiday lull.
QUIET_FLOOR_DAYS = 21

# Below this many dated records we have no basis for a per-source threshold and
# fall back to the floor alone.
MIN_HISTORY = 4


def active_sources():
    """Source names fetcher.py is currently configured to fetch.

    Read from fetcher.SOURCES rather than from the store on purpose. The store
    still holds SEC, FTC and CFTC items from when those were trialled and
    dropped; checking the store's agency list would report three permanently
    broken sources forever.
    """
    return sorted({source["agency"] for source, _ in fetcher.SOURCES})


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_date(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def source_history(store):
    """Per source, the set of publication dates we have seen from it.

    Only used to judge whether a source has gone unusually quiet. Deliberately
    NOT used to judge whether a source is still delivering: a record's `sources`
    list is cumulative — pipeline.py appends new agencies to it and never removes
    them — so an interagency item that FDIC keeps republishing would keep a dead
    FDIC FILs scraper looking alive indefinitely. Delivery is judged from
    fetch_report.json, which records what each source actually returned this run.
    """
    published = collections.defaultdict(set)
    last_seen = date.min
    for rec in store.values():
        pub = parse_date(rec.get("date"))
        seen = parse_date(rec.get("last_seen"))
        if seen and seen > last_seen:
            last_seen = seen
        if pub:
            for name in rec.get("sources") or []:
                published[name].add(pub)
    return published, (last_seen if last_seen > date.min else None)


def quiet_threshold(dates):
    """Days of silence tolerated for a source, from its own publishing rhythm."""
    if len(dates) < MIN_HISTORY:
        return QUIET_FLOOR_DAYS
    ordered = sorted(dates, reverse=True)
    gaps = sorted((ordered[i] - ordered[i + 1]).days for i in range(len(ordered) - 1))
    p90 = gaps[max(0, int(len(gaps) * 0.9) - 1)]
    return max(p90 * QUIET_MULTIPLIER, QUIET_FLOOR_DAYS)


def assess(store, fetch_report):
    published, last_seen = source_history(store)

    # Prefer the fetch's own timestamp; fall back to the store's newest last_seen
    # so running this by hand days later still evaluates the last real run rather
    # than reporting every source as silent.
    run_date = parse_date(fetch_report.get("fetched_at")) or last_seen or date.today()
    errors = {f["agency"]: f["error"] for f in fetch_report.get("failures", [])}
    counts = fetch_report.get("counts", {})
    # Without a fetch report there is no per-run attribution, so delivery cannot
    # be judged at all; fall back to the publication-gap check alone.
    have_counts = bool(fetch_report)

    findings = []
    for name in active_sources():
        dates = published.get(name, set())
        delivered = counts.get(name)
        entry = {
            "source": name,
            "items_this_run": delivered,
            "newest_publication": max(dates).isoformat() if dates else None,
            "records_in_store": len(dates),
        }

        if name in errors:
            entry.update(status="BROKEN", reason="fetch error", detail=errors[name])
        elif have_counts and not delivered:
            # The fetch did not raise, but returned nothing. This is the quiet
            # failure the whole check exists for — a changed page layout parses
            # to zero rows and looks like a normal day.
            entry.update(status="BROKEN", reason="not delivered",
                         detail="fetch returned 0 items")
        else:
            quiet_days = (run_date - max(dates)).days if dates else None
            limit = quiet_threshold(dates)
            entry["quiet_days"] = quiet_days
            entry["quiet_limit"] = limit
            if quiet_days is not None and quiet_days > limit:
                entry.update(status="QUIET", reason="gone quiet",
                             detail=f"nothing published in {quiet_days}d (expected within {limit}d)")
            else:
                entry.update(status="OK", reason="", detail="")

        findings.append(entry)

    # Sources that failed to fetch but are not in the configured list — i.e. one
    # was removed from fetcher.py while still erroring. Cheap to surface.
    for name in sorted(set(errors) - set(active_sources())):
        findings.append({
            "source": name, "status": "BROKEN", "reason": "fetch error",
            "detail": errors[name] + " (not in active source list)",
        })

    return run_date, findings


RANK = {"BROKEN": 0, "QUIET": 1, "OK": 2}


def report(run_date, findings):
    broken = [f for f in findings if f["status"] == "BROKEN"]
    quiet = [f for f in findings if f["status"] == "QUIET"]

    print(f"Source health for run of {run_date}\n")
    for f in sorted(findings, key=lambda f: (RANK[f["status"]], f["source"])):
        mark = {"BROKEN": "BROKEN", "QUIET": "QUIET ", "OK": "ok    "}[f["status"]]
        line = f"  {mark}  {f['source']:22}"
        if f["status"] == "OK":
            quiet_days = f.get("quiet_days")
            line += f"last published {quiet_days}d ago" if quiet_days is not None else ""
        else:
            line += f"{f['reason']}: {f['detail']}"
        print(line)

    print(f"\n{len(findings) - len(broken) - len(quiet)} ok, "
          f"{len(quiet)} quiet, {len(broken)} broken")
    if broken:
        print("\nA broken source stops appearing on the dashboard silently. "
              "Check the source URL by hand before assuming the parser is at fault.")
    return broken, quiet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true",
                    help="always exit 0; use when the report is being recorded, not gating")
    args = ap.parse_args()

    store = load_json(STORE_PATH, {})
    if not store:
        print(f"No {STORE_PATH} — run fetcher.py and pipeline.py first.")
        return 1

    fetch_report = load_json(FETCH_REPORT_PATH, {})
    if not fetch_report:
        print(f"note: no {FETCH_REPORT_PATH}, so fetch errors from this run are "
              f"not included. Staleness checks below are still valid.\n")

    run_date, findings = assess(store, fetch_report)
    broken, quiet = report(run_date, findings)

    with open(HEALTH_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "run_date": run_date.isoformat(),
            "status": "BROKEN" if broken else ("QUIET" if quiet else "OK"),
            "broken": len(broken),
            "quiet": len(quiet),
            "sources": findings,
        }, f, indent=2)

    return 1 if (broken and not args.report_only) else 0


if __name__ == "__main__":
    sys.exit(main())
