"""Cluster updates that describe the same underlying event across agencies.

Interagency actions get published simultaneously by FDIC, OCC, the Fed and NCUA,
and often again as a bulletin or FIL with different wording. Without clustering
we pay to classify the same action 4-5 times and it appears 4-5 times in a digest.

Pure functions, no API calls — safe to import and cheap to test.
"""
import hashlib
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

# Words that carry no distinguishing signal for matching.
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in",
    "is", "its", "of", "on", "or", "that", "the", "to", "with", "will", "not",
    "press", "release", "announces", "announce", "announced", "issues", "issue",
    "issued", "agencies", "agency", "federal", "board", "statement", "new",
}

# Leading labels some feeds prepend to an otherwise identical title.
PREFIX = re.compile(
    r"^\s*(press release|news release|bulletin|financial institution letter"
    r"|fil-\d+-\d{4}|sr \d+-\d+|ca \d+-\d+)\s*[:\-]\s*",
    re.I,
)


def normalize(title):
    t = PREFIX.sub("", title or "")
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return " ".join(t.split())


def tokens(title):
    return {w for w in normalize(title).split() if w not in STOP and len(w) > 2}


def parse_any_date(value):
    """Best-effort date parse across the formats our sources emit."""
    if not value or value == "unknown":
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value[:len(fmt) + 6].strip(), fmt)
        except ValueError:
            pass
    try:  # RSS pubDate, e.g. "Thu, 16 Jul 2026 18:00:00 GMT"
        return parsedate_to_datetime(value).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def similarity(a, b):
    """Jaccard overlap of significant title tokens."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def event_key(title, date=""):
    """Stable id for a cluster, from its normalized title AND date.

    The date is load-bearing, not decoration. Keying on title alone collapsed
    every recurring notice into a single store entry — NCUA publishes "Sunshine
    Act Meetings" most months, and all 18 occurrences overwrote each other. The
    date keeps genuinely separate events separate while staying stable for the
    same event across runs.
    """
    return hashlib.sha1(f"{normalize(title)}|{date}".encode("utf-8")).hexdigest()[:16]


def cluster(items, threshold=0.5, max_days_apart=14, min_shared=4):
    """Group items describing the same event.

    Merging is deliberately restricted to items from *different* agencies. The
    duplication we care about is interagency republication (a joint action posted
    by FDIC, OCC, the Fed and NCUA at once). Two posts from the same agency are
    almost always genuinely different items — OFAC publishes several distinct
    Iran actions in a week, and CFPB's ECOA small-business rule is not its ECOA
    disparate-impact rule. Allowing same-agency merges collapsed all of those.

    `min_shared` guards short or opaque titles ("SR 94-22 (FIS)", "FIN-2026-NTC1")
    where a couple of incidental tokens produce a spuriously high overlap ratio.

    Returns a list of clusters, each: {key, title, date, sources[], items[]}.
    """
    clusters = []
    for item in items:
        item_date = parse_any_date(item.get("date"))
        placed = False

        for c in clusters:
            if item["agency"] in c["sources"]:
                continue
            if len(tokens(item["title"]) & tokens(c["title"])) < min_shared:
                continue
            if similarity(item["title"], c["title"]) < threshold:
                continue
            if item_date and c["_date"]:
                if abs((item_date - c["_date"]).days) > max_days_apart:
                    continue
            c["items"].append(item)
            if item["agency"] not in c["sources"]:
                c["sources"].append(item["agency"])
            # Prefer the longest title, ignoring feed prefixes like "Press Release:"
            # so the representative reads cleanly in a digest.
            if len(PREFIX.sub("", item["title"])) > len(PREFIX.sub("", c["title"])):
                c["title"] = PREFIX.sub("", item["title"])
            placed = True
            break

        if not placed:
            clusters.append(
                {
                    "key": event_key(item["title"], item.get("date", "")),
                    "title": PREFIX.sub("", item["title"]).strip(),
                    "_date": item_date,
                    "sources": [item["agency"]],
                    "items": [item],
                }
            )

    # Recompute keys from the final (possibly updated) representative title, and
    # expose a display date.
    for c in clusters:
        # Date string must be resolved before the key, which now depends on it.
        c["date"] = c["_date"].strftime("%Y-%m-%d") if c["_date"] else "unknown"
        c["key"] = event_key(c["title"], c["date"])
        del c["_date"]
    return clusters


def representative(c):
    """The item a cluster should be classified from: the one with the most text."""
    return max(c["items"], key=lambda i: len(i.get("summary") or ""))
