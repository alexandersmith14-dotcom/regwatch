"""Generate a self-contained HTML dashboard from store.json.

    python dashboard.py            # writes dashboard.html
    python dashboard.py --open     # ...and opens it

No server, no dependencies, no network calls. Regenerate after each pipeline run.

Design notes:
  * Urgency and deadline proximity are shown as colour + text label. The status
    yellow sits below 3:1 contrast on a light surface, so colour alone would not
    be readable for everyone; the label is the mitigation, not decoration.
  * "Updates by agency" is one hue against a muted track (magnitude comparison),
    not a multi-colour categorical set — the agencies aren't competing series.
  * Dark mode is declared under both the OS media query and the data-theme
    scope, so a manual toggle wins in both directions.
"""
import argparse
import html
import json
# main() binds a local named `html` for the page string, which shadows the module
# there. Alias the escaper so it stays reachable inside main.
from html import escape as hesc
import os
import re
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import fetcher
import regref

# "Ask" is parked. Nothing is broken and nothing was deleted — set ASK_ENABLED
# back to True and the box returns exactly as it was.
#
# Parked 2026-07-21 on evidence. A bake-off of free models turned up the failure
# this feature cannot afford: the source text of 12 CFR 1002.9 carries only the
# subsection markers (a)(2)(i) and (a)(2)(ii), but the answering model cited
# (iii) through (vi) and attached one to each element of the notice, and the
# reconciler then in use (gemma-4-26b) restated all six as fact in its main list
# — a hallucination given citation-level precision. Two other free models
# quarantined and flagged it, so this is model quality, not a design fault.
#
# Scoping the box to the tracked updates removed that specific failure (no CFR
# text in, no subsections to invent) and measured well. It is parked anyway:
# model-written prose under a CRCM's name is a liability posture to take
# deliberately rather than by default, which is the same reasoning that already
# keeps RegAssistant out of this repo.
#
# Preserved and still working: the Worker and its keys, the reconciler order
# measured in the bake-off, corpus.json, ecfr_corpus.py, the in-browser BM25
# retrieval and the whole client path. Unparking is this one flag.
#
# ASK_INCLUDE_REGULATIONS stays False independently. Before setting it True,
# upgrade the ANSWERERS and re-run the bake-off — the fabrication came from an
# answerer reading CFR text, and a better reconciler catches rather than
# prevents it.
#
# The plain keyword search box is a different thing entirely — no model, no
# network — and is unaffected by either flag.
ASK_ENABLED = False
ASK_INCLUDE_REGULATIONS = False

# Where a reader lands when they click a source name. Human pages, deliberately
# NOT the URLs fetcher.py uses — most of those are raw RSS and would drop a
# reader into a wall of XML.
#
# Six agencies here publish through two feeds. The primary one links to the
# agency home page, which effectively never moves; the secondary one links to its
# specific index, because "FDIC FILs" pointing at fdic.gov would say nothing about
# what that feed actually is. Durability where it costs nothing, specificity where
# it earns its keep.
#
# Two notes for whoever revisits these. The OCC reorganised its site, so the old
# /news-issuances/... paths now soft-404 — they return 200 and redirect to a 404
# page, which a status check alone would pass. And consumerfinance.gov returns
# 403 to scripts while serving browsers normally, so a failed command-line check
# there is not evidence of a dead link; both CFPB links were confirmed in a real
# browser.
SOURCE_LINKS = {
    # Primary feed -> agency home page.
    "FDIC": "https://www.fdic.gov/",
    "OCC": "https://www.occ.gov/",
    "Federal Reserve": "https://www.federalreserve.gov/",
    "CFPB": "https://www.consumerfinance.gov/",
    "FinCEN": "https://www.fincen.gov/",
    "NCUA": "https://ncua.gov/",
    "OFAC": "https://ofac.treasury.gov/",
    "CSBS": "https://www.csbs.org/",
    # Secondary feed -> the specific listing it is named after.
    "FDIC FILs": "https://www.fdic.gov/news/financial-institution-letters",
    "OCC Bulletins": "https://www.occ.gov/news-events/newsroom/?nr=Bulletin",
    "Fed SR/CA Letters":
        "https://www.federalreserve.gov/supervisionreg/srletters/srletters.htm",
    "CFPB Rules": "https://www.consumerfinance.gov/rules-policy/final-rules/",
    "FinCEN Advisories": "https://www.fincen.gov/resources/advisoriesbulletinsfact-sheets",
    "NCUA Press": "https://ncua.gov/news/press-releases",
    # State regulators.
    "FL OFR Press": "https://flofr.gov/news/press-releases",
    "TX Dept of Banking": "https://www.dob.texas.gov/news-and-events/industry-notices",
}

# Every cite in regref.py is a part of title 12, given as "12 CFR 215",
# "CFPB 1002" or "Fed 228" — the trailing number is the part either way.
CFR_PART = re.compile(r"(\d{3,4})\s*$")


def ecfr_url(cfr):
    """eCFR link for a regref cite, or None if no part number is present."""
    m = CFR_PART.search(cfr)
    return f"https://www.ecfr.gov/current/title-12/part-{m.group(1)}" if m else None

STORE_PATH = "store.json"
OUT_PATH = "dashboard.html"

# Absolute URL of the published site. Social scrapers require absolute URLs for
# og:image and og:url — a relative path silently produces no preview.
SITE_URL = "https://alexandersmith14-dotcom.github.io/regwatch/"

