import feedparser
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

# Several agency sites (CSBS, OFAC) reject non-browser User-Agents with a 403,
# so present as a browser rather than as "RegWatch".
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# How many items to take from each source. None = take everything the source
# lists, which varies a lot: OFAC shows 10, FinCEN Advisories 76, NCUA Press 60.
# Taking everything gives deeper history and more slack between runs — a source
# only loses items once they scroll off its own listing page.
PER_SOURCE = None

# The Federal Register API needs a real number for per_page; it won't accept
# "everything". 100 is well past what these agencies publish in a year.
FEDREG_PER_PAGE = 100


def cap(items):
    """Apply PER_SOURCE if one is set."""
    return items if PER_SOURCE is None else items[:PER_SOURCE]

# ---------------------------------------------------------------- RSS sources

RSS_FEEDS = [
    {"agency": "FDIC", "url": "https://public.govdelivery.com/topics/USFDIC_26/feed.rss"},
    {"agency": "OCC", "url": "https://www.occ.gov/rss/occ_news.xml"},
    {"agency": "OCC Bulletins", "url": "https://www.occ.gov/rss/occ_bulletins.xml"},
    {"agency": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    # SR/CA letters — the Fed's supervisory guidance channel. Titles are bare
    # codes ("SR 26-3"); the real subject line is in the summary field.
    {"agency": "Fed SR/CA Letters", "url": "https://www.federalreserve.gov/feeds/bankinginfo-rss.xml"},
    {"agency": "CFPB", "url": "https://www.consumerfinance.gov/about-us/newsroom/feed/"},
    {"agency": "CFPB Rules", "url": "https://www.consumerfinance.gov/rules-policy/final-rules/feed/"},
]

# Dropped after measuring keep-rate — all three were pure classification cost:
#   SEC  (news/pressreleases.rss)     0 of 10 relevant
#   FTC  (feeds/press-release.xml)    0 of 10 relevant — antitrust, Made-in-USA
#                                     claims, tenant-screening FCRA; adjacent to
#                                     consumer protection but not to banks/fintechs
#   CFTC (PressRoom/PressReleases)    0 of 10 relevant — commodity swaps, margin
#                                     rules, agricultural advisory committees. Was
#                                     added specifically to chase crypto
#                                     derivatives; that slice never showed up.
# Not reachable: FFIEC and NYDFS return 403 to all server-side requests (edge bot
# protection, not a User-Agent issue). Both would need a headless browser.

# ------------------------------------------------- Federal Register API sources

FEDREG_AGENCIES = [
    {"agency": "FinCEN", "slug": "financial-crimes-enforcement-network"},
    {"agency": "NCUA", "slug": "national-credit-union-administration"},
]

# ------------------------------------------------------ Scraped HTML <table>s

HTML_TABLES = [
    {
        "agency": "FinCEN Advisories",
        "url": "https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets",
        "base": "https://www.fincen.gov",
        "title_col": 0,
        "date_col": 1,
        "desc_col": 2,
    },
    {
        "agency": "NCUA Press",
        "url": "https://ncua.gov/news/press-releases",
        "base": "https://ncua.gov",
        "title_col": 0,
        "date_col": 2,
        "desc_col": 1,  # NCUA's middle column is a category, not a description
    },
]

# ------------------------------------------- Scraped Drupal "views-row" lists
# FDIC FILs are the FDIC's primary supervisory channel to community banks and
# never appear in its press-release feed. OFAC publishes no feed at all.
# link_filter keeps us on real content links and drops nav/sidebar noise.

VIEWS_ROW_PAGES = [
    {
        "agency": "FDIC FILs",
        "url": "https://www.fdic.gov/news/financial-institution-letters/index.html",
        "base": "https://www.fdic.gov",
        "link_filter": "/news/financial-institution-letters/",
    },
    {
        "agency": "OFAC",
        "url": "https://ofac.treasury.gov/recent-actions",
        "base": "https://ofac.treasury.gov",
        "link_filter": "/recent-actions/2",
    },
    {
        "agency": "CSBS",
        "url": "https://www.csbs.org/newsroom",
        "base": "https://www.csbs.org",
        "link_filter": "/newsroom/",
    },
]

# ---------------------------------------------------------------- HTML helpers

TAG = re.compile(r"<[^>]+>")
LINK = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
TIME = re.compile(r'<time[^>]*datetime="([^"]{10})', re.I)
TEXTDATE = re.compile(r"([A-Z][a-z]{2,8})\s+(\d{1,2}),\s*(\d{4})")


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def text_of(html):
    return " ".join(unescape(TAG.sub(" ", html)).split())


class TableRowParser(HTMLParser):
    """Collects <tbody> rows from every <table> on a page.

    Each row is {"cells": [...], "url": first <a> href, "datetime": <time>}.
    Some FinCEN tables use <time>, others plain MM/DD/YYYY text, so capture both
    and let the caller prefer whichever exists.
    """

    def __init__(self):
        super().__init__()
        self.rows = []
        self.in_tbody = False
        self.in_cell = False
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.row = {"cells": [], "url": "", "datetime": ""}
        elif tag == "td" and self.row is not None:
            self.in_cell = True
            self.cell = []
        elif tag == "a" and self.in_cell and not self.row["url"]:
            self.row["url"] = a.get("href", "")
        elif tag == "time" and self.in_cell and not self.row["datetime"]:
            self.row["datetime"] = a.get("datetime", "")

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.in_tbody = False
        elif tag == "td" and self.in_cell:
            self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            if self.row["cells"]:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)


