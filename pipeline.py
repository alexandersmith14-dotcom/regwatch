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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show what would be classified, spend nothing")
    ap.add_argument("--limit", type=int, help="classify at most N new events")
    ap.add_argument("--backfill", metavar="FIELD",
                    help="re-classify stored RELEVANT items that lack FIELD "
                         "(use after changing the classifier, e.g. --backfill fintech_specific)")
    args = ap.parse_args()

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