# Kaufman Rossin brand.
# Navy #003B6A and green #AED136 are taken from kaufmanrossin.com, along with
# its heading grey #3C3C3C and body ink #212529.
#
# The green is used ONLY as a solid accent block (the header bar, panel rules)
# with dark text on top - never for text, thin marks, or anything that carries
# meaning by colour. It measures 1.75:1 against white, well under the 3:1 floor,
# so as a data colour it would be invisible to a lot of readers. That is how the
# firm's own site uses it too.
#
# Navy is too dark to sit on a dark background, so dark mode uses a lighter step
# of the same hue (#4E9BD8), checked against the dark surface.
CSS = """
:root{
  color-scheme:light;
  --page:#f4f4f4; --surface:#ffffff; --raised:#fafafa;
  --ink:#212529; --ink-2:#3c3c3c; --ink-muted:#6c757d;
  --rule:#e3e3e3; --border:rgba(0,0,0,.12);
  --brand:#003b6a; --brand-bg:#003b6a; --accent:#aed136;
  --bar:#003b6a; --track:#e3e3e3;
  --crit:#c0392b; --warn:#9a6400; --ok:#2f7d32; --neutral:#3c3c3c;
  --chip:#f0f0f0;
  --on-accent:#212529;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --page:#101418; --surface:#161a1d; --raised:#1d2226;
    --ink:#f5f5f5; --ink-2:#c9cdd1; --ink-muted:#8b9298;
    --rule:#2a3035; --border:rgba(255,255,255,.12);
    --brand:#4e9bd8; --brand-bg:#00294a; --accent:#aed136;
    --bar:#4e9bd8; --track:#2a3035;
    --crit:#e66767; --warn:#eda100; --ok:#4caf50; --neutral:#c9cdd1;
    --chip:#232a2f;
    --on-accent:#101418;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --page:#101418; --surface:#161a1d; --raised:#1d2226;
  --ink:#f5f5f5; --ink-2:#c9cdd1; --ink-muted:#8b9298;
  --rule:#2a3035; --border:rgba(255,255,255,.12);
  --brand:#4e9bd8; --brand-bg:#00294a; --accent:#aed136;
  --bar:#4e9bd8; --track:#2a3035;
  --crit:#e66767; --warn:#eda100; --ok:#4caf50; --neutral:#c9cdd1;
  --chip:#232a2f;
  --on-accent:#101418;
}
*{box-sizing:border-box}
/* museo-sans is the firm's typeface, licensed through Adobe Fonts and not
   embeddable in a self-contained file, so it only resolves on a machine that has
   it installed locally. Everything after it is the fallback that actually runs.
   It used to be kaufmanrossin.com's chain — Calibri,Georgia,Verdana — and that
   was a real bug on phones: Calibri is a Windows font, so desktops got Calibri
   and looked right, while iOS has no Calibri and fell through to GEORGIA, a
   serif book face, for the whole dashboard. It rendered like a printed document,
   not a tool. Measured on a 390px viewport before changing it.
   The system stack below gives SF on iOS, Segoe UI on Windows, Roboto on
   Android — each platform's own interface face, which is what "native" looks
   like. Do not reintroduce Georgia or Verdana as fallbacks. */
body{margin:0;padding:22px;background:var(--page);color:var(--ink);
  font:14px/1.55 museo-sans,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "Helvetica Neue",Arial,sans-serif;
  -webkit-text-size-adjust:100%;-webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto}
header{display:flex;align-items:center;gap:16px;margin-bottom:20px;
  background:var(--brand-bg);color:#fff;padding:18px 22px;border-radius:8px;
  border-bottom:4px solid var(--accent)}
header .t{flex:1}
h1{font-size:21px;margin:0 0 3px;color:#fff;font-weight:700;letter-spacing:-.01em}
.sub{color:rgba(255,255,255,.82);font-size:13px;margin:0}
/* Desktop keeps both facts on one line; the separator is CSS so the phone can
   drop it and break instead. */
.sub .stamp::before{content:" · "}
.lbl-full{display:inline}
button{font:inherit;font-size:13px;padding:8px 14px;color:var(--ink);
  background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer}
button:hover{background:var(--raised)}
header button{background:var(--accent);border-color:var(--accent);
  color:var(--on-accent);font-weight:700}
header button:hover{filter:brightness(1.06)}

/* Public-facing notice. Deliberately at the top and in normal body size: a
   personal triage tool can put its caveats in the footer, a public one can't.
   Anyone landing here needs to know the summaries are generated before they
   read any of them. */
.notice{background:var(--surface);border:1px solid var(--border);
  border-left:4px solid var(--warn);border-radius:8px;padding:13px 16px;
  margin-bottom:18px;font-size:13px;color:var(--ink-2)}
.notice strong{color:var(--ink)}

.coverage{font-size:12.5px;color:var(--ink-2)}
.coverage summary{cursor:pointer;font-size:12.5px;color:var(--brand);
  font-weight:600;list-style:none}
.coverage summary::-webkit-details-marker{display:none}
.coverage summary::before{content:"▸ ";}
.coverage[open] summary::before{content:"▾ ";}
.coverage .body{padding-top:10px;line-height:1.6}
.coverage .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
  gap:6px 22px;margin-top:8px}
.rr-group{margin-top:16px}
.rr-group h3{font-size:13px;margin:0 0 2px;color:var(--ink)}
.rr-table{width:100%;border-collapse:collapse;margin-top:7px}
.rr-table th{text-align:left;font-size:11px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--ink-muted);padding:5px 8px;
  border-bottom:1px solid var(--rule)}
.rr-table td{padding:6px 8px;border-bottom:1px solid var(--rule);
  font-size:12.5px;vertical-align:top}
.rr-letter{font-weight:700;color:var(--brand);white-space:nowrap;width:64px}
.rr-cfr{color:var(--ink-2);white-space:nowrap;font-variant-numeric:tabular-nums}
.rr-note{color:var(--ink-muted);font-size:11.5px;margin-top:3px}
.rr-foot{margin-top:14px;padding-left:18px}
.rr-foot li{margin-bottom:8px;font-size:12.5px}
.rr.hidden,.rr-group.hidden{display:none}
.coverage code{background:var(--chip);padding:1px 5px;border-radius:3px;font-size:11.5px}

/* "Ask the regulations" panel. Retrieval runs in the browser; only the model
   call goes to a Cloudflare Worker, which holds the API key server-side. */
.ask-panel{background:var(--surface);border:1px solid var(--border);
  border-left:4px solid var(--brand);border-radius:9px;padding:16px 18px;
  margin-bottom:18px}
.ask-panel h2{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--brand);margin:0 0 6px;font-weight:700}
.ask-panel .sub{font-size:12.5px;color:var(--ink-2);margin:0 0 11px}
.ask-row{display:flex;gap:8px;flex-wrap:wrap}
.ask-row input{flex:1 1 380px;font:inherit;font-size:13px;padding:9px 12px;
  color:var(--ink);background:var(--page);border:1px solid var(--border);
  border-radius:6px}
.ask-row input:focus{outline:2px solid var(--brand);outline-offset:1px}
.ask-row button{font:inherit;font-size:13px;font-weight:700;padding:9px 18px;
  background:var(--brand);color:#fff;border:1px solid var(--brand);
  border-radius:6px;cursor:pointer}
.ask-row button:disabled{opacity:.55;cursor:default}
#askout{margin-top:13px;font-size:13.5px;line-height:1.6;color:var(--ink)}
#askout:empty{display:none}
#askout .ans{background:var(--raised);border:1px solid var(--border);
  border-radius:8px;padding:13px 15px}
#askout .cites{font-size:12px;color:var(--ink-muted);margin-top:9px;
  padding-top:8px;border-top:1px solid var(--rule)}
#askout h3{font-size:13px;margin:11px 0 5px;color:var(--ink)}
#askout ul{margin:5px 0 5px 20px;padding:0}
#askout li{margin-bottom:3px}
#askout .warn{color:var(--warn)}
.ask-note{font-size:11.5px;color:var(--ink-muted);margin-top:9px}
/* The individual model answers behind the reconciled one. Collapsed by default:
   the merged answer is what to read, these are for checking it. */
#askout .askraw{margin-top:9px}
#askout .askraw summary{font-size:12px;color:var(--ink-2);cursor:pointer;
  padding:5px 0;user-select:none}
#askout .askraw summary:hover{color:var(--brand)}
#askout .askraw .ans{margin-top:8px}
#askout .ans+.ans{margin-top:9px}
#askout .who{font-size:11px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;color:var(--brand);margin-bottom:7px}
@media (max-width:640px), (hover:none) and (pointer:coarse) and (max-width:1024px){
  .ask-panel{padding:12px 13px;margin-bottom:14px}
  .ask-row input{flex:1 1 100%}
  .ask-row button{width:100%}
}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:12px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:14px 16px}
.kpi .l{font-size:12px;color:var(--ink-2)}
.kpi .v{font-size:32px;line-height:1.15;letter-spacing:-.02em;margin:6px 0 2px}
.kpi .n{font-size:12px;color:var(--ink-muted)}
.kpi .n.up{color:var(--crit)} .kpi .n.down{color:var(--ok)}
/* Clickable tiles (those with a non-zero count) filter the list on click. */
.kpi[data-kpi]{cursor:pointer;user-select:none;text-align:left;
  transition:border-color .1s,box-shadow .1s}
.kpi[data-kpi]:hover{border-color:var(--brand)}
.kpi[data-kpi]:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
.kpi[aria-pressed="true"]{border-color:var(--brand);
  box-shadow:inset 0 0 0 1px var(--brand)}
.kpi[data-kpi]::after{content:"filter ▸";display:block;margin-top:6px;
  font-size:10.5px;font-weight:600;letter-spacing:.04em;color:var(--brand);
  opacity:0;transition:opacity .1s}
.kpi[data-kpi]:hover::after,.kpi[aria-pressed="true"]::after{opacity:1}
.kpi[aria-pressed="true"]::after{content:"filtering ▾"}

/* Two labelled groups. The pills used to be one undifferentiated row, which hid
   the fact that they answer different questions: agency pills filter by WHO
   published an item, topic pills by WHAT it is about. Same look, different
   mechanism, no way for a reader to tell. */
.pillgroup{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:9px}
.pillgroup:last-of-type{margin-bottom:18px}
.grouplabel{font-size:11px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink-muted);width:104px;flex:none}
.grouplabel small{display:block;font-weight:400;letter-spacing:0;
  text-transform:none;font-size:11px;line-height:1.3;margin-top:1px}
.searchwrap{position:relative;flex:1 1 340px;max-width:520px}
.searchwrap input{width:100%;font:inherit;font-size:13px;padding:8px 30px 8px 12px;
  color:var(--ink);background:var(--surface);border:1px solid var(--border);
  border-radius:999px}
.searchwrap input:focus{outline:2px solid var(--brand);outline-offset:1px;
  border-color:var(--brand)}
.searchwrap input::-webkit-search-cancel-button{display:none}
#clearq{position:absolute;right:4px;top:50%;transform:translateY(-50%);
  border:none;background:transparent;color:var(--ink-muted);font-size:17px;
  line-height:1;padding:2px 8px;cursor:pointer;border-radius:50%}
#clearq:hover{color:var(--ink);background:var(--chip)}
.pills{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:18px}
.pill{font-size:12.5px;padding:6px 13px;border-radius:999px;cursor:pointer;
  background:var(--surface);border:1px solid var(--border);color:var(--ink-2)}
/* Selected pill uses navy, not the brand green: the green is a background
   accent and white text on it fails contrast badly. */
.pill[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);
  color:#fff;font-weight:700}

/* Relevance is a lens, not a gate — this switches between the filtered default
   and everything collected. */
.viewtoggle{display:inline-flex;border:1px solid var(--border);border-radius:999px;
  overflow:hidden}
.viewtoggle button{border:none;border-radius:0;padding:6px 15px;font-size:12.5px;
  background:var(--surface);color:var(--ink-2);cursor:pointer}
.viewtoggle button[aria-pressed="true"]{background:var(--brand);color:#fff;font-weight:700}
/* Set-aside items are dimmed AND labelled — dimming alone is not a readable
   signal, and in the everything view the reader must be able to tell which
   items met the criteria. */
.dropped{opacity:.78}
.badge.setaside{background:transparent;border:1px solid var(--border);
  color:var(--ink-muted);font-weight:400}

#filters summary{display:none}          /* desktop: always expanded, no control */
#filters>.pillgroup:last-of-type{margin-bottom:18px}
.cols{display:grid;grid-template-columns:1fr 400px;gap:18px;align-items:start}
@media (max-width:900px){.cols{grid-template-columns:1fr}}

.panel{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:16px 18px}
.panel+.panel{margin-top:18px}
.panel h2{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--brand);margin:0 0 12px;font-weight:700;
  border-bottom:2px solid var(--accent);padding-bottom:7px}
/* Two panels are <details> so they can fold on a phone. Suppress the native
   disclosure triangle at every width — on desktop they are plain panels with no
   affordance, and script blocks the click that would otherwise collapse them. */
.foldable>summary{list-style:none;display:block}
.foldable>summary::-webkit-details-marker{display:none}
.foldable>summary h2{cursor:default}
.panel .note{font-size:12px;color:var(--ink-2);margin:-6px 0 12px}

.card{padding:14px 0;border-bottom:1px solid var(--rule)}
.card:first-of-type{padding-top:0}
.card:last-child{border-bottom:none;padding-bottom:0}
.card .top{display:flex;align-items:center;gap:8px;margin-bottom:7px;flex-wrap:wrap}
.badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:4px;background:var(--chip);color:var(--ink-2)}
.badge.t-Final{color:#fff;background:var(--crit)}
.badge.t-Proposed{color:#fff;background:var(--warn)}
.badge.t-Guidance{color:#fff;background:var(--brand)}
.badge.t-Enforcement{color:#fff;background:var(--neutral)}
.card .agency{font-size:12px;color:var(--ink-muted)}
.card h3{font-size:14.5px;margin:0 0 5px;font-weight:600;line-height:1.35}
.card h3 a{color:var(--brand);text-decoration:none}
.card h3 a:hover{text-decoration:underline}
.card p{margin:0;font-size:13px;color:var(--ink-2)}
.card .meta{margin-top:7px;font-size:12px;color:var(--ink-muted);
  font-variant-numeric:tabular-nums}
.u{font-weight:600}
.u::before{content:"● "}
.u-High{color:var(--crit)} .u-Medium{color:var(--warn)} .u-Low{color:var(--ink-muted)}

.dl{display:flex;gap:10px;padding:11px 0;border-bottom:1px solid var(--rule)}
.dl:last-child{border-bottom:none}
.dl .dot{flex:none;width:9px;height:9px;border-radius:50%;margin-top:6px}
.dl .body{flex:1}
.dl .ttl{font-size:13.5px;font-weight:600;line-height:1.35}
.dl .ttl a{color:var(--ink);text-decoration:none}
.dl .ttl a:hover{text-decoration:underline}
.dl .when{font-size:12px;margin-top:3px;font-variant-numeric:tabular-nums}
.soon{color:var(--crit)} .mid{color:var(--warn)} .far{color:var(--ok)}

.agrow{display:grid;grid-template-columns:120px 1fr 74px;gap:7px 10px;align-items:center}
.agrow .n{font-size:12.5px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.meter{position:relative;height:11px;background:var(--track);border-radius:4px;overflow:hidden}
.meter>span{position:absolute;inset:0 auto 0 0;background:var(--bar);border-radius:4px}
.agrow .c{font-size:12px;color:var(--ink-2);font-variant-numeric:tabular-nums}
.empty{color:var(--ink-2);font-size:13px;padding:8px 0}

/* Contact card. This is the point of publishing the tool, so it gets real
   estate at the bottom of the page — where someone lands after they have
   found it useful — rather than a link buried in the footer text. */
.contact{margin-top:22px;background:var(--surface);border:1px solid var(--border);
  border-top:4px solid var(--accent);border-radius:9px;padding:18px 20px;
  display:flex;flex-wrap:wrap;gap:18px;align-items:center}
.contact .who{flex:1 1 340px;min-width:280px}
.contact .name{font-size:15px;font-weight:700;color:var(--ink)}
.contact .role{font-size:13px;color:var(--ink-2);margin-top:2px}
.contact .pitch{font-size:13px;color:var(--ink-2);margin-top:9px;line-height:1.55}
.contact .acts{display:flex;flex-wrap:wrap;gap:9px}
.contact a.btn{font-size:13px;font-weight:600;padding:9px 16px;border-radius:6px;
  text-decoration:none;border:1px solid var(--border);color:var(--ink);
  background:var(--raised)}
.contact a.btn:hover{border-color:var(--brand)}
.contact a.btn.primary{background:var(--brand);border-color:var(--brand);color:#fff}
.contact a.btn.primary:hover{filter:brightness(1.12)}
footer{margin-top:22px;font-size:11px;color:var(--ink-muted)}

/* ===================================================================
   PHONE LAYOUT LIVES LAST, AND MUST STAY LAST.

   Media-query rules carry no extra specificity, so any base rule written
   below this block beats it on source order alone. It used to sit in the
   middle of the stylesheet with ~70 lines after it, and seven overrides
   were silently dead: .panel padding, .card h3 size and line-height,
   .card p size, .contact padding and gap. Phones were quietly served
   desktop spacing and nothing pointed at it - the page just looked a bit
   wrong. Add new base rules ABOVE this block, never below.
   =================================================================== */
/* Phone layout. The desktop proportions put 1,434px of header, counts and
   filters above the first actual update — nearly two full screens of scrolling
   before any content, on the device most LinkedIn traffic arrives from.
   Everything here buys that height back.

   Not width alone. A phone in landscape is around 800px wide, so a plain
   max-width:640px rule handed it the full desktop layout on a 375px-tall
   screen: updates above deadlines, the filter block fully expanded, nothing
   foldable, small tap targets. The pointer test catches a phone in either
   orientation; the width bound keeps large tablets and touch-capable laptops on
   the desktop layout, which is what suits them.

   MUST stay in sync with the MOBILE matchMedia in the script below. */
@media (max-width:640px), (hover:none) and (pointer:coarse) and (max-width:1024px){
  /* Type scale. The old one ran 11-12.5px for everything secondary, which on a
     phone reads as dense rather than compact — small type is the main thing that
     makes a page feel clunky rather than considered. Nothing here is larger than
     its desktop size; the phone just stops being punished. */
  body{padding:12px;font-size:15px}

  /* The header was 152px — 18% of an iPhone screen — as a solid navy slab with
     a two-line title and a three-line subtitle. Two causes, both fixed here
     rather than by shrinking type:
       1. "Export CSV" took 102px of a 366px row, leaving the title 220px and
          forcing the wrap. Hiding "Export " leaves "CSV" and gives the title
          the width to sit on one line.
       2. The audience and the timestamp ran together into three ragged lines.
          They are separate blocks now, and the stamp is dimmed — it is
          reference, not a headline.
     The accent rule also drops 4px to 3px: at phone width a 4px bar reads as a
     third element rather than a trim. */
  header{padding:14px 16px;gap:10px;margin-bottom:14px;border-bottom-width:3px;
    align-items:flex-start}
  h1{font-size:20px;line-height:1.2;margin:0 0 4px}
  .sub{font-size:12.5px;line-height:1.4}
  .sub .stamp{display:block;font-size:11.5px;opacity:.72;margin-top:2px}
  .sub .stamp::before{content:none}
  .lbl-full{display:none}
  #export{flex:0 0 auto}
  /* Stays at readable body size on purpose — see the .notice comment above; a
     public tool cannot put its caveats in the footer. Only the padding and the
     leading tighten here, and the deadline explanation moved into the coverage
     panel. The caveat itself is not shrunk to get the height down. */
  .notice{padding:12px 13px;font-size:13px;line-height:1.45;margin-bottom:14px}

  /* Two-up instead of stacked: four numbers in half the height. */
  .kpis{grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}
  .kpi{padding:12px 13px;border-radius:10px}
  .kpi .v{font-size:26px;margin:4px 0 2px}
  .kpi .l,.kpi .n{font-size:12px;line-height:1.35}

  /* Label above the controls rather than beside them — the fixed 104px column
     was taking 31% of a 331px content width and pushing the source pills onto
     five rows. */
  .grouplabel{width:100%;flex:0 0 100%;margin-bottom:3px}
  .grouplabel small{display:inline;margin-left:6px}
  .pillgroup{gap:7px;margin-bottom:13px}
  .searchwrap{flex:1 1 100%;max-width:none}

  /* 16px is not a style choice. Safari zooms the whole page when you focus an
     input smaller than 16px, so tapping search used to lurch the layout and
     leave the reader pinched in. This is the fix for that, not a size bump. */
  #q{font-size:16px;padding-top:11px;padding-bottom:11px}

  .panel{padding:14px 15px}
  .cols{gap:14px}
  .card h3{font-size:15px}
  .card p{font-size:13.5px}

  .rr-table td,.rr-table th{padding:4px 5px;font-size:11.5px}
  .rr-letter{width:46px}
  .contact{padding:15px 16px;gap:14px}

  /* Stacked columns put deadlines eight screens down, below every update card,
     even though they are the most actionable thing on the page. display:contents
     lifts the panels out of their column wrappers so they can be ordered. */
  .cols{display:flex;flex-direction:column;gap:14px}
  .colmain,.colside{display:contents}
  .p-deadlines{order:1}
  .p-updates{order:2}
  #alsofound{order:3}
  .p-agencies{order:4}

  /* Touch targets. Apple's guideline is 44px and these measured 33-35px, which
     is the difference between tapping a filter and aiming at one. min-height
     with centred content rather than more padding, so the pill rows do not grow
     taller than they need to. */
  .pill,.viewtoggle button{min-height:44px;display:inline-flex;align-items:center;
    justify-content:center;font-size:13px}
  .pill{padding:0 14px}
  .viewtoggle button{padding:0 16px}
  .viewtoggle{border-radius:14px}
  #export{min-height:44px;padding:0 16px;font-size:13px}
  #showmore,#dlmore{min-height:44px}
  .contact a.btn{min-height:44px;display:inline-flex;align-items:center}
  .card h3{line-height:1.45}
  .card h3 a{display:inline-block;padding:2px 0}
  #showmore,#dlmore{width:100%;margin-top:12px;padding:11px;font-weight:600;
    color:var(--brand);background:var(--surface)}

  /* Foldable panels. Only here, and only as an affordance the reader can use --
     both stay open on arrival. Collapsing the update list by default would show
     a visitor from LinkedIn a page of headings and nothing else. */
  .foldable>summary{cursor:pointer;list-style:none;display:block}
  .foldable>summary::-webkit-details-marker{display:none}
  /* Flex so the disclosure arrow can sit hard right. The card-count span floats
     right on desktop; inside a flex row that float is ignored and it simply
     lands between the title and the arrow, which reads correctly on a phone. */
  .foldable>summary h2{display:flex;align-items:center;gap:8px}
  .foldable>summary h2::after{content:"▸";margin-left:auto;font-size:13px;
    line-height:1;color:var(--brand)}
  .foldable[open]>summary h2::after{content:"▾"}
  /* The heading's bottom margin is the gap to the content; with the panel shut
     that becomes dead space under the bar. */
  .foldable:not([open])>summary h2{margin-bottom:0}

  /* Collapse the filter block. 327px of pills sat above the first update on a
     phone; search stays out here because it is the control people reach for. */
  #filters summary{display:block;cursor:pointer;list-style:none;
    font-size:12.5px;font-weight:700;color:var(--brand);padding:9px 13px;
    background:var(--surface);border:1px solid var(--border);border-radius:8px;
    margin-bottom:12px}
  #filters summary::-webkit-details-marker{display:none}
  #filters summary::after{content:" ▸";}
  #filters[open] summary::after{content:" ▾";}
  #filters[open] summary{margin-bottom:10px}
}
"""

