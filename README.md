# RegWatch

A bot that watches government websites for regulatory updates affecting community
banks and fintechs, decides which ones matter, explains each one in plain English,
and shows you the results.

---

## What it actually does

Every time you run it:

1. **Checks 14 government sources** — FDIC, OCC, Federal Reserve, CFPB, FinCEN,
   NCUA, OFAC, CSBS and others. Pulls the latest items from each.
2. **Removes duplicates.** When four agencies publish the same joint guidance, it
   becomes one entry showing all four agencies, not four entries.
3. **Asks Claude which ones matter** to community banks and fintechs, and to write
   a 2–3 sentence explanation of what changed and who it affects.
4. **Looks up real deadlines** — comment periods and effective dates — from the
   Federal Register.
5. **Builds a web page** showing the results.

It remembers what it has already seen, so running it again only processes new
items. That keeps the cost to a few cents a day.

---

## How to run it

Open a command prompt, go to this folder, and run these in order:

```
python fetcher.py       # check the government websites
python pipeline.py      # remove duplicates, analyse anything new
python deadlines.py     # look up comment periods and effective dates
python dashboard.py     # build the web page
```

Then open `dashboard.html` in your browser. That's it.

**Before you spend anything**, `python pipeline.py --dry-run` shows what it would
analyse and roughly what it would cost, without doing it.

---

## The dashboard

`dashboard.html` is the output — a web page you open in your browser. It has:

- **Four counts across the top** — updates this week, open comment periods,
  enforcement actions this month, rules taking effect this quarter
- **Filter buttons** — by agency (FDIC, CFPB, FinCEN…), by topic (BSA/AML,
  Lending, Prepaid/FBO), or **Fintech** for the items that are genuinely
  fintech-specific rather than general bank rules
- **Latest updates** — each with its plain-English summary
- **Upcoming deadlines** — colour-coded by how soon, with a day countdown
- **Export CSV** — whatever is currently filtered, as a spreadsheet

It's a single self-contained file. You can bookmark it, email it to someone, or
put it on a shared drive and it will still work — nothing is loaded from the
internet when you open it.

---

## What's in this folder

| File | What it's for |
|---|---|
| `fetcher.py` | Visits the 14 government websites and collects updates |
| `dedupe.py` | Spots when several agencies published the same thing |
| `classifier.py` | Asks Claude to judge relevance and write the summaries |
| `pipeline.py` | Runs dedupe + classifier together, skipping anything seen before |
| `deadlines.py` | Looks up comment deadlines and effective dates |
| `dashboard.py` | Builds the web page |
| `health.py` | Checks that all 14 sources are still working, and complains if not |
| `dashboard.html` | The web page itself — this is what you open |
| `store.json` | The memory. Everything it has ever seen and analysed. **Don't delete this** |
| `updates.json` | Working file, rewritten every run — doesn't matter |
| `.env` | Your API key. **Never share this file** |
| `requirements.txt` | List of Python packages this needs |

**The only two files you can't lose** are `store.json` (everything analysed so
far — deleting it means paying to re-analyse from scratch) and `.env` (your API
key). Everything else can be regenerated.

---

## Where it currently stands

- **146 events tracked**, 76 judged relevant, **14 fintech-specific**
- **16 have real deadlines** attached
- Fully working — nothing is half-finished

### State regulators — by email, not scraped

NYDFS (New York) and California DFPI both run bot protection that blocks
automated access, including real browsers. Rather than work around it, both are
subscribed to by email through their own alert services:

- NYDFS Industry Letters: public.govdelivery.com/accounts/NYDFS/subscriber/new?topic_id=NYDFS_162
  — subscribed 2026-07-18, confirmed by GovDelivery
- California DFPI (industry list): public.govdelivery.com/accounts/CADFI/subscriber/new
  — subscribed and confirmed 2026-07-18, immediate delivery, broad topic
    selection (43 topics + 7 categories)

These arrive in the personal inbox, not the work one, and are not part of the
dashboard. Everything in the dashboard is federal.

Two traps, both hit on the first attempt at DFPI:

- **DFPI's own subscribe page offers two different signups through two different
  systems** — a consumer newsletter via HubSpot, and the industry alerts via
  GovDelivery. The consumer one is the wrong list. Link straight to the
  GovDelivery form above to avoid the choice.
- **DFPI requires clicking a confirmation link in the email; NYDFS does not.**
  Until that link is clicked the web page still says "Subscriptions updated" and
  nothing is ever delivered. Silence from an unconfirmed subscription is
  indistinguishable from silence because there is no news.

