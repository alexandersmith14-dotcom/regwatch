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
import os
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import regref

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
/* museo-sans is the firm's typeface but it's licensed through Adobe Fonts and
   can't be embedded in a self-contained file. This is the exact fallback chain
   kaufmanrossin.com declares after it, so the dashboard matches what the site
   shows on any machine without a Typekit licence. Calibri ships with Windows. */
body{margin:0;padding:22px;background:var(--page);color:var(--ink);
  font:14px/1.55 museo-sans,Calibri,Georgia,Verdana,sans-serif}
.wrap{max-width:1240px;margin:0 auto}
header{display:flex;align-items:center;gap:16px;margin-bottom:20px;
  background:var(--brand-bg);color:#fff;padding:18px 22px;border-radius:8px;
  border-bottom:4px solid var(--accent)}
header .t{flex:1}
h1{font-size:21px;margin:0 0 3px;color:#fff;font-weight:700;letter-spacing:-.01em}
.sub{color:rgba(255,255,255,.82);font-size:13px;margin:0}
/* Bookmark hint. Starts hidden and is revealed by script only on a device with
   a keyboard, since Ctrl+D means nothing on a phone. */
.bmk{display:none;align-items:center;gap:8px;margin:7px 0 0;
  font-size:12px;color:rgba(255,255,255,.62)}
.bmk kbd{font:inherit;font-size:11px;padding:2px 6px;border-radius:4px;
  background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.22);
  color:rgba(255,255,255,.92)}
.bmk button{background:none;border:0;padding:0 2px;cursor:pointer;font-size:15px;
  line-height:1;color:rgba(255,255,255,.45)}
.bmk button:hover{background:none;color:rgba(255,255,255,.85)}
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

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:12px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:14px 16px}
.kpi .l{font-size:12px;color:var(--ink-2)}
.kpi .v{font-size:32px;line-height:1.15;letter-spacing:-.02em;margin:6px 0 2px}
.kpi .n{font-size:12px;color:var(--ink-muted)}
.kpi .n.up{color:var(--crit)} .kpi .n.down{color:var(--ok)}

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

/* Phone layout. The desktop proportions put 1,434px of header, counts and
   filters above the first actual update — nearly two full screens of scrolling
   before any content, on the device most LinkedIn traffic arrives from.
   Everything here buys that height back. */
