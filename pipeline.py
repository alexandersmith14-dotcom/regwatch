"""RegWatch pipeline: dedupe -> classify only what's new -> report.

Run `python fetcher.py` first to refresh updates.json, then this.

Keeps a persistent store (store.json) keyed by event. An event already in the
store is never re-classified, so a daily run costs only for genuinely new items
instead of re-billing the whole window every time.

  python pipeline.py            # classify new events, update store, print digest
  python pipeline.py --dry-run  # show what WOULD be classified and the cost, spend nothing
  python pipeline.py --limit 5  # classify at most 5 new events this run
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import dedupe

STORE_PATH = "store.json"
UPDATES_PATH = "updates.json"

# Rough per-item cost at current model/effort settings, for the dry-run estimate.
EST_COST_PER_ITEM = 0.011


def load_store():
    if not os.path.exists(STORE_PATH):
        return {}
    with open(STORE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_store(store):
    # Write to a temp file then replace, so an interrupted run can't corrupt the
    # store and lose the classification history we've already paid for.
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp, STORE_PATH)


def backfill(field, dry_run=False, limit=None):
    """Re-classify stored relevant items that are missing a field.

    Used after changing classifier.py — existing records keep their old shape
    otherwise, and a new field would only ever appear on future items. Only
    relevant items are touched: filtered-out ones never reach a report, so
    paying to re-judge them is waste.
    """
    store = load_store()
    targets = [r for r in store.values() if r.get("relevant") and field not in r]
    if limit:
        targets = targets[:limit]

    print(f"{len(targets)} relevant item(s) missing '{field}'")
    if dry_run:
        print(f"DRY RUN — would re-classify {len(targets)} (~${len(targets)*EST_COST_PER_ITEM:.2f})")
        return 0
    if not targets:
        return 0

    import classifier

    changed = 0
    for i, rec in enumerate(targets, 1):
        item = {
            "agency": (rec.get("sources") or ["?"])[0],
            "title": rec.get("title", ""),
            "date": rec.get("date", ""),
            "summary": rec.get("plain_english", ""),
            "doc_type": rec.get("update_type", ""),
        }
        try:
            fresh = classifier.classify(item)
        except Exception as e:
            print(f"[{i}/{len(targets)}] FAILED: {e}")
            continue
        # Only take the new field and the rewritten summary; leave dates, sources
        # and deadline data alone — those came from sources, not the model.
        rec[field] = fresh.get(field)
        if fresh.get("plain_english"):
            rec["plain_english"] = fresh["plain_english"]
        changed += 1
        if i % 10 == 0 or i == len(targets):
            print(f"[{i}/{len(targets)}] ...")
            save_store(store)

    save_store(store)
    yes = sum(1 for r in store.values() if r.get(field) is True)
    print(f"\n{changed} updated. {yes} now have {field}=true")
    return 0


def refresh_dates(dry_run=False):
    """Re-read `date` for stored events from the current fetch. Costs nothing.

    Dates are frozen at first classification: main() refreshes `last_seen` and
    `sources` for events it has seen before, but never `date`. So when a parsing
    fix teaches the fetcher to read a date it previously could not, existing
    records keep the old wrong value forever. That is how sixteen FinCEN
    reference documents sat at the very top of the dashboard — their date was
    the string "unknown", which sorts above "2026" — long after the fetcher
    could read them.

    Re-keying is the awkward part. The store key is sha1(normalized title|date),
    so correcting a date necessarily changes the key. Without moving the record
    to its new key the next run treats it as a brand new event, pays to classify
    it again, and leaves the stale one behind as a duplicate.

    Matched on normalized title, since the key itself is what is changing. That
    match is deliberately hemmed in on two sides, because a loose version of it
    is destructive:

    1. Only titles that appear EXACTLY ONCE in the current fetch. Recurring
       titles are common — NCUA posts "Sunshine Act Meetings" most months — and
       a title-only match maps all of them onto one date, which then re-keys
       every occurrence to the same key and overwrites all but one. That is the
       bug that once collapsed eighteen Sunshine Act notices into a single
       entry; the first draft of this function reproduced it exactly, touching
       88 records instead of 16.
    2. Only records whose stored date cannot be parsed at all. This function
       repairs unreadable dates; it does not second-guess dates that already
       work. A stored 2026-07-02 differing from a same-titled item dated
       2026-05-05 means they are probably two separate events, not one wrong
       one.
    """
    with open(UPDATES_PATH, encoding="utf-8") as f:
        updates = json.load(f)

    seen = {}
    for c in dedupe.cluster(updates):
        seen.setdefault(dedupe.normalize(c["title"]), []).append(c["date"])
    # Ambiguous titles are dropped entirely rather than resolved by guesswork.
    current = {t: dates[0] for t, dates in seen.items() if len(dates) == 1}
    ambiguous = len(seen) - len(current)

    store = load_store()
    changes, skipped = [], 0
    for key, rec in list(store.items()):
        title = rec.get("title", "")
        old = rec.get("date", "")
        if dedupe.parse_any_date(old) is not None:
            continue                      # already a usable date, leave it alone
        if dedupe.normalize(title) in seen and dedupe.normalize(title) not in current:
            skipped += 1                  # recurring title, cannot match safely
            continue
        fresh = current.get(dedupe.normalize(title))
        if not fresh or fresh == old or fresh == "unknown":
            continue
        new_key = dedupe.event_key(title, fresh)
        changes.append((key, new_key, old, fresh, title))

    print(f"{ambiguous} recurring title(s) in this fetch, not eligible for matching")
    if skipped:
        print(f"{skipped} undated record(s) skipped — title recurs, no safe match")

    print(f"{len(changes)} record(s) with a corrected date")
    for _, _, old, fresh, title in changes[:20]:
        print(f"  {old:12} -> {fresh:12}  {title[:52]}")
    if len(changes) > 20:
        print(f"  ... and {len(changes) - 20} more")

    if dry_run:
        print("\nDRY RUN — nothing written. No API cost either way.")
        return 0
    if not changes:
        return 0

    collisions = 0
    for key, new_key, _, fresh, _ in changes:
        rec = store.pop(key)
        rec["date"] = fresh
        rec["key"] = new_key
        # A record already sitting on the target key means the same event is in
        # the store twice under two dates. Keep the one we just corrected.
        if new_key in store:
            collisions += 1
        store[new_key] = rec

    save_store(store)
    print(f"\n{len(changes)} updated, {collisions} duplicate(s) merged. "
          f"{len(store)} in store.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show what would be classified, spend nothing")
    ap.add_argument("--limit", type=int, help="classify at most N new events")
    ap.add_argument("--backfill", metavar="FIELD",
                    help="re-classify stored RELEVANT items that lack FIELD "
                         "(use after changing the classifier, e.g. --backfill fintech_specific)")
    ap.add_argument("--refresh-dates", action="store_true",
                    help="re-read dates from the current fetch for stored events "
                         "and re-key them (use after a date parsing fix; costs nothing)")
    args = ap.parse_args()

    if args.refresh_dates:
        return refresh_dates(dry_run=args.dry_run)

    if args.backfill:
        return backfill(args.backfill, dry_run=args.dry_run, limit=args.limit)

    with open(UPDATES_PATH, encoding="utf-8") as f:
        updates = json.load(f)

    clusters = dedupe.cluster(updates)
    store = load_store()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new = [c for c in clusters if c["key"] not in store]
    seen = [c for c in clusters if c["key"] in store]

    print(f"{len(updates)} items -> {len(clusters)} events "
          f"({len(updates) - len(clusters)} duplicates merged)")
    print(f"{len(seen)} already classified, {len(new)} new")

    # Refresh source lists on events we've seen before — a later agency may have
    # republished something we first saw elsewhere. No API cost.
    for c in seen:
        rec = store[c["key"]]
        rec["last_seen"] = now
        for s in c["sources"]:
            if s not in rec["sources"]:
                rec["sources"].append(s)

    if args.limit:
        new = new[: args.limit]

    if args.dry_run:
        print(f"\nDRY RUN — would classify {len(new)} events "
              f"(~${len(new) * EST_COST_PER_ITEM:.2f})")
        for c in new[:20]:
            print(f"  [{', '.join(c['sources'])}] {c['title'][:66]}")
        if len(new) > 20:
            print(f"  ... and {len(new) - 20} more")
        return

    if not new:
        print("\nNothing new to classify.")
        save_store(store)
        return

    # Imported here so --dry-run works without an API key present.
    import classifier

    failures = []
    for i, c in enumerate(new, 1):
        rep = dedupe.representative(c)
        print(f"[{i}/{len(new)}] {c['title'][:58]}...")
        try:
            parsed = classifier.classify(rep)
        except Exception as e:
            failures.append((c["title"][:60], str(e)))
            print(f"    FAILED: {e}")
            continue

        parsed.update(
            {
                "key": c["key"],
                "title": c["title"],
                "date": c["date"],
                "sources": c["sources"],
                "url": rep["url"],
                "first_seen": now,
                "last_seen": now,
            }
        )
        store[c["key"]] = parsed
        # Save as we go — a crash 90 items in shouldn't discard the spend.
        save_store(store)

    save_store(store)

    fresh = [store[c["key"]] for c in new if c["key"] in store]
    relevant = [r for r in fresh if r["relevant"]]
    print(f"\n{len(fresh)} newly classified, {len(relevant)} relevant "
          f"({len(store)} total in store)")

    for level in ("High", "Medium"):
        batch = [r for r in relevant if r["urgency"] == level]
        if not batch:
            continue
        print(f"\n--- {level.upper()} URGENCY ({len(batch)}) ---")
        for r in batch:
            print(f"  {r['title'][:70]}")
            print(f"    {', '.join(r['sources'])} | {r['date']} | {r['update_type']}")
            print(f"    {r['plain_english'][:160]}")

    if failures:
        print(f"\nWARNING: {len(failures)} failed:")
        for title, err in failures:
            print(f"  - {title}: {err}")


if __name__ == "__main__":
    sys.exit(main())
