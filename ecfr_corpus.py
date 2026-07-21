"""Build a searchable corpus of the actual regulation text from the eCFR API.

The eCFR (ecfr.gov) publishes Title 12 — the federal banking/consumer-finance
regulations — as structured XML through a free public API, no key required. This
pulls a curated set of parts, splits them into sections, and writes corpus.json:
one clean, citable record per section.

  python ecfr_corpus.py            # build corpus.json for the parts below
  python ecfr_corpus.py 1002 1026  # just these parts

This is the "what the rule says" half of the assistant. RegWatch's store.json is
the "what changed recently" half; they are combined at query time, not here.
"""
import json
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

# eCFR "full" endpoint needs a concrete date, not "current". This is the point-in
# -time the corpus reflects; bump it to refresh. (A compliance answer should say
# which date it is grounded in — the assistant surfaces this.)
AS_OF = "2026-06-01"
FULL = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-12.xml?part={part}"

# Curated Title-12 parts, mapped to the Regulation letter a banker actually says.
# Kept to the consumer-compliance core for the first build; Fed prudential parts
# (217 capital, 228 CRA) and the larger Reg Z (1026) can be added once the
# pipeline is proven.
PARTS = {
    "1002": "Regulation B — Equal Credit Opportunity Act (fair lending)",
    "1005": "Regulation E — Electronic Fund Transfer Act",
    "1030": "Regulation DD — Truth in Savings",
}

TAG = re.compile(r"<[^>]+>")
DIV8 = re.compile(r'<DIV8\b[^>]*\bN="([^"]+)"[^>]*>(.*?)</DIV8>', re.S)
HEAD = re.compile(r"<HEAD>(.*?)</HEAD>", re.S)


def text_of(xml_fragment):
    # eCFR text uses <I>, <P>, entities; strip to readable plain text.
    from html import unescape
    return " ".join(unescape(TAG.sub(" ", xml_fragment)).split())


def fetch_part(part):
    url = FULL.format(date=AS_OF, part=part)
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60
    ).read().decode("utf-8", "ignore")


def build(parts):
    corpus = []
    for part in parts:
        reg_name = PARTS.get(part, f"12 CFR Part {part}")
        xml = fetch_part(part)
        sections = 0
        for n, body in DIV8.findall(xml):
            head = HEAD.search(body)
            heading = text_of(head.group(1)) if head else f"§ {n}"
            # Section text is everything after the heading.
            after = body[head.end():] if head else body
            text = text_of(after)
            if not text:
                continue
            corpus.append({
                "id": f"12cfr{n}",
                "citation": f"12 CFR {n}",
                "part": part,
                "reg_name": reg_name,
                "heading": heading,
                "text": text,
                "as_of": AS_OF,
            })
            sections += 1
        print(f"  Part {part:5} {reg_name[:38]:40} {sections} sections")
    return corpus


def main():
    parts = sys.argv[1:] or list(PARTS)
    corpus = build(parts)
    with open("corpus.json", "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2)
    chars = sum(len(c["text"]) for c in corpus)
    print(f"\n{len(corpus)} sections, {chars:,} chars -> corpus.json (as of {AS_OF})")


if __name__ == "__main__":
    main()