@media (max-width:640px){
  body{padding:12px}
  header{padding:14px 16px;gap:12px;margin-bottom:14px}
  h1{font-size:18px}
  .sub{font-size:12px}
  .notice{padding:11px 13px;font-size:12.5px;margin-bottom:14px}

  /* Two-up instead of stacked: four numbers in half the height. */
  .kpis{grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}
  .kpi{padding:10px 12px;border-radius:8px}
  .kpi .v{font-size:23px;margin:3px 0 1px}
  .kpi .l,.kpi .n{font-size:11px;line-height:1.3}

  /* Label above the controls rather than beside them — the fixed 104px column
     was taking 31% of a 331px content width and pushing the source pills onto
     five rows. */
  .grouplabel{width:100%;flex:0 0 100%;margin-bottom:1px}
  .grouplabel small{display:inline;margin-left:6px}
  .pillgroup{gap:6px;margin-bottom:11px}
  .pill{padding:5px 11px;font-size:12px}
  .searchwrap{flex:1 1 100%;max-width:none}

  .panel{padding:13px 14px}
  .cols{gap:14px}
  .card h3{font-size:14px}
  .card p{font-size:12.5px}

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

  /* Bigger touch targets. */
  .pill{padding:8px 13px}
  .viewtoggle button{padding:9px 15px}
  .card h3{line-height:1.45}
  .card h3 a{display:inline-block;padding:2px 0}
  #showmore{width:100%;margin-top:12px;padding:11px;font-weight:600;
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
"""

JS = r"""
const DATA = JSON.parse(document.getElementById('data').textContent);
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
    if (filter.kind === 'agency') return d.sources.includes(filter.value);
    // Fintech uses the classifier's explicit judgment, not a word match. Matching
    // the text found ~55 items because the model padded most summaries with the
    // phrase "community banks and fintechs"; the real count is 14.
    if (filter.kind === 'fintech') return d.fintech === true;
    // Topics match any term in a list, not one literal word. A single keyword
    // silently under-reports: "Lending" missed "loan" and "credit", and
    // "Prepaid / FBO" would have missed an FBO item written as
    // "for-benefit-of accounts".
    if (filter.kind === 'tag') {
      const hay = ((d.tags || []).join(' ') + ' ' + d.title + ' ' + d.why).toLowerCase();
      return filter.value.split('|').some(t => hay.includes(t));
    }
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
const MOBILE = window.matchMedia('(max-width:640px)');
let cardLimit = MOBILE.matches ? 8 : 25;
let userChoseLimit = false;      // never override an explicit "show more"
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
  $('#deadlines').innerHTML = items.length ? items.map(({d, when, what}) => {
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
}

function renderAgencies(rs) {
  const c = {};
  rs.forEach(d => d.sources.forEach(s => c[s] = (c[s] || 0) + 1));
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

document.querySelectorAll('.pill').forEach(p => p.addEventListener('click', () => {
  document.querySelectorAll('.pill').forEach(x => x.setAttribute('aria-pressed', 'false'));
  p.setAttribute('aria-pressed', 'true');
  filter = {kind: p.dataset.kind, value: p.dataset.value || ''};
  render();
}));

// Bookmark tip. There is no way to bookmark a page from script -- every browser
// removed that years ago -- so the most any page can honestly do is name the
// shortcut. Shown only where the shortcut exists, and only until dismissed.
(() => {
  const tip = $('#bmk');
  if (!tip) return;
  // A coarse pointer with no hover is a touch device: no Ctrl, no Cmd, and the
  // browser's own "add to home screen" already covers saving the page there.
  const touch = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  let dismissed = false;
  try { dismissed = localStorage.getItem('bmk') === 'off'; } catch (e) {}
  if (touch || dismissed) return;
  const mac = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent);
  $('#bmkkey').textContent = mac ? '⌘' : 'Ctrl';
  tip.style.display = 'flex';
  $('#bmkx').addEventListener('click', () => {
    tip.style.display = 'none';
    // Private-mode browsers throw on write; the tip simply returns next visit.
    try { localStorage.setItem('bmk', 'off'); } catch (e) {}
  });
})();

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

setView(false);
"""

# Each topic is a set of terms matched against tags + title + summary. Pipe
# separated because the value rides in a data- attribute.
TOPIC_PILLS = [
    ("BSA / AML",
     "aml|bsa|money laundering|sanction|ofac|suspicious activity|"
     "beneficial owner|know your customer|customer identification|314(b)"),
    ("Lending",
     "lending|loan|credit|underwriting|mortgage|ecoa|regulation b|"
     "fair lending|hmda|truth in lending"),
    ("Enforcement",
     "enforcement|consent order|civil money penalty|cease and desist|"
     "settlement|charges|restitution"),
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
            "comments_close_on": r.get("comments_close_on"),
            "effective_on": r.get("effective_on"),
        })
    rows.sort(key=lambda d: (d["date"] or "0000"), reverse=True)
    return rows


def kpis(rows, today):
    """Headline numbers. Only counts we can actually substantiate."""
    def within(d, lo, hi):
        return bool(d) and str(lo) <= d <= str(hi)

    wk_start = today - timedelta(days=7)
    prev_start = today - timedelta(days=14)
    rel = [r for r in rows if r["relevant"]]

    this_wk = sum(1 for r in rel if within(r["date"], wk_start, today))
    last_wk = sum(1 for r in rel if within(r["date"], prev_start, wk_start))
    delta = this_wk - last_wk

    open_c = [r for r in rel if r["comments_close_on"] and r["comments_close_on"] >= str(today)]
    soon = sum(1 for r in open_c if r["comments_close_on"] <= str(today + timedelta(days=30)))

    month_start = today.replace(day=1)
    enf = sum(1 for r in rel if r["type"] == "Enforcement Action"
              and within(r["date"], month_start, today))

    q_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    q_end = date(today.year + (q_start.month + 3 > 12), ((q_start.month + 2) % 12) + 1, 28)
    eff = sum(1 for r in rel if r["effective_on"] and str(q_start) <= r["effective_on"] <= str(q_end))

    dn = "up" if delta > 0 else "down" if delta < 0 else ""
    dtxt = f"{'+' if delta > 0 else ''}{delta} vs last week" if delta else "same as last week"
    return [
        ("Updates this week", this_wk, dtxt, dn),
        ("Open comment periods", len(open_c), f"{soon} closing within 30 days", ""),
        ("Enforcement actions", enf, "This month", ""),
        ("Effective this quarter", eff, f"Rules taking effect by {q_end.strftime('%b %Y')}", ""),
    ]


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
            + f'</td><td class="rr-cfr">{html.escape(cfr)}</td></tr>'
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
    per = {}
    for r in store.values():
        for a in r.get("sources", []):
            if str(r.get("date", "")).startswith("20"):
                per.setdefault(a, []).append(r["date"])

    rows = []
    for agency in sorted(per):
        d = sorted(per[agency])
        rows.append(
            f'<div><strong>{html.escape(agency)}</strong> — '
            f'{len(d)} items, {d[0]} to {d[-1]}</div>'
        )

    return (
        '<details class="coverage"><summary>What this covers, and what it does not'
        '</summary><div class="body">'
        '<p><strong>Tracked:</strong> the US federal banking and financial-crime '
        'agencies listed below. History depth varies by source — some publish '
        'archives going back years, others only their most recent items.</p>'
        f'<div class="grid">{"".join(rows)}</div>'
        '<p style="margin-top:12px"><strong>Not tracked:</strong> state regulators '
        '(including NYDFS and California DFPI, which block automated access), '
        'FFIEC, SEC, FTC and CFTC. Congressional activity and court decisions are '
        'not covered. Anything an agency published but did not list on the pages '
        'above will be missing.</p>'
        '<p><strong>Relevance:</strong> items are screened against a profile of US '
        'community banks (under ~$10B assets) and fintechs — BaaS and sponsor-bank '
        'arrangements, prepaid and FBO accounts, consumer lending and credit risk, '
        'BSA/AML, and internal audit. Items outside that scope are collected but '
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
    agencies = [a for a, _ in Counter(
        s for d in rows if d["relevant"] for s in d["sources"]).most_common(9)]

    # Grouped so it's obvious that one row filters by publisher and the other by
    # subject — they look identical otherwise and read as one arbitrary list.
    source_pills = (
        '<button class="pill" data-kind="all" aria-pressed="true">All</button>'
        + "".join(f'<button class="pill" data-kind="agency" data-value="{a}" '
                  f'aria-pressed="false">{a}</button>' for a in agencies)
    )
    topic_pills = (
        '<button class="pill" data-kind="fintech" aria-pressed="false">Fintech</button>'
        + "".join(f'<button class="pill" data-kind="tag" data-value="{v}" '
                  f'aria-pressed="false">{lbl}</button>' for lbl, v in TOPIC_PILLS)
    )

    # Live counts in the share description, so the preview reflects reality
    # rather than a number that quietly goes stale.
    share_desc = (
        f"{sum(1 for d in rows if d['relevant'])} regulatory updates affecting "
        f"community banks and fintechs, "
        f"tracked across 14 federal agencies. Plain-English summaries, comment "
        f"deadlines and effective dates. Updated daily."
    )

    coverage_html = coverage_panel(store)
    regref_html = regref_panel()

    kpi_html = "".join(
        f'<div class="kpi"><div class="l">{lbl}</div><div class="v">{val}</div>'
        f'<div class="n {cls}">{note}</div></div>'
        for lbl, val, note, cls in kpis(rows, today)
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Regulatory update tracker — community banks &amp; fintechs</title>
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
<meta property="og:title" content="Regulatory update tracker — community banks &amp; fintechs">
<meta property="og:description" content="{share_desc}">
<meta property="og:url" content="{SITE_URL}">
<meta property="og:image" content="{SITE_URL}og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Regulatory update tracker for community banks and fintechs">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Regulatory update tracker — community banks &amp; fintechs">
<meta name="twitter:description" content="{share_desc}">
<meta name="twitter:image" content="{SITE_URL}og-image.png">
<style>{CSS}</style></head>
<body data-today="{today}"><div class="wrap">

<header>
  <div class="t">
    <h1>Regulatory update tracker</h1>
    <p class="sub">Community banks &amp; fintechs &middot; last updated
      {datetime.now(timezone.utc).strftime('%B %-d, %Y %H:%M UTC') if os.name != 'nt'
       else datetime.now(timezone.utc).strftime('%B %d, %Y %H:%M UTC')}</p>
    <p class="bmk" id="bmk">
      <span>Press <kbd id="bmkkey">Ctrl</kbd> + <kbd>D</kbd> to bookmark this page</span>
      <button id="bmkx" type="button" aria-label="Dismiss bookmark tip"
              title="Dismiss">&times;</button>
    </p>
  </div>
  <button id="export">Export CSV</button>
</header>

<div class="notice">
  <strong>Read this first.</strong> The summaries are based on agency listings.
  They are a starting point for triage, not legal or
  compliance advice, and they can be wrong or incomplete. Always open the source
  document before acting on anything here. Deadlines shown are structured fields
  taken from matched Federal Register records; items without a match show none,
  which does not mean none exists.
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
      <button id="viewRelevant" aria-pressed="true">Relevant only</button>
      <button id="viewAll" aria-pressed="false">Everything</button>
    </div>
    <span class="count" id="viewnote"></span>
  </div>
  <div class="pillgroup">
    <div class="grouplabel">Source<small>who published it</small></div>
    {source_pills}
  </div>
  <div class="pillgroup">
    <div class="grouplabel">Topic<small>what it's about</small></div>
    {topic_pills}
  </div>
</details>

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
    <div class="pitch">I built this to keep track of federal regulatory activity
      affecting community banks and fintechs. If your institution is tracking this
      manually — or wants monitoring shaped around its own risk profile — I'm happy
      to talk it through.</div>
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
