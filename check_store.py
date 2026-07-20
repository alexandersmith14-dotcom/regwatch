"""Refuse to push a store.json that would delete events.

store.json now has two authors. You classify locally, and since the CI secret was
fixed the Action classifies too and commits its own results. Git does not merge
JSON: when both sides have touched the file, one whole version wins. So a local
copy taken before a bot commit will silently drop whatever the bot added, and
nothing in git says so — the diff is 900 changed lines of reformatted JSON either
way.

That is not hypothetical. On 2026-07-20 a local store sat at 508 events while the
bot had classified one more to 509; pushing would have deleted an item the Action
had just paid for.

This compares the working-tree store against a git ref and fails if any event key
present there is missing here. Run by the pre-push hook; also runnable by hand:

    python check_store.py                 # against origin/main
    python check_store.py HEAD            # against the last commit

Deleting events is sometimes deliberate — forcing an item back through
classification to test CI, for instance. Say so explicitly:

    STORE_ALLOW_SHRINK=1 git push
"""
import json
import os
import subprocess
import sys

STORE_PATH = "store.json"
DEFAULT_REF = "origin/main"


def store_at(ref):
    """The store as of `ref`, or None if it isn't there / can't be read."""
    proc = subprocess.run(["git", "show", f"{ref}:{STORE_PATH}"],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REF

    # Compare against the remote as it actually is, not a stale cache.
    if ref == DEFAULT_REF:
        subprocess.run(["git", "fetch", "--quiet", "origin"], check=False)

    if not os.path.exists(STORE_PATH):
        print(f"check_store: no {STORE_PATH} in the working tree — skipping.")
        return 0

    theirs = store_at(ref)
    if theirs is None:
        print(f"check_store: no readable {STORE_PATH} at {ref} — skipping.")
        return 0

    with open(STORE_PATH, encoding="utf-8") as f:
        ours = json.load(f)

    missing = [k for k in theirs if k not in ours]
    if not missing:
        gained = len(ours) - len(theirs)
        print(f"check_store: OK — {len(ours)} events, "
              f"{gained:+d} vs {ref}, nothing dropped.")
        return 0

    if os.getenv("STORE_ALLOW_SHRINK"):
        print(f"check_store: {len(missing)} event(s) dropped, allowed by "
              f"STORE_ALLOW_SHRINK.")
        return 0

    print(f"\ncheck_store: REFUSING — this push would delete {len(missing)} "
          f"event(s) that exist at {ref}.\n")
    for key in missing[:10]:
        rec = theirs[key]
        who = ", ".join(rec.get("sources") or []) or "?"
        print(f"  [{who}] {rec.get('title', '(untitled)')[:64]}")
    if len(missing) > 10:
        print(f"  ... and {len(missing) - 10} more")

    print(f"\n  {ref}: {len(theirs)} events    yours: {len(ours)} events")
    print("\nAlmost always this means your copy predates a bot commit. Fix with:")
    print("    git stash            # if you have uncommitted work")
    print("    git fetch origin && git rebase origin/main")
    print("    git checkout origin/main -- store.json   # take the newer store")
    print("\nIf the deletion is deliberate:  STORE_ALLOW_SHRINK=1 git push")
    return 1


if __name__ == "__main__":
    sys.exit(main())