JS = r"""
const DATA = JSON.parse(document.getElementById('data').textContent);
// Feed names grouped under the agency that publishes them. Readers think "OCC",
// not "OCC versus OCC Bulletins".
const GROUPS = JSON.parse(document.getElementById('groups').textContent);
// feed name -> agency label, for the by-agency chart.
const FEED_TO_AGENCY = {};
GROUPS.forEach(([label, feeds]) => feeds.forEach(f => { FEED_TO_AGENCY[f] = label; }));
const TODAY = document.body.dataset.today;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const days = d => Math.round((new Date(d) - new Date(TODAY)) / 86400000);

let filter = {kind: 'all', value: ''};
let query = '';
// Relevance is a lens, not a gate. The profile it screens against is one
// person's view of what matters; a public audience does not share it. Default to
// the filtered view because that is the useful default, but everything the
// agencies published stays one click away.
let showAll = false;

// Search runs IN ADDITION to whichever pill is active, so "FinCEN" + "stablecoin"
// narrows rather than replacing the pill selection.
// Terms match at the START of a word, not anywhere inside one. Plain substring
// matching produced false hits that were hard to spot: searching "regulation gg"
// returned an item about Regulation O, because "gg" sits inside "trigger".
// Anchoring to a word boundary still allows prefixes, so "stablecoin" finds
// "stablecoins" and "reg" finds "regulation".
const rxCache = new Map();
function termRx(t) {
  if (!rxCache.has(t)) {
    const lit = t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // Short terms must match a WHOLE word; longer ones may match a prefix.
    //
    // Regulation designators are single letters, and a prefix match on "d" hits
    // data, disparate, directors, delay — so "Regulation D" returned Reg B and
    // Reg O items. Prefix matching is still wanted for real words ("stablecoin"
    // should find "stablecoins"), so the rule is length-based rather than global.
    const rx = t.length <= 2 ? `\\b${lit}\\b` : `\\b${lit}`;
    rxCache.set(t, new RegExp(rx, 'i'));
  }
  return rxCache.get(t);
}

function matchesQuery(d) {
  if (!query) return true;
  const hay = (d.title + ' ' + d.why + ' ' + d.sources.join(' ') + ' ' +
               (d.tags || []).join(' ') + ' ' + (d.type || '')).toLowerCase();
  // Every whitespace-separated term must appear, so extra words narrow the
  // result instead of widening it the way an OR match would.
  return query.split(/\s+/).every(t => termRx(t).test(hay));
}

function rows() {
  return DATA.filter(d => {
    if (!showAll && !d.relevant) return false;
    if (!matchesQuery(d)) return false;
    // One agency, several feeds — the pill value is pipe separated so "OCC"
    // covers both the press feed and the bulletins.
    if (filter.kind === 'agency') {
      return filter.value.split('|').some(f => d.sources.includes(f));
    }
    // Fintech uses the classifier's explicit judgment, not a word match.
    // Searching the text instead returns 63 items where the classifier finds 48,
    // agreeing on only 31: it misses 17 genuinely fintech items and adds 32 that
    // are not, because most summaries carry the phrase "community banks and
    // fintechs" regardless of subject. This is why it is a control, not a search.
    if (filter.kind === 'fintech') return d.fintech === true;
    // Credit unions likewise use the classifier's judgment, not the NCUA source:
    // NCUA publishes plenty that is not credit-union-specific, and interagency
    // credit-union items arrive under other agencies' names.
    if (filter.kind === 'credit_union') return d.credit_union === true;
    // KPI tiles: d.kpi holds the tile keys this item satisfies, tagged at build
    // time so the tile count and this list are the same computation.
    if (filter.kind === 'kpi') return (d.kpi || []).includes(filter.value);
    return true;
  });
}

// Items the relevance filter dropped, shown ONLY when searching. The filter is a
// judgment and it can be wrong for a specific reader — a bank in Tennessee wants
// the Tennessee disaster-relief notice even though it is not a broad regulatory
// change. Without this, search silently misses 280 items and looks like proof
// that nothing exists.
// The reg reference filters with the same search box, so "Regulation B" or
// "1002" surfaces the lookup row as well as the tracked items.
function renderRegRef() {
  const rows = document.querySelectorAll('#regref tr.rr');
  if (!rows.length) return;
  let shown = 0;
  rows.forEach(tr => {
    const hit = !query || query.split(/\s+/).every(t => termRx(t).test(tr.dataset.rr));
    tr.classList.toggle('hidden', !hit);
    if (hit) shown++;
  });
  document.querySelectorAll('#regref .rr-group').forEach(g => {
    g.classList.toggle('hidden', !g.querySelectorAll('tr.rr:not(.hidden)').length);
  });
  // Open the panel automatically when a search matches a regulation.
  const det = document.getElementById('regref');
  if (query && shown && shown < rows.length) det.open = true;
}

function renderFilteredOut() {
  const box = $('#alsofound');
  // Redundant when the full set is already on screen.
  if (!query || showAll) { box.innerHTML = ''; return; }
  const hits = DATA.filter(d => !d.relevant && matchesQuery(d)).slice(0, 15);
  if (!hits.length) { box.innerHTML = ''; return; }
  box.innerHTML = `
    <div class="panel" style="margin-top:18px">
      <h2>Also found — items the relevance filter set aside (${hits.length})</h2>
      <p class="note">These did not meet the community bank / fintech criteria, so
      they are not in the counts above. Shown because they match your search.</p>
      ${hits.map(d => `
        <div class="card dropped">
          <div class="top">
            <span class="badge">${esc(d.type || '—')}</span>
            <span class="agency">${esc(d.sources.join(' · '))}</span>
          </div>
          <h3><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a></h3>
          <p>${esc(d.why)}</p>
          <div class="meta">${esc(d.date)}</div>
        </div>`).join('')}
    </div>`;
}

// Fewer cards on a phone. At 25 the page ran ten screens deep, which put the
// contact card past the point anyone scrolls. The rest are one tap away.
//
// Driven by a matchMedia listener rather than a one-off check at load: a
// load-time read is unreliable and would also strand a phone that rotates into
// landscape with the narrow layout.
// MUST match the phone media query in the stylesheet above. A phone in
// landscape is ~800px wide, so testing width alone treated it as a desktop and
// switched off the folding, the deadlines-first ordering and the collapsed
// filter block exactly when the 375px-tall screen needed them most.
const MOBILE = window.matchMedia(
  '(max-width:640px), (hover:none) and (pointer:coarse) and (max-width:1024px)');
let cardLimit = MOBILE.matches ? 8 : 25;
// Deadlines are ordered FIRST on a phone because they are the most actionable
// thing here — but uncapped that panel ran 1,389px, two thirds of everything
// above the first update card. Capping it keeps the ordering decision without
// making the reader scroll past 78 dates to reach an update. Desktop is a side
// column where length costs nothing, so it stays uncapped.
let dlLimit = MOBILE.matches ? 6 : Infinity;
let userChoseLimit = false;      // never override an explicit "show more"
let userChoseDlLimit = false;    // same, for the deadlines panel
let userToggledFilters = false;  // or an explicit open/close

function renderCards(rs) {
  const list = rs.slice(0, cardLimit);
  $('#cards').innerHTML = list.length ? list.map(d => {
    const short = (d.type || '').split(' ')[0];
    // In the "everything" view a set-aside item must be visibly marked, or the
    // reader cannot tell which items met the criteria and which did not.
    return `<div class="card${d.relevant ? '' : ' dropped'}">
      <div class="top">
        <span class="badge t-${esc(short)}">${esc(d.type || '—')}</span>
        <span class="agency">${esc(d.sources.join(' · '))}</span>
        ${d.relevant ? '' : '<span class="badge setaside">set aside by filter</span>'}
      </div>
      <h3><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a></h3>
      <p>${esc(d.why)}</p>
      <div class="meta">${esc(d.date)} · <span class="u u-${esc(d.urgency)}">${esc(d.urgency)}</span></div>
    </div>`;
  }).join('') : '<div class="empty">No updates match this filter.</div>';
  $('#cardcount').textContent = `${rs.length} update${rs.length === 1 ? '' : 's'}`;
  const more = $('#showmore');
  if (more) {
    const hidden = rs.length - list.length;
    more.hidden = hidden <= 0;
    more.textContent = `Show ${hidden} more update${hidden === 1 ? '' : 's'}`;
  }
}

function renderDeadlines(rs) {
  const items = [];
  rs.forEach(d => {
    if (d.comments_close_on && d.comments_close_on >= TODAY)
      items.push({d, when: d.comments_close_on, what: 'Comments close'});
    if (d.effective_on && d.effective_on >= TODAY)
      items.push({d, when: d.effective_on, what: 'Takes effect'});
  });
  items.sort((a, b) => a.when.localeCompare(b.when));
  // Sorted soonest-first, so a cap hides the least urgent — never the ones about
  // to close.
  const shown = items.slice(0, dlLimit);
  $('#deadlines').innerHTML = shown.length ? shown.map(({d, when, what}) => {
    const n = days(when);
    const cls = n <= 14 ? 'soon' : n <= 45 ? 'mid' : 'far';
    const col = cls === 'soon' ? 'var(--crit)' : cls === 'mid' ? 'var(--warn)' : 'var(--ok)';
    return `<div class="dl">
      <div class="dot" style="background:${col}"></div>
      <div class="body">
        <div class="ttl"><a href="${esc(d.fr_url || d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a></div>
        <div class="when ${cls}">${esc(what)} ${esc(when)} · ${n} day${n === 1 ? '' : 's'}</div>
      </div></div>`;
  }).join('')
  : '<div class="empty">No dated deadlines in this view. Dates come from matched Federal Register documents; items without a match show none.</div>';

  const dlMore = $('#dlmore');
  if (dlMore) {
    const hidden = items.length - shown.length;
    dlMore.hidden = hidden <= 0;
    dlMore.textContent = `Show ${hidden} more deadline${hidden === 1 ? '' : 's'}`;
  }
}

function renderAgencies(rs) {
  const c = {};
  // Counted by agency, matching the Source pills. Counting raw feeds instead
  // listed "FDIC" and "FDIC FILs" as if they were separate regulators, and an
  // interagency item counted once per feed rather than once per agency.
  rs.forEach(d => {
    const seen = new Set();
    d.sources.forEach(s => {
      const label = FEED_TO_AGENCY[s] || s;
      if (!seen.has(label)) { seen.add(label); c[label] = (c[label] || 0) + 1; }
    });
  });
  const e = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const max = e.length ? e[0][1] : 1;
  $('#agencies').innerHTML = e.length ? e.map(([n, v]) =>
    `<div class="n" title="${esc(n)}">${esc(n)}</div>
     <div class="meter"><span style="width:${Math.round(v / max * 100)}%"></span></div>
     <div class="c">${v} update${v === 1 ? '' : 's'}</div>`).join('')
    : '<div class="empty">—</div>';
}

function render() {
  const rs = rows();
  renderCards(rs); renderDeadlines(rs); renderAgencies(rs); renderFilteredOut(); renderRegRef();
}

// Counts on the buttons, so the size of each lens is visible before clicking
// rather than inferred afterwards. Computed from the data, never hardcoded.
function labelViews() {
  const rel = DATA.filter(d => d.relevant).length;
  const fin = DATA.filter(d => d.relevant && d.fintech === true).length;
  const cu = DATA.filter(d => d.relevant && d.credit_union === true).length;
  $('#viewRelevant').textContent = `Banks, credit unions & fintechs (${rel})`;
  $('#viewAll').textContent = `Everything (${DATA.length})`;
  const f = $('[data-kind="fintech"]');
  if (f) f.textContent = `Fintech only (${fin})`;
  const c = $('[data-kind="credit_union"]');
  if (c) c.textContent = `Credit unions only (${cu})`;
}

function setView(all) {
  showAll = all;
  $('#viewAll').setAttribute('aria-pressed', String(all));
  $('#viewRelevant').setAttribute('aria-pressed', String(!all));
  $('#viewnote').textContent = all
    ? 'Showing everything collected, including items the filter set aside'
    : 'Showing items that met the community bank / fintech criteria';
  render();
}
$('#viewAll').addEventListener('click', () => setView(true));
$('#viewRelevant').addEventListener('click', () => setView(false));

const searchBox = $('#q');
searchBox.addEventListener('input', () => {
  query = searchBox.value.trim().toLowerCase();
  $('#clearq').hidden = !query;
  render();
});
$('#clearq').addEventListener('click', () => {
  searchBox.value = ''; query = ''; $('#clearq').hidden = true;
  searchBox.focus(); render();
});
// Escape clears the box — expected in a search field, and quicker than
// selecting the text to delete it.
searchBox.addEventListener('keydown', e => {
  if (e.key === 'Escape' && searchBox.value) { $('#clearq').click(); }
});

// One active filter at a time across pills AND kpi tiles, so selecting either
// clears the other.
function clearFilterUI() {
  document.querySelectorAll('.pill, .kpi[data-kpi]')
    .forEach(x => x.setAttribute('aria-pressed', 'false'));
  $('#viewnote').textContent = '';
}

document.querySelectorAll('.pill').forEach(p => p.addEventListener('click', () => {
  clearFilterUI();
  p.setAttribute('aria-pressed', 'true');
  filter = {kind: p.dataset.kind, value: p.dataset.value || ''};
  render();
}));

// KPI tiles filter the list to exactly what they count. Clicking the active tile
// again clears back to all. KPI items are all relevant, so also drop out of the
// "Everything" view for a consistent picture.
document.querySelectorAll('.kpi[data-kpi]').forEach(k => {
  const activate = () => {
    const key = k.dataset.kpi;
    const already = filter.kind === 'kpi' && filter.value === key;
    clearFilterUI();
    if (already) {
      filter = {kind: 'all', value: ''};
      const all = $('.pill[data-kind="all"]');
      if (all) all.setAttribute('aria-pressed', 'true');
    } else {
      filter = {kind: 'kpi', value: key};
      k.setAttribute('aria-pressed', 'true');
      $('#viewnote').textContent = 'Showing: ' + k.querySelector('.l').textContent;
      showAll = false;
      $('#viewAll').setAttribute('aria-pressed', 'false');
      $('#viewRelevant').setAttribute('aria-pressed', 'true');
    }
    render();
  };
  k.addEventListener('click', activate);
  k.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
  });
});

$('#export').addEventListener('click', () => {
  const rs = rows();
  const head = ['date','title','sources','type','urgency','comments_close_on','effective_on','url','summary'];
  const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [head.join(',')].concat(rs.map(d => [
    d.date, d.title, d.sources.join('; '), d.type, d.urgency,
    d.comments_close_on || '', d.effective_on || '', d.url, d.why
  ].map(cell).join(','))).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
  a.download = `regwatch-${TODAY}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// Open in the markup, collapsed here only on a phone. Written this way round so
// a script failure leaves the filters visible rather than hiding them entirely.
const showMoreBtn = document.getElementById('showmore');
if (showMoreBtn) showMoreBtn.addEventListener('click', () => {
  cardLimit = Infinity;
  userChoseLimit = true;
  render();
  showMoreBtn.hidden = true;
});

const dlMoreBtn = document.getElementById('dlmore');
if (dlMoreBtn) dlMoreBtn.addEventListener('click', () => {
  dlLimit = Infinity;
  userChoseDlLimit = true;
  render();
  dlMoreBtn.hidden = true;
});

const filtersEl = document.getElementById('filters');
if (filtersEl) filtersEl.addEventListener('toggle', () => { userToggledFilters = true; });

// Foldable panels collapse on a phone only. On desktop the heading is still a
// <summary>, so a click would fold the main update list -- block it there rather
// than leave a control that does something the desktop layout never intends.
const foldables = Array.from(document.querySelectorAll('.foldable'));
foldables.forEach(el => {
  const sum = el.querySelector('summary');
  if (sum) sum.addEventListener('click', e => { if (!MOBILE.matches) e.preventDefault(); });
});

function applyViewport() {
  if (!userChoseLimit) cardLimit = MOBILE.matches ? 8 : 25;
  if (!userChoseDlLimit) dlLimit = MOBILE.matches ? 6 : Infinity;
  // Re-open anything the reader folded on a phone before turning to landscape or
  // widening the window; a collapsed panel on desktop has no visible way back.
  if (!MOBILE.matches) foldables.forEach(el => { el.open = true; });
  if (filtersEl && !userToggledFilters) {
    // Assigning .open fires 'toggle', which would set the user flag — suppress it.
    const wanted = !MOBILE.matches;
    if (filtersEl.open !== wanted) {
      filtersEl.open = wanted;
      userToggledFilters = false;
    }
  }
  render();
}
MOBILE.addEventListener('change', applyViewport);
applyViewport();

labelViews();
setView(false);

// ------------------------------------------------------- Ask the tracked updates
// Retrieval happens HERE, in the browser: the page already holds every tracked
// update. Only the model call leaves, to a Cloudflare Worker that holds the API
// key server-side — so the key is never in this page, and searching costs
// nothing. corpus.json (the actual CFR text) is loaded only when the panel says
// data-regs="1"; see ASK_INCLUDE_REGULATIONS in dashboard.py for why it is off.
const ASK_ENDPOINT = 'https://regwatch-ask.alexandersmith14.workers.dev';

const STOP = new Set(('the a an and or of to in for on is are be as by with that this it at from '
  + 'any all no not may must shall will can under per each').split(' '));
const tok = s => (String(s).toLowerCase().match(/[a-z0-9]+/g) || [])
  .filter(w => w.length > 1 && !STOP.has(w));

let ASK_INDEX = null;

// BM25 (Okapi) over regs + tracked updates. Same ranking as the local tool.
function buildAskIndex(regs) {
  const passages = [];
  regs.forEach(s => passages.push({
    kind: 'regulation', label: s.citation, title: s.heading,
    stamp: 'as of ' + s.as_of,
    text: s.reg_name + ' ' + s.heading + ' ' + s.text,
  }));
  DATA.filter(d => d.relevant).forEach(d => passages.push({
    kind: 'update', label: (d.sources || []).join(', '), title: d.title,
    stamp: 'dated ' + d.date,
    text: d.title + ' ' + (d.why || '') + ' ' + (d.tags || []).join(' '),
  }));
  const docs = passages.map(p => tok(p.text));
  const N = docs.length, avgdl = docs.reduce((a, d) => a + d.length, 0) / (N || 1);
  const df = {};
  docs.forEach(d => new Set(d).forEach(t => { df[t] = (df[t] || 0) + 1; }));
  const idf = {};
  for (const t in df) idf[t] = Math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5));
  const tf = docs.map(d => { const c = {}; d.forEach(t => c[t] = (c[t] || 0) + 1); return c; });
  return { passages, docs, idf, tf, avgdl, k1: 1.5, b: 0.75 };
}

function askSearch(q, k) {
  const ix = ASK_INDEX, terms = tok(q), scored = [];
  for (let i = 0; i < ix.passages.length; i++) {
    const c = ix.tf[i], dl = ix.docs[i].length;
    let s = 0;
    for (const t of terms) {
      if (!c[t]) continue;
      s += (ix.idf[t] || 0) * (c[t] * (ix.k1 + 1)) /
           (c[t] + ix.k1 * (1 - ix.b + ix.b * dl / ix.avgdl));
    }
    if (s > 0) scored.push([s, i]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, k).map(([, i]) => ix.passages[i]);
}

// The models answer in markdown; render the small subset they actually use.
function askMd(t) {
  return t.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))
    .replace(/^#{1,6}\s*(.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^\s*[-*]\s+(.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '<br><br>');
}

(function initAsk() {
  const q = $('#askq'), go = $('#askgo'), out = $('#askout');
  if (!q || !go) return;
  const say = html => { out.innerHTML = html; };

  // No model picker. Every question goes to every model the Worker has a key
  // for, and the Worker reconciles them into one answer. "Best available" asked
  // the reader to choose between three names they have no way to rank.

  // corpus.json is fetched only when the panel asks for regulations. With it off
  // the index is the tracked updates alone, so there is no CFR text in front of
  // the models and no subsections for them to invent.
  const WANT_REGS = document.querySelector('.ask-panel')?.dataset.regs === '1';

  async function ensureIndex() {
    if (ASK_INDEX) return true;
    if (!WANT_REGS) { ASK_INDEX = buildAskIndex([]); return true; }
    try {
      const r = await fetch('corpus.json');
      ASK_INDEX = buildAskIndex(r.ok ? await r.json() : []);
    } catch (e) {
      ASK_INDEX = buildAskIndex([]);   // updates-only still answers usefully
    }
    return true;
  }

  async function ask() {
    const question = q.value.trim();
    if (!question) return;
    go.disabled = true;
    say('<div class="ans">Searching the tracked updates&hellip;</div>');
    try {
      await ensureIndex();
      // 12 is what the free tiers accept; more makes Groq return 413.
      const passages = askSearch(question, 12);
      if (!passages.length) {
        say('<div class="ans">Nothing in the tracked updates matches that. '
          + 'Try different wording, or search the list below.</div>');
        return;
      }
      say('<div class="ans">Asking the models and comparing their answers&hellip;</div>');
      const res = await fetch(ASK_ENDPOINT, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question, passages}),
      });
      const d = await res.json();
      if (d.error) { say('<div class="ans warn">' + esc(d.error) + '</div>'); return; }

      const all = d.answers || [];
      const good = all.filter(a => a.text && a.text.trim());
      if (!good.length) {
        // Every model failed — usually free-tier quota. Say which and why.
        say('<div class="ans warn">No model could answer just now.<br>'
          + all.map(a => esc(a.provider) + ': ' + esc(a.error || 'no answer')).join('<br>')
          + '</div>');
        return;
      }

      // One answer to read. The reconcile pass is instructed to state the
      // models' disagreements inside the text, so a single block is not hiding
      // a split — but the raw answers stay one click away, because "they
      // agreed" is a claim the reader should be able to check.
      const main = d.merged ? d.merged.text : good[0].text;
      let note;
      if (d.merged) {
        note = 'Reconciled from ' + good.length + ' models'
             + (good.length < (d.asked || good.length)
                 ? ' (' + (d.asked - good.length) + ' unavailable)' : '')
             + (d.merged.independent
                 ? ' by a separate model.'
                 : ' by one of them — no independent reconciler configured.');
      } else {
        note = good.length + ' of ' + (d.asked || good.length)
             + ' models answered, so there was nothing to compare.';
      }

      let raw = '';
      if (good.length > 1) {
        raw = '<details class="askraw"><summary>See the ' + good.length
            + ' separate answers</summary>'
            + good.map(a => '<div class="ans"><div class="who">' + esc(a.provider)
                + ' &middot; ' + esc(a.model) + '</div>' + askMd(a.text) + '</div>').join('')
            + '</details>';
      }

      const cites = [...new Set(passages.map(p => p.label))].join(' &middot; ');
      say('<div class="ans">' + askMd(main) + '</div>' + raw
        + '<div class="cites">' + note + '<br>Grounded in: ' + cites + '</div>');
    } catch (e) {
      say('<div class="ans warn">The assistant is unavailable right now. '
        + 'Everything below still works.</div>');
    } finally {
      go.disabled = false;
    }
  }
  go.addEventListener('click', ask);
  q.addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });
})();
"""

