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
- **State regulators are added one at a time, measured first.** Florida OFR
  (Press Releases, 30%) and Texas Dept of Banking (Industry Notices, 33%) are in.
  Texas CU Dept (dormant), OCCC (payday/pawn noise) and TX Savings & Mortgage
  (mortgage-originator admin) were each examined and rejected. Same discipline as
  the SEC/FTC/CFTC federal trials.
- **The Texas cert handling is chain-completion, NOT disabled verification.**
  www.dob.texas.gov serves a real SSL.com cert but omits the intermediate;
  browsers fetch it via the cert's AIA extension, Python doesn't, so a plain
  fetch fails "self-signed certificate in chain". `fetcher._dob_context` bundles
  the intermediate (`certs-ssl-com-intermediate.pem`, expires 2031) and verifies
  against the SSL.com root in certifi — proper verification. Do NOT "fix" a future
  cert error here by disabling verification: the tool republishes what it fetches,
  so an unverified connection means serving content whose integrity isn't checked.
  If the bundled cert expires, refresh it from the AIA URL in fetcher.py.
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

## To-do / open items

Carried forward as of 2026-07-20. Nothing here is broken — these are the next
things to do, not fixes.

1. **Relevance tuning** — does the keep judgment match Alexander's? Currently
   363 of 665 relevant. Never reviewed against his eye; the highest-value open
   item and it costs nothing. Related: FinCEN is a large share of the relevant
   set, much of it older reference material — worth a look at whether it dilutes.
2. **Historical backfill** — ~$16 one-off, ~1,450 rules/proposed rules back to
   2018 across six agencies. Two switches in `fetcher.py` (`ARCHIVE_ENABLED`,
   `FEDREG_AGENCIES_PENDING`). Run locally, 90–120 min. Full detail in README.
3. **LinkedIn launch post** — a draft exists but predates the credit-union
   expansion and the two state sources, so it undersells the tool now. Update the
   deadlines and the audience framing before posting; refresh the preview via
   LinkedIn Post Inspector. The pitch copy also dropped the word "federal" (state
   sources are in now) — check it reads right.
4. **Texas DOB phase 2** — its Enforcement Orders (money-services + bank sectors)
   and Supervisory Memoranda are higher-value than the Industry Notices already
   added. Enforcement Orders need per-sector link following; Supervisory Memoranda
   carry no listing dates. Both over the same completed TLS chain.
5. **More states** — the method is proven (probe reachability → find listing
   pages → measure keep-rate → decide). FL and TX are in. Any new state gets the
   same measure-first test; expect low volume per state.
6. **GitHub 60-day inactivity rule** — scheduled workflows in public repos are
   disabled after 60 days without repo activity. Bot commits happen daily but
   whether they count is undocumented. If the page timestamp ever stops advancing
   with no failure email, this is the likely cause. The weekly `regwatch-watchdog`
   scheduled task is the backstop.

Done 2026-07-20/21 (not open anymore): daily source health check + alerting,
CI dependency fix, FinCEN date bug, tab/bookmark/home-screen icons, foldable
panels + landscape fix, store push-guard, filter relabel, credit-union audience
expansion, Florida OFR + Texas Dept of Banking sources, weekly watchdog task,
"Credit unions only" lens + "Banks, credit unions & fintechs" label, Florida and
Texas source pills, click-to-filter KPI tiles.

---

## "Ask the tracked updates" — the one moving part with a dependency

The public dashboard has a question box that answers from the tracked updates,
naming the agency and date behind each point. It is the only feature that depends
on anything outside this repo.

    browser                          Cloudflare Worker      3 models answer
    searches the tracked       ──▶   adds the keys,    ──▶  in parallel, then a
    updates (BM25, free)             fans out               4th reconciles them

- **It no longer answers from CFR text, deliberately.** `ASK_INCLUDE_REGULATIONS`
  in `dashboard.py` is `False`, so the browser does not load `corpus.json` and no
  regulation text goes to the models. See the next bullet for the evidence. The
  plain keyword search box is a different thing entirely — no model, no network —
  and was never affected.
- **Why: a free model fabricated CFR subsections.** Measured 2026-07-21. The
  source text of 12 CFR 1002.9 contains only the markers `(a)(2)(i)` and
  `(a)(2)(ii)`. Given exactly that text, `gpt-oss-20b` cited `(iii)` through
  `(vi)` and attached one to each element of the notice. The reconciler then in
  use, `gemma-4-26b`, reproduced all six as fact in its main list — a
  hallucination promoted to citation-level precision under a CRCM's name. With no
  CFR text in front of the models there are no subsections to invent, which
  removes the failure rather than hoping a reviewer catches it. Same reasoning
  that keeps RegAssistant out of this repo. Turn it back on when the answering
  models are ones worth citing.
- **The prompts were hardened at the same time.** The answer prompt forbids
  citing any CFR part or subsection not appearing verbatim in the sources, and
  forbids subdividing one that does. The reconcile prompt now treats a citation
  only one answer makes as unconfirmed — report it as that answer's claim, never
  restate it as fact.