The DFPI selection is deliberately broad, which means volume. If it becomes
noisy, the subset that actually matches this project's focus is roughly: Bank
Regulations, Credit Union Regulations, Money Transmitter Regulations, Digital
Financial Assets Law, Crypto Kiosk Operators, CCFPL, Debt Collection Licensing,
Administrative Orders, Important Notices, Monthly Bulletins, Legislation, and
the Regulations and Rulemaking category. Trim via "Manage Subscriptions" in any
DFPI email.

---

## How you find out when a source breaks

A government website can change its page layout at any time. When that happens
the scraper for it quietly stops finding anything — the daily run still succeeds,
the page still builds, and that agency simply stops appearing. Nothing looks
wrong. That is the failure this guards against.

After each daily run, `health.py` checks all 14 sources and asks two questions:

1. **Did it deliver anything at all this run?** If not, that source is *broken*.
2. **Has the agency published nothing for an unusually long time?** If so, it is
   *quiet* — possibly fine, possibly a sign the listing has frozen.

"Unusually long" is worked out separately for every source from its own track
record, because they run at completely different speeds — OFAC typically posts
something every 2 days, while Fed SR/CA Letters can legitimately go 6 months in
silence. A single shared cut-off would either nag constantly about the slow ones
or never notice the fast ones going dark.

**What you will see:** if a source breaks, the daily run on GitHub goes red and
GitHub emails you. The dashboard still publishes normally first — a broken source
never takes the site down, it just means that agency is missing from it until
fixed. A *quiet* source only shows as a note on the run; it does not email you,
because an alert that fires on nothing teaches you to ignore it.

To check by hand at any time:

    python health.py

---

## Planned: historical backfill (not done yet)

History is currently uneven. The Federal Register sources go back years; the RSS
ones only carry recent items, which is a limit of the format:

| Source | Reaches back to |
|---|---|
| FinCEN Advisories (scraped) | 2018 |
| FinCEN, NCUA (Federal Register) | 2021 / 2024 |
| FDIC, CFPB (RSS) | months |
| OCC, Federal Reserve (RSS) | weeks |

**The fix:** FDIC, OCC, the Federal Reserve and CFPB all publish in the Federal
Register, but `fetcher.py` only queries it for FinCEN and NCUA. Adding the other
four gives deep history for every major agency.

**Do it filtered by document type.** Counts measured against the API, back to
2018:

| Scope | Documents | Approx. cost |
|---|---|---|
| All document types | 6,450 | $71 |
| **Rules + proposed rules only** | **1,453** | **$16** |

The 5,000-document difference is almost entirely Notices — bank holding company
applications, meeting notices, routine filings. The Federal Reserve alone drops
from 3,193 to 362. Paying to classify those so the relevance filter can discard
them is waste.

Add `"conditions[type][]": ["RULE", "PRORULE"]` and
`"conditions[publication_date][gte]": "2018-01-01"` to the Federal Register query,
and add the four agencies to `FEDREG_AGENCIES`. Agency slugs:

    federal-deposit-insurance-corporation
    comptroller-of-the-currency
    federal-reserve-system
    consumer-financial-protection-bureau

Expect roughly 90 minutes to two hours of continuous running. Run it locally, not
through the GitHub Action — the store saves every 10 items, so an interruption
loses nothing.

**What this will not fix:** the Federal Register carries rules and notices only.
Historical OCC Bulletins, FDIC Financial Institution Letters and press releases
live in agency archives and would need separate scraping.

---

## What it costs

Analysis is charged per update by Anthropic, separately from any Claude
subscription.

- A brand new run of everything: about **$1.50**
- A normal daily run: **a few cents**, because it only looks at new items
- Checking the websites, deduplicating and looking up deadlines: **free**

---

## Things worth knowing

**The summaries are written by Claude and can be wrong.** They're good for triage —
deciding what deserves your attention — not for compliance conclusions. Always
open the source link before acting on anything. The dashboard says this at the
bottom.

**Three sources were removed after testing.** SEC, FTC and CFTC were each added,
measured, and found to produce nothing relevant to community banks or fintechs —
0 of 10 every time. They were dropped rather than left running up costs. The
reasons are recorded in `fetcher.py` so they don't get re-added.

**Duplicate detection isn't perfect.** It catches the same item published by
several agencies, but misses cases where the wording differs a lot — for example
one item spelled out as "Anti-Money Laundering" and the same rule abbreviated as
"AML/CFT" appear separately.

**Government websites change.** When one does, that source will start reporting a
failure instead of silently returning nothing. If you see `FAIL` next to a source
name when running `fetcher.py`, that source needs attention — the rest keep working.