# Feeds grouped under the agency that publishes them. Several agencies use more
# than one channel, and the split is an artefact of how we fetch, not something a
# reader cares about — nobody thinks "FDIC versus FDIC FILs", they think "FDIC".
#
# This also fixes a real gap. The pills used to be the top nine feeds by volume,
# which meant you could filter to "Fed SR/CA Letters" but not to "Federal
# Reserve", and to "OCC Bulletins" but not "OCC" — the two most recognisable
# banking regulators looked missing, and 16 relevant items sat behind no pill at
# all. Grouped, eight pills reach 100% of items with no truncation.
AGENCY_GROUPS = [
    ("FDIC", ["FDIC", "FDIC FILs"]),
    ("OCC", ["OCC", "OCC Bulletins"]),
    ("Federal Reserve", ["Federal Reserve", "Fed SR/CA Letters"]),
    ("CFPB", ["CFPB", "CFPB Rules"]),
    ("FinCEN", ["FinCEN", "FinCEN Advisories"]),
    ("NCUA", ["NCUA", "NCUA Press"]),
    ("OFAC", ["OFAC"]),
    ("CSBS", ["CSBS"]),
    # State regulators. Labelled by state so the pill reads as the state, not the
    # feed name — a reader filters by "Florida", not "FL OFR Press".
    ("Florida", ["FL OFR Press"]),
    ("Texas", ["TX Dept of Banking"]),
]


