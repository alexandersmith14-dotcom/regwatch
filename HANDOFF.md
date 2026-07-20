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
| `pipeline.py` | Dedupe + classify only what's new. `--dry-run`, `--backfill FIELD`, `--refresh-dates` |
| `deadlines.py` | Matches Federal Register records for comment/effective dates |
| `dashboard.py` | Builds `dashboard.html` |
| `health.py` | Per-source health check. `--report-only` to never exit non-zero |
| `check_store.py` | Blocks a push that would delete events. Run by `.githooks/pre-push` |
| `regref.py` | Fed regulation A–YY lookup table (47 entries) |
| `make_og_image.py` | Regenerates the LinkedIn preview card |
| `make_icons.py` | Regenerates favicon, home-screen icons and `site.webmanifest` |
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
  because one profile can't serve a public audience. The buttons are labelled
  **Banks & fintechs / Fintech only / Everything** with live counts; "Relevant
  only" was self-referential — relevant to whom?
- **Do not split the view into "Community banks" vs "Fintechs".** Measured, not
  assumed: a `bank_specific` judgment was added to the classifier and sampled
  over 25 relevant items for $0.27. **24 of 25 came back true (96%)**, and of the
  4 fintech items every one was *also* bank-specific — "fintech only" was empty.
  A Community banks button would therefore show ~220 of 229 and be
  indistinguishable from the default. The two are not independent axes; fintech
  is a subset of bank. The field was removed again rather than kept unused. The
  remaining ~$2.25 of backfill was not spent.
- **Topic pills were removed.** BSA/AML matched 151 of 228 relevant items (66%),
  which is a smaller "All" rather than a filter; Lending and Enforcement were
  plain keyword matches the search box already does. Fintech survived because it
  reads the classifier's judgment: searching "fintech" returns 63 where the
  classifier finds 48, agreeing on only 31.
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
- **"Phone" is not a width.** A phone in landscape is ~800px wide, so the
  original `max-width:640px` rule handed it the full desktop layout on a 375px
  tall screen — updates above deadlines, filter block expanded, nothing
  foldable, small tap targets. The query is now
  `(max-width:640px), (hover:none) and (pointer:coarse) and (max-width:1024px)`.
  It lives in two places — the stylesheet and the `MOBILE` matchMedia — and they
  must stay identical. Alexander found this by rotating his phone; no amount of
  resizing a desktop browser reproduces it, because a desktop reports
  `pointer:fine` and never takes the branch.
- **Month-only dates stay month-only.** FinCEN dates its reference material
  "09/2007". That is stored as `2007-09`, not `2007-09-01` — the day is unknown
  and inventing one asserts precision the source never gave. `YYYY-MM` still
  sorts correctly against `YYYY-MM-DD` as a string.
- **`store.json` has two authors now, and git cannot merge it.** Since the CI
  dependency fix the Action classifies and commits too, so a local copy taken
  before a bot commit silently deletes whatever the bot added — the diff looks
  like 900 reformatted lines either way. `check_store.py` blocks such a push and
  names the events at risk. It runs from `.githooks/pre-push`, which needs
  enabling once per clone:

      git config core.hooksPath .githooks

  Deliberate shrinks: `STORE_ALLOW_SHRINK=1 git push`. **Always rebase onto
  `origin/main` before committing `store.json`.**
- **`--refresh-dates` matches on title, so it only touches titles that appear
  exactly once in the current fetch, and only records whose date is unparseable.**
  Without both limits it re-dates recurring notices to a single shared date and,
  because the key contains the date, re-keys them all onto one key and destroys
  every occurrence but one. The first draft did exactly that: 88 records instead
  of 16, including the Sunshine Act series. The dry run caught it. Always
  `--dry-run` this first and read the list.

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