def parse_table_date(row, date_col):
    """Return (sort_key, display). Undated rows sort last."""
    raw = row["datetime"][:10] if row["datetime"] else ""
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d"), raw
        except ValueError:
            pass
    text = row["cells"][date_col] if date_col < len(row["cells"]) else ""
    try:
        dt = datetime.strptime(text, "%m/%d/%Y")
        return dt, dt.strftime("%Y-%m-%d")
    except ValueError:
        return datetime.min, text or "unknown"


def parse_chunk_date(chunk):
    """Date from a views-row chunk: <time datetime> first, else 'July 17, 2026'."""
    m = TIME.search(chunk)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d"), m.group(1)
        except ValueError:
            pass
    m = TEXTDATE.search(text_of(chunk))
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                dt = datetime.strptime(" ".join(m.groups()), fmt)
                return dt, dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.min, "unknown"


# ------------------------------------------------------------------- fetchers


def fetch_rss(source):
    # feedparser sends its own User-Agent by default, which FTC rejects with a 403.
    parsed = feedparser.parse(source["url"], agent=UA["User-Agent"])
    status = parsed.get("status")
    if status and status >= 400:
        raise RuntimeError(f"HTTP {status}")
    if not parsed.entries:
        raise RuntimeError("feed returned 0 entries")
    return [
        {
            "agency": source["agency"],
            "title": e.get("title", ""),
            "url": e.get("link", ""),
            "date": e.get("published", ""),
            # Some feeds (notably FDIC's GovDelivery) ship the entire HTML email
            # template as the summary — tens of KB of boilerplate per item. Strip
            # tags and cap it so the classifier sees content, not markup.
            "summary": text_of(e.get("summary", ""))[:1500],
            "source_type": "rss",
        }
        for e in cap(parsed.entries)
    ]


def fetch_fedreg(source):
    query = {
        "conditions[agencies][]": source["slug"],
        "order": "newest",
        "per_page": str(FEDREG_PER_PAGE),
        "fields[]": ["title", "publication_date", "type", "html_url", "abstract"],
    }
    url = "https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(
        query, doseq=True
    )
    data = json.loads(get(url, timeout=45))
    if not data.get("results"):
        raise RuntimeError("API returned 0 results")
    return [
        {
            "agency": source["agency"],
            "title": d.get("title", ""),
            "url": d.get("html_url", ""),
            "date": d.get("publication_date", ""),
            "summary": d.get("abstract") or "",
            "doc_type": d.get("type", ""),
            "source_type": "federal_register",
        }
        for d in data["results"]
    ]