def build_rows(store):
    rows = []
    for r in store.values():
        rows.append({
            "title": r.get("title", ""), "url": r.get("url", ""),
            "fr_url": r.get("fr_url"), "date": r.get("date", ""),
            "sources": r.get("sources", []), "type": r.get("update_type", ""),
            "urgency": r.get("urgency", "Low"), "relevant": bool(r.get("relevant")),
            "why": r.get("plain_english", ""), "tags": r.get("tags", []),
            "fintech": bool(r.get("fintech_specific")),
            "credit_union": bool(r.get("credit_union")),
            "comments_close_on": r.get("comments_close_on"),
            "effective_on": r.get("effective_on"),
        })
    rows.sort(key=lambda d: (d["date"] or "0000"), reverse=True)
    return rows


def kpis(rows, today):
    """Headline numbers, and tag each item with the tiles it belongs to.

    Each relevant row gets r["kpi"] = the list of tile keys it satisfies, and the
    tile counts are derived from those tags — so a tile's number and the list you
    get by clicking it are computed once and cannot drift apart. Non-relevant rows
    get an empty list, which also makes the click filter relevant-only for free.
    """
    def within(d, lo, hi):
        return bool(d) and str(lo) <= d <= str(hi)

    wk_start = today - timedelta(days=7)
    prev_start = today - timedelta(days=14)
    month_start = today.replace(day=1)
    q_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    q_end = date(today.year + (q_start.month + 3 > 12), ((q_start.month + 2) % 12) + 1, 28)
    soon_end = today + timedelta(days=30)

    for r in rows:
        r["kpi"] = []
    rel = [r for r in rows if r["relevant"]]

    last_wk = 0
    for r in rel:
        if within(r["date"], wk_start, today):
            r["kpi"].append("week")
        if within(r["date"], prev_start, wk_start):
            last_wk += 1
        if r["comments_close_on"] and r["comments_close_on"] >= str(today):
            r["kpi"].append("comments")
        if r["type"] == "Enforcement Action" and within(r["date"], month_start, today):
            r["kpi"].append("enforcement")
        if r["effective_on"] and str(q_start) <= r["effective_on"] <= str(q_end):
            r["kpi"].append("effective")

    def count(key):
        return sum(1 for r in rel if key in r["kpi"])

    this_wk = count("week")
    soon = sum(1 for r in rel if "comments" in r["kpi"]
               and r["comments_close_on"] <= str(soon_end))
    delta = this_wk - last_wk
    dn = "up" if delta > 0 else "down" if delta < 0 else ""
    dtxt = f"{'+' if delta > 0 else ''}{delta} vs last week" if delta else "same as last week"
    # (label, value, note, delta-class, tile key)
    return [
        ("Updates this week", this_wk, dtxt, dn, "week"),
        ("Open comment periods", count("comments"), f"{soon} closing within 30 days", "", "comments"),
        ("Enforcement actions", count("enforcement"), "This month", "", "enforcement"),
        ("Effective this quarter", count("effective"),
         f"Rules taking effect by {q_end.strftime('%b %Y')}", "", "effective"),
    ]


