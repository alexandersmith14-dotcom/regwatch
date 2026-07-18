# RegWatch — handoff

Paste this into a new chat, or point Claude at this file.

**Project:** `C:\Users\alexa\RegWatch`
**Live:** https://alexandersmith14-dotcom.github.io/regwatch/
**Repo:** https://github.com/alexandersmith14-dotcom/regwatch (public)

---

## What it is

A regulatory tracker for community banks and fintechs, built by Alexander Smith
(CRCM, CFE — Risk Advisory Services, Kaufman Rossin) as a free public tool for
business development on LinkedIn. Firm approval obtained.

It watches 14 federal sources daily, deduplicates interagency republication, uses
Claude to judge relevance and write plain-English summaries, matches Federal
Register records for real comment deadlines, and publishes one self-contained
HTML page.

**State: finished and running.** Nothing is half-built.

    508 events tracked · 228 relevant · 49 fintech-specific · 78 with deadlines

---

## How it runs

GitHub Actions, `.github/workflows/update.yml`:
- **06:30 UTC daily**, on push to main, or manually from the Actions tab
- Steps: `fetcher.py` → `pipeline.py` → `deadlines.py` → `dashboard.py` → deploy
- API key is the `ANTHROPIC_API_KEY` repo secret
- Cost: a few cents a day; nothing on days with no new items

Locally the same four commands work in that order. `.env` holds the key and is
gitignored.

---

## Files

| File | Role |
|---|---|
| `fetcher.py` | 14 sources: RSS, Federal Register API, scraped tables, scraped Drupal lists |
| `dedupe.py` | Cross-agency clustering; key is sha1(normalized title + date) |
| `classifier.py` | Relevance + fintech judgment + summaries. `classify()` is importable |
| `pipeline.py` | Dedupe + classify only what's new. `--dry-run`, `--backfill FIELD` |
| `deadlines.py` | Matches Federal Register records for comment/effective dates |
| `dashboard.py` | Builds `dashboard.html` |
| `health.py` | Per-source health check. `--report-only` to never exit non-zero |
| `regref.py` | Fed regulation A–YY lookup table (47 entries) |
| `make_og_image.py` | Regenerates the LinkedIn preview card |
| `store.json` | **The memory — 508 analysed events. Do not delete.** |

---

## Decisions worth not re-litigating

- **Dedupe only merges across different agencies.** Same-agency merging collapsed
  three distinct OFAC Iran actions and two different CFPB ECOA rules.
- **Store key includes the date.** Title alone collapsed 18 "Sunshine Act
  Meetings" into one and silently dropped the whole beneficial-ownership sequence.
- **SEC, FTC and CFTC were added, measured at 0/10 relevant, and dropped.**
  Reasons are recorded in `fetcher.py`. Don't re-add without measuring.
- **NYDFS and California DFPI are not scraped.** Both block automated access
  including real browsers. Alexander subscribed to their email alerts instead —
  the sanctioned route. Do not add stealth/anti-detection.
- **Search matches at word starts; terms ≤2 chars must match a whole word.**
  Two bugs came from being looser: "gg" matched "trigger", "regulation d" matched
  "data"/"disparate". Don't relax this.
- **Relevance is a lens, not a gate.** The Relevant/Everything toggle exists
  because one profile can't serve a public audience.
- **The reg reference table carries no commentary**, and unverified entries (AA,
  JJ, SS, UU, ZZ) were removed rather than published with a caveat.
- **Source health is judged from `fetch_report.json`, not from `store.json`.**
  The obvious approach — per-source `last_seen` in the store — is wrong. A
  record's `sources` list is cumulative and never pruned, so an interagency item
  that FDIC keeps republishing keeps a dead FDIC FILs scraper looking alive
  forever. Fault-injection caught this; it silently defeated the whole check.
- **Quiet thresholds are per-source, derived from each source's own history**
  (2 × its 90th-percentile publication gap, floored at 21 days). Measured across
  all 14: OFAC's median gap is 2 days, Fed SR/CA Letters' is 38 with a 387-day
  maximum. Any fixed threshold nags or misses. Verified to flag nothing on a
  healthy day.
- **Only BROKEN fails the run; QUIET does not.** A daily automated check that
  cries wolf is one you learn to ignore.

---

## Parked, ready to go

**Historical backfill** — ~1,450 rules and proposed rules back to 2018 across six
agencies, about **$16** one-off, then unchanged daily cost. Two switches in
`fetcher.py`, both off:

    ARCHIVE_ENABLED = False        # the 2018 backfill
    FEDREG_AGENCIES_PENDING        # recent Federal Register window for FDIC/OCC/Fed/CFPB (~$4)

Deliberately restricted to `RULE` and `PRORULE` — without that filter it is 6,450
documents and $71, and the extra 5,000 are routine notices. Full detail in
`README.md`. Expect 90–120 minutes; run locally, not through the Action.

---

## Working agreements

- **Ask before any API spend.** Use `pipeline.py --dry-run` to price it first.
- **Plain language.** Alexander is an audit professional, not a developer.
- **Verify, don't assert.** He has caught two real search bugs; check claims
  against the data before stating them.
- **Answer briefly.** Direct answer first.

---

## Next up when he returns

He is letting it run for some days before tuning. Likely topics:

1. ~~Whether any source silently broke~~ — done. `health.py` runs after each
   deploy and turns the run red (which emails him) if a source stops delivering.
   All 14 verified healthy on 2026-07-18.
2. Whether the relevance judgment matches his — currently 228 of 508
3. The historical backfill
4. The LinkedIn launch post (a draft exists; update the deadlines in it before
   posting, and refresh the preview via LinkedIn Post Inspector)