def fetch_table(source):
    parser = TableRowParser()
    parser.feed(get(source["url"]))
    if not parser.rows:
        raise RuntimeError("no table rows found (page layout may have changed)")

    items = []
    for row in parser.rows:
        cells = row["cells"]
        if source["title_col"] >= len(cells):
            continue
        title = cells[source["title_col"]].replace("PDF Only", "").strip()
        # Spanish editions duplicate an English item we already have.
        if title.endswith(" Spanish"):
            continue
        sort_key, date_str = parse_table_date(row, source["date_col"])
        desc = cells[source["desc_col"]] if source["desc_col"] < len(cells) else ""
        items.append(
            (
                sort_key,
                {
                    "agency": source["agency"],
                    "title": title,
                    "url": urllib.parse.urljoin(source["base"], row["url"]),
                    "date": date_str,
                    "summary": desc,
                    "source_type": "scraped_table",
                },
            )
        )
    if not items:
        raise RuntimeError("rows found but none had a usable title column")
    items.sort(key=lambda p: p[0], reverse=True)
    return cap([x for _, x in items])


def fetch_views_rows(source):
    """Scrape a Drupal listing page that renders results as views-rows.

    Chunks the page on views-row boundaries and takes the longest matching link
    as the title. Chunks with no matching link are dropped, which conveniently
    also discards nested-row fragments and sidebar blocks.
    """
    html = get(source["url"])
    marks = [m.start() for m in re.finditer(r'class="[^"]*views-row', html)]
    if not marks:
        raise RuntimeError("no views-row blocks found (page layout may have changed)")

    filt = source.get("link_filter")
    items, seen = [], set()
    for chunk in (html[a:b] for a, b in zip(marks, marks[1:] + [len(html)])):
        links = [
            (h, text_of(t))
            for h, t in LINK.findall(chunk)
            if text_of(t) and (filt is None or filt in h)
        ]
        if not links:
            continue
        href, title = max(links, key=lambda p: len(p[1]))
        url = urllib.parse.urljoin(source["base"], href)
        if url in seen:
            continue
        seen.add(url)
        sort_key, date_str = parse_chunk_date(chunk)
        # Chunks start mid-attribute (inside the opening tag), so drop everything
        # up to that tag's closing '>' before extracting text — otherwise the
        # attribute fragment survives tag-stripping and pollutes the summary.
        body = chunk[chunk.find(">") + 1 :] if ">" in chunk else chunk
        # Same problem at the tail: the chunk ends wherever the next views-row
        # begins, which can be mid-tag. Drop any unterminated trailing tag.
        body = re.sub(r"<[^>]*$", "", body)
        summary = text_of(body).replace(title, "", 1).strip()[:300]
        items.append(
            (
                sort_key,
                {
                    "agency": source["agency"],
                    "title": title,
                    "url": url,
                    "date": date_str,
                    "summary": summary,
                    "source_type": "scraped_list",
                },
            )
        )
    if not items:
        raise RuntimeError("views-rows found but none matched link_filter")
    items.sort(key=lambda p: p[0], reverse=True)
    return cap([x for _, x in items])


# ----------------------------------------------------------------------- main

SOURCES = (
    [(s, fetch_rss) for s in RSS_FEEDS]
    + [(s, fetch_fedreg) for s in FEDREG_AGENCIES]
    + [(s, fetch_table) for s in HTML_TABLES]
    + [(s, fetch_views_rows) for s in VIEWS_ROW_PAGES]
)

def main():
    results, failures = [], []

    for source, fetch in SOURCES:
        try:
            items = fetch(source)
            results.extend(items)
            print(f"  OK    {source['agency']:20} {len(items)} items")
        except Exception as e:
            failures.append((source["agency"], str(e)))
            print(f"  FAIL  {source['agency']:20} {e}")

    with open("updates.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(
        f"\n{len(results)} updates from {len(SOURCES) - len(failures)} of "
        f"{len(SOURCES)} sources -> updates.json"
    )

    if failures:
        print(f"\nWARNING: {len(failures)} source(s) failed:")
        for agency, err in failures:
            print(f"  - {agency}: {err}")


# Guarded so other modules (browser_fetcher) can reuse TableRowParser / text_of
# without triggering a full fetch on import.
if __name__ == "__main__":
    main()