def _cfr_cell(cfr):
    url = ecfr_url(cfr)
    if not url:
        return html.escape(cfr)
    return (f'<a href="{url}" target="_blank" rel="noopener">'
            f'{html.escape(cfr)}</a>')


def regref_panel():
    """Federal Reserve regulation letter lookup, collapsed by default.

    Sits beside the tracker so a reader who hits "Regulation B" in an item can
    see what it covers without leaving the page. Rendered as static HTML and
    filtered client-side by the same search box as everything else.
    """
    blocks = []
    for group, desc, entries in regref.GROUPS:
        rows = "".join(
            # Searchable text includes the spoken forms — "regulation d" and
            # "reg d" — not just the bare letter, so the way people actually
            # type it finds the row.
            f'<tr class="rr" data-rr="{html.escape(" ".join([letter, "regulation " + letter, "reg " + letter, subject, cfr]).lower(), quote=True)}">'
            f'<td class="rr-letter">{html.escape(letter)}</td>'
            f'<td>{subject}'
            + (f'<div class="rr-note">{note}</div>' if note else "")
            # The cite links to the part on eCFR. All 47 were checked to resolve.
            # It stays a lookup aid, not a citation source — the caveat above the
            # table still stands, and eCFR is the current text, not a point-in-time
            # version, so anything being cited should be confirmed there directly.
            + f'</td><td class="rr-cfr">{_cfr_cell(cfr)}</td></tr>'
            for letter, subject, cfr, note in entries
        )
        blocks.append(
            f'<div class="rr-group"><h3>{html.escape(group)}</h3>'
            f'<p class="note">{html.escape(desc)}</p>'
            f'<table class="rr-table"><thead><tr><th>Reg</th><th>Subject</th>'
            f'<th>CFR</th></tr></thead><tbody>{rows}</tbody></table></div>'
        )

    # Omit the list entirely when there are no footnotes, rather than emitting an
    # empty <ul> that renders as stray padding.
    notes = (
        f'<ul class="rr-foot">{"".join(f"<li>{n}</li>" for n in regref.FOOTNOTES)}</ul>'
        if regref.FOOTNOTES else ""
    )
    return (
        '<details class="coverage" id="regref"><summary>'
        'Federal Reserve regulation reference (A&ndash;YY)</summary>'
        '<div class="body">'
        '<p>What each regulation letter covers, and where it now lives in the CFR. '
        'This is a lookup aid, not a citation source — confirm anything you intend '
        'to cite against the '
        '<a href="https://www.federalreserve.gov/supervisionreg/reglisting.htm" '
        'target="_blank" rel="noopener">Federal Reserve\'s own regulation listing</a>. '
        'Reserved and never-finalised letters are omitted.</p>'
        f'{"".join(blocks)}'
        f"{notes}"
        "</div></details>"
    )