- **Retrieval runs in the browser.** GitHub Pages cannot hold an API key —
  anything in the page is readable. So the page searches locally and only the
  model call leaves. Search is therefore free at any traffic level.
- **`corpus.json`** is built by `ecfr_corpus.py` from the free eCFR API (Regs B,
  E, DD — 67 sections; add parts in `PARTS`). The workflow still publishes it and
  it is still current; nothing loads it while the flag is off.
- **The Worker** lives in `worker/` — deployed at
  `regwatch-ask.alexandersmith14.workers.dev`, endpoint hardcoded in
  `dashboard.py` as `ASK_ENDPOINT`. Deploy notes in `worker/README.md`.
- **There is no model picker, and one question costs four provider calls.**
  Groq, Gemini and OpenRouter each answer from the same passages; a fourth model
  then reads *only those three answers, not the sources*, and writes the single
  answer shown. It cannot invent a citation none of them made — the merge can
  only narrow. It is told to state disagreements rather than pick a side, and the
  three raw answers stay behind a "See the N separate answers" toggle, because
  "the models agreed" is a claim the reader should be able to check.
  The reconciler is deliberately not one of the answerers: asked to judge a set
  including its own answer, a model prefers its own. Falling back to an answerer
  works but is degraded, and the page says so under the answer.
- **The reconciler order is measured; don't reshuffle it on taste.** Same
  question, same set of answers to every candidate. `nemotron-3-ultra-550b` and
  `nemotron-3-super-120b` both quarantined the invented citations into an
  attributed "where the answers differ" section and told the reader to verify;
  `gemma-4-26b` restated them as fact. Order is now ultra → super → gemma, and
  gemma is a last-resort fallback, not the choice. Ultra is slower (57s vs 11s,
  and erratic — it was also 4s once) and that trade was made deliberately.
  `gemma-4-31b:free` was rate-limited upstream on every attempt, so it is unused.
  Note the `openrouter` answerer comment warns off Nemotron for *answering* —
  that was measured with 12 large passages, where it burns its budget on internal
  reasoning. The reconcile input is ~6k chars and the objection does not apply.
- **The free-provider search is recorded in `worker.js`; don't repeat it.**
  Cerebras looked ideal and is dead: the key is valid and `/v1/models` lists
  three models, but chat completions returns **402 payment_required on every
  one** — the free tier grants no inference at all. OpenAI has no free API tier
  regardless of what a free ChatGPT account suggests. DeepSeek has no free tier
  either (cheap, but needs a balance — and it is a Chinese-jurisdiction API,
  which is a firm-policy question before it is a technical one). On OpenRouter
  the familiar `:free` slugs (llama-3.3-70b, deepseek-v3, qwen-2.5-72b,
  mistral-small, gemma-3-27b) now 404 "unavailable for free". Cerebras and OpenAI
  are left configured but out of `RECONCILERS`, so enabling either is a one-word
  change once billing exists.
- **Quota and latency both got worse, deliberately.** Free quota is reached ~4×
  sooner — two bake-off runs in a row exhausted Groq's — and measured end-to-end
  times were 37s / 46s / 49s / 121s. The reconcile cannot start until the slowest
  answerer returns. Add the KV rate limit (`worker/README.md`) **before this goes
  public**, not just before a paid key.
- **The key is a Worker secret**, never in the repo or the page. Check it with
  `npx wrangler secret list` — it must be exactly `GROQ_API_KEY`. A trailing
  space in the name once made the Worker report "backend not configured" while
  the dashboard showed the secret as present; the name is invisible-whitespace
  sensitive.
- **Quota is the expected failure.** On a free key, heavy public use exhausts it
  and the box says so plainly; the rest of the dashboard is unaffected. Add the
  KV rate limit (see `worker/README.md`) before moving to a paid key.
- Never commit `worker/.wrangler/` — it holds the Cloudflare account id and an
  account name containing a personal email. Gitignored after being committed once.

---

## Something else reads store.json now

**RegAssistant** (`C:\Users\alexa\RegAssistant`) is a separate, private compliance
research assistant. It reads this project's `store.json` (relevant items only,
read-only) as its "what changed recently" corpus, alongside actual regulation
text pulled from the free eCFR API. Ask it a question, it answers grounded in
both, with citations, via a free LLM provider (Groq/Gemini/OpenRouter/Cerebras);
`--compare` asks several and shows where they disagree.

Two things that matter to RegWatch:

- **`store.json`'s shape is now a small contract.** RegAssistant reads `title`,
  `plain_english`, `tags`, `relevant`, `sources`, `date` and `url`. Renaming or
  dropping those fields breaks it. Adding fields is safe.
- **It is deliberately NOT part of RegWatch.** RegWatch stays the public,
  self-running tracker with no server and no chatbot; a public Q&A bot would add
  hosting, cost and — the real reason — a materially higher liability posture
  (answering "what does the reg require" under a CRCM's name reads as advice).
  Keep them separate.