def coverage_panel(store):
    """Build the 'what this covers' panel from the store itself.

    Generated rather than written by hand so it can't drift from reality — if a
    source breaks or is dropped, the panel stops claiming we track it. A public
    tool that silently under-reports is worse than no tool, because absence reads
    as "nothing happened".
    """
    # Live sources come from fetcher.py, not from the store. The store keeps
    # records from feeds that were trialled and dropped — SEC, FTC and CFTC were
    # each measured at 0 of 10 relevant and removed — and reading it alone made
    # this panel claim to track FTC and CFTC while the paragraph directly below
    # said it did not. A public page contradicting itself about its own coverage
    # is worse than one that says less.
    active = {s["agency"] for s, _ in fetcher.SOURCES}

    per = {}
    for r in store.values():
        for a in r.get("sources", []):
            if a in active and str(r.get("date", "")).startswith("20"):
                per.setdefault(a, []).append(r["date"])

    rows = []
    for agency in sorted(per):
        d = sorted(per[agency])
        url = SOURCE_LINKS.get(agency)
        name = html.escape(agency)
        # Linked to the agency's own listing page so a reader can check the
        # source rather than take this page's word for it.
        label = (f'<a href="{url}" target="_blank" rel="noopener">{name}</a>'
                 if url else name)
        rows.append(
            f'<div><strong>{label}</strong> — '
            f'{len(d)} items, {d[0]} to {d[-1]}</div>'
        )

    # State regulators are tracked selectively now, so the "not tracked" note has
    # to name the exceptions or the panel contradicts itself the way it did over
    # FTC/CFTC. Which states are tracked is detected from the live source list
    # (agency names beginning with a 2-letter state code), so this stays correct
    # as states are added or removed rather than drifting against a hard-coded list.
    STATE_NAMES = {"FL": "Florida", "TX": "Texas"}
    tracked_states = sorted({
        STATE_NAMES.get(a.split()[0], a.split()[0])
        for a in active if a[:2] in STATE_NAMES and a[2:3] == " "
    })
    if tracked_states:
        joined = (tracked_states[0] if len(tracked_states) == 1
                  else " and ".join([", ".join(tracked_states[:-1]), tracked_states[-1]])
                  if len(tracked_states) > 2
                  else " and ".join(tracked_states))
        state_note = (
            'MOST state regulators (including NYDFS and California DFPI, which '
            f'block automated access) — {joined} are tracked and are the exception')
    else:
        state_note = ('state regulators (including NYDFS and California DFPI, '
                      'which block automated access)')

    tracked_intro = (
        'the US federal banking and financial-crime agencies listed below'
        + (f', plus the {joined} state financial regulators' if tracked_states else '')
        + '. History depth varies by source — some publish archives going back '
        'years, others only their most recent items.')
    return (
        '<details class="coverage"><summary>What this covers, and what it does not'
        '</summary><div class="body">'
        f'<p><strong>Tracked:</strong> {tracked_intro}</p>'
        f'<div class="grid">{"".join(rows)}</div>'
        # Moved here from the always-visible notice, which ran to six lines on a
        # phone. The instruction a reader must act on ("open the source") stays
        # up top; this is the explanation of how deadlines are derived, which is
        # reference and belongs with the other scope caveats.
        '<p style="margin-top:12px"><strong>Deadlines:</strong> shown only where a '
        'Federal Register record could be matched, and taken from that record\'s '
        'structured fields. An item showing no deadline has no match — that does '
        'not mean no deadline exists.</p>'
        f'<p><strong>Not tracked:</strong> {state_note}, '
        'FFIEC, SEC, FTC and CFTC. Congressional activity and court decisions are '
        'not covered. Anything an agency published but did not list on the pages '
        'above will be missing.</p>'
        '<p><strong>Relevance:</strong> items are screened against a profile of US '
        'community banks (under ~$10B assets), federally-insured credit unions, and '
        'fintechs — BaaS and sponsor-bank arrangements, prepaid and FBO accounts, '
        'consumer lending and credit risk, BSA/AML, NCUA and share-insurance '
        'matters, and internal audit. Items outside that scope are collected but '
        'filtered out, so this is not a complete record of everything these '
        'agencies publish.</p>'
        "</div></details>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    with open(STORE_PATH, encoding="utf-8") as f:
        store = json.load(f)

    rows = build_rows(store)
    today = datetime.now(timezone.utc).date()

    # Busiest agency first, so the ordering carries information rather than being
    # alphabetical by accident. Empty groups are dropped — a pill that returns
    # nothing is worse than no pill.
    relevant_rows = [d for d in rows if d["relevant"]]
    group_counts = [
        (label, feeds, sum(1 for d in relevant_rows
                           if any(f in d["sources"] for f in feeds)))
        for label, feeds in AGENCY_GROUPS
    ]
    group_counts = sorted((g for g in group_counts if g[2]),
                          key=lambda g: -g[2])

    source_pills = (
        '<button class="pill" data-kind="all" aria-pressed="true">All</button>'
        + "".join(f'<button class="pill" data-kind="agency" '
                  f'data-value="{hesc("|".join(feeds), quote=True)}" '
                  f'aria-pressed="false">{hesc(label)}</button>'
                  for label, feeds, _ in group_counts)
    )

    # Live counts in the share description, so the preview reflects reality
    # rather than a number that quietly goes stale.
    share_desc = (
        f"{sum(1 for d in rows if d['relevant'])} regulatory updates affecting "
        f"community banks, credit unions and fintechs, tracked across US federal "
        f"regulators and Florida's OFR. Plain-English summaries, comment "
        f"deadlines and effective dates. Updated daily."
    )

    coverage_html = coverage_panel(store)
    regref_html = regref_panel()

    # Tiles are clickable when they count something — clicking filters the list to
    # exactly those items. A zero tile is left inert (nothing to show).
    kpi_html = "".join(
        (f'<div class="kpi" data-kpi="{key}" role="button" tabindex="0" '
         f'aria-pressed="false">' if val else '<div class="kpi">')
        + f'<div class="l">{lbl}</div><div class="v">{val}</div>'
          f'<div class="n {cls}">{note}</div></div>'
        for lbl, val, note, cls, key in kpis(rows, today)
    )

    # Gated on ASK_ENABLED — see the note at the top of this file. When off the
    # panel is simply absent; initAsk() finds no #askq and returns, so no
    # corpus.json fetch and no call to the Worker.
    # data-regs is read by initAsk() to decide whether to load corpus.json, so
    # the scope of the feature is set here in Python, not duplicated in the JS.
    ask_html = f"""
<!-- Ask sits after the numbers and the filters, not before them. The tiles and
     the search box are what most readers came for and they cost nothing; the
     question box is the slow, optional thing. -->
<div class="ask-panel" data-regs="{1 if ASK_INCLUDE_REGULATIONS else 0}">
  <h2>Ask the tracked updates</h2>
  <p class="sub">Answers are drawn from the {'regulation text and the ' if ASK_INCLUDE_REGULATIONS else ''}updates
    tracked on this page, with sources named. Every question goes to three
    separate models and their answers are reconciled into one, with any
    disagreement between them stated in the answer. This is research to verify
    against the source &mdash; not legal or compliance advice.</p>
  <div class="ask-row">
    <input id="askq" autocomplete="off" maxlength="400"
           placeholder="e.g. what has FinCEN said about beneficial ownership?"
           aria-label="Ask a question about the tracked updates">
    <button id="askgo" type="button">Ask</button>
  </div>
  <div id="askout" aria-live="polite"></div>
  <div class="ask-note">Covers the updates tracked below{', and Regulation B, E and DD' if ASK_INCLUDE_REGULATIONS else ' &mdash; not regulation text'}.
    Answers can be wrong or incomplete &mdash; always open the source.</div>
</div>
""" if ASK_ENABLED else ""

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Regulatory update tracker — community banks, credit unions &amp; fintechs</title>
<meta name="description" content="{share_desc}">
<!-- Tab, bookmark and home-screen icons. Generated by make_icons.py; the paths
     are relative because the site is served from a /regwatch/ subpath, not a
     domain root. Anything absolute here 404s. -->
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="icon-32.png" sizes="32x32">
<link rel="icon" type="image/png" href="icon-16.png" sizes="16x16">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="site.webmanifest">
<meta name="theme-color" content="#003b6a">
<!-- Open Graph / Twitter card. Social scrapers cannot render the page, so the
     preview is driven entirely by these tags plus a real image file. Without
     them LinkedIn shows a bare URL with no title, description or image. -->
<meta property="og:type" content="website">
<meta property="og:site_name" content="RegWatch">
<meta property="og:title" content="Regulatory update tracker — community banks, credit unions &amp; fintechs">
<meta property="og:description" content="{share_desc}">
<meta property="og:url" content="{SITE_URL}">
<meta property="og:image" content="{SITE_URL}og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Regulatory update tracker for community banks, credit unions and fintechs">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Regulatory update tracker — community banks, credit unions &amp; fintechs">
<meta name="twitter:description" content="{share_desc}">
<meta name="twitter:image" content="{SITE_URL}og-image.png">
<style>{CSS}</style></head>
<body data-today="{today}"><div class="wrap">

<header>
  <div class="t">
    <h1>Regulatory update tracker</h1>
    <!-- The audience and the timestamp are two different facts. Run together they
         wrapped to three ragged lines on a phone; as separate blocks they are two
         tidy ones, and the stamp can be dimmed since it is reference, not billing. -->
    <p class="sub">Community banks, credit unions &amp; fintechs<span class="stamp">Updated
      {datetime.now(timezone.utc).strftime('%B %-d, %Y %H:%M UTC') if os.name != 'nt'
       else datetime.now(timezone.utc).strftime('%B %d, %Y %H:%M UTC')}</span></p>
  </div>
  <!-- "Export" is hidden on a phone, leaving "CSV". The full label cost 102px of
       a 366px row, which is what forced the title onto two lines. -->
  <button id="export"><span class="lbl-full">Export </span>CSV</button>
</header>

<!-- The visible caveat is now the instruction only: what the summaries are, and
     what to do about it. How deadlines are derived moved into "What this covers"
     with the other scope caveats — it explains rather than instructs, and it was
     costing two of six lines on a phone. Nothing was deleted. -->
<div class="notice">
  <strong>Read this first.</strong> The summaries are based on agency listings.
  Always open the source document before acting on anything here.
  <div style="margin-top:9px">{coverage_html}</div>
  <div style="margin-top:6px">{regref_html}</div>
</div>

<div class="kpis">{kpi_html}</div>
<div class="pillgroup">
  <div class="grouplabel">Search<small>any word</small></div>
  <div class="searchwrap">
    <input id="q" type="search" autocomplete="off"
           placeholder="e.g. stablecoin, Regulation B, comment period…"
           aria-label="Search updates">
    <button id="clearq" type="button" hidden aria-label="Clear search">&times;</button>
  </div>
</div>
<!-- Search stays visible; the rest collapses on a phone. Kept as one <details>
     that JS opens on wide screens, so desktop is unchanged and mobile gets ~330px
     of pills back above the first update. -->
<details id="filters" open>
  <summary>Filters &amp; view</summary>
  <div class="pillgroup">
    <div class="grouplabel">View<small>how much to show</small></div>
    <div class="viewtoggle">
      <!-- "Relevant only" was self-referential: relevant to whom? These say who
           the page is for. Counts are filled in by script so they cannot go
           stale against the data. -->
      <button id="viewRelevant" aria-pressed="true">Banks, credit unions &amp; fintechs</button>
      <button id="viewAll" aria-pressed="false">Everything</button>
    </div>
    <!-- Fintech and Credit unions sit with the view toggle, not with Source,
         because they are the same kind of control: lenses on the classifier's
         judgment rather than keywords, and the two filters the search box cannot
         reproduce (a text match on "fintech"/"credit union" is far noisier). -->
    <button class="pill" data-kind="fintech" aria-pressed="false">Fintech only</button>
    <button class="pill" data-kind="credit_union" aria-pressed="false">Credit unions only</button>
    <span class="count" id="viewnote"></span>
  </div>
  <div class="pillgroup">
    <div class="grouplabel">Source<small>who published it</small></div>
    {source_pills}
  </div>
</details>

{ask_html}
<div class="cols">
  <div class="colmain">
    <!-- <details> rather than <div> so these fold on a phone, same mechanism as
         the filter block. Left open in the markup: a script failure must leave
         the content readable, never collapse the page to a row of headings. -->
    <details class="panel p-updates foldable" open>
      <summary><h2>Latest updates <span style="float:right;text-transform:none;letter-spacing:0"
          id="cardcount"></span></h2></summary>
      <div id="cards"></div>
      <button id="showmore" type="button" hidden>Show more updates</button>
    </details>
    <div id="alsofound"></div>
  </div>
  <div class="colside">
    <details class="panel p-deadlines foldable" open>
      <summary><h2>Upcoming deadlines</h2></summary>
      <div id="deadlines"></div>
      <!-- Hidden in the markup and revealed by script only when something is
           actually capped, so a script failure leaves every deadline visible
           rather than a button that does nothing. -->
      <button id="dlmore" type="button" hidden>Show more deadlines</button>
    </details>
    <div class="panel p-agencies">
      <h2>Updates by agency</h2>
      <div class="agrow" id="agencies"></div>
    </div>
  </div>
</div>

<div class="contact">
  <div class="who">
    <div class="name">Built by Alexander Smith, CRCM, CFE</div>
    <div class="role">Risk Advisory Services &middot; Kaufman Rossin</div>
    <div class="pitch">I built this to track regulatory activity affecting
      community banks, credit unions and fintechs. If you're impacted by any of these
      updates, or have questions, please feel free to reach out to see how we can help.</div>
  </div>
  <div class="acts">
    <a class="btn primary" href="https://www.linkedin.com/in/alexandersmith14/"
       target="_blank" rel="noopener">Connect on LinkedIn</a>
    <a class="btn" href="mailto:asmith@kaufmanrossin.com?subject=RegWatch%20regulatory%20tracker">Email me</a>
    <a class="btn" href="https://kaufmanrossin.com/professionals/alexander-smith/"
       target="_blank" rel="noopener">Full bio</a>
  </div>
</div>

<footer>Deadlines are structured fields from matched Federal Register documents.
Summaries are model-generated from agency listings and are not a substitute for
reading the source document. Not legal or compliance advice.</footer>
</div>
<script type="application/json" id="data">{json.dumps(rows)}</script>
<script type="application/json" id="groups">{json.dumps(AGENCY_GROUPS)}</script>
<script>{JS}</script>
</body></html>"""

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT_PATH} ({os.path.getsize(OUT_PATH)/1024:.0f} KB) — "
          f"{sum(1 for r in rows if r['relevant'])} relevant of {len(rows)} events")
    if args.open:
        webbrowser.open("file://" + os.path.abspath(OUT_PATH))


if __name__ == "__main__":
    main()
