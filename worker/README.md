# regwatch-ask — the backend for "Ask"

> **The feature is parked and this Worker is DELETED from Cloudflare.**
> `ASK_ENABLED = False` in `dashboard.py`, so the dashboard renders no question
> box and nothing calls this endpoint. The deployment was taken down on
> 2026-07-21 rather than left idle: it was publicly callable by anyone who knew
> the URL — the Origin check only constrains browsers, since a plain client sets
> whatever headers it likes — and that becomes a billable open endpoint the
> moment a paid key is added.
>
> **To bring it back**, from this folder:
>
> ```bash
> npx wrangler deploy
> npx wrangler secret put GROQ_API_KEY         # answerer (at least one required)
> npx wrangler secret put GEMINI_API_KEY       # answerer
> npx wrangler secret put OPENROUTER_API_KEY   # answerer AND all free reconcilers
> npx wrangler secret put DEEPSEEK_API_KEY     # preferred reconciler, PAID, optional
> ```
>
> Those were the live secret names at deletion, minus `CEREBRAS_API_KEY`, which
> was set but useless — see the note on Cerebras below. The keys themselves are
> gone with the Worker and must be reissued from each provider's console.
> The URL is derived from the account and worker name in `wrangler.toml`, so a
> redeploy should return the same endpoint already hardcoded as `ASK_ENDPOINT`
> in `dashboard.py` — verify it matches before flipping `ASK_ENABLED`.
>
> The rest of this file describes how it works when switched back on.

A Cloudflare Worker. It exists for one reason: the published dashboard is a
static file on GitHub Pages and **cannot hold an API key**. Anything in that page
is readable by anyone. So the browser does the searching, and this Worker does
the one step that must stay server-side — calling the model with the key.

```
visitor's browser                    this Worker                3 answerers
  searches the tracked        ─────▶  adds the keys,     ─────▶  (in parallel)
  updates (BM25, free)                fans out                       │
                                            │                        ▼
                                            └──────────────────▶ 1 reconciler
                                                                 writes the
                                                                 single answer
```

## Scope: updates only

The passages sent here are RegWatch's **tracked updates**, not CFR text.
`ASK_INCLUDE_REGULATIONS` in `dashboard.py` is `False` because a free answerer
invented the subsections `12 CFR 1002.9(a)(2)(iii)`–`(vi)`, which do not exist in
the source it was handed. No regulation text in, no subsections to fabricate. The
prompts in `worker.js` now also forbid citing or subdividing any CFR reference
not present verbatim in the sources.

## The two roles

There is no model picker. Every question goes to all three **answerers** at once,
each working from the same retrieved passages. A separate **reconciler** then
reads only those three answers — not the sources — and writes the one the visitor
sees, stating where the three disagreed instead of picking a winner.

The reconciler is deliberately a model that did not answer. Asked to judge a set
including its own, a model tends to prefer its own, which would quietly turn the
whole thing into "whichever answerer went first wins".

| Role | Provider | Model | Secret |
|---|---|---|---|
| answerer | Groq | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| answerer | Gemini | `gemini-flash-latest` | `GEMINI_API_KEY` |
| answerer | OpenRouter | `openai/gpt-oss-20b:free` | `OPENROUTER_API_KEY` |
| reconciler | OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | `OPENROUTER_API_KEY` |
| ↳ fallback | OpenRouter | `nemotron-3-super-120b`, then `gemma-4-26b` | `OPENROUTER_API_KEY` |

The reconcilers share OpenRouter's key with an answerer but run different
weights, so none is grading its own work. The order is measured, not chosen —
in a bake-off on the same answers, both Nemotrons quarantined a fabricated CFR
citation and flagged it for verification while Gemma restated it as fact. See
`RECONCILERS` in `worker.js` for the alternatives tried and why each failed.

Everything degrades rather than breaking: one answerer left → nothing to
reconcile, its answer is returned as-is; reconciler fails → the individual
answers are shown; all fail → each provider's reason is named.

## Deploy (about five minutes)

You need a free Cloudflare account. Run these from this `worker/` folder.

```bash
npx wrangler login                          # opens a browser to authorise
npx wrangler secret put GROQ_API_KEY        # paste your gsk_... key when prompted
npx wrangler secret put GEMINI_API_KEY      # optional
npx wrangler secret put OPENROUTER_API_KEY  # optional, but also the reconciler
npx wrangler deploy
```

Paste keys at the interactive prompt. Piping them in appends a newline, which
makes the auth header `Bearer key\n` and every call 401s.

A deploy takes a few seconds to propagate — a test fired immediately after
`wrangler deploy` can still hit the previous version. If behaviour looks stale,
wait and retry before debugging the code.

`wrangler deploy` prints the live URL, e.g.

```
https://regwatch-ask.YOUR-SUBDOMAIN.workers.dev
```

**Send that URL to Claude (or paste it into `ASK_ENDPOINT` in `dashboard.py`),
then rebuild and push.** Until that is set, the ask box is not wired up.

## What it costs, honestly

- **Cloudflare Workers** free tier: 100,000 requests/day. A public compliance
  tracker will not come close.
- **The model providers** are the real limit, and note that **one question is now
  four provider calls, not one** — three answers plus the reconcile. Free quota
  is reached roughly four times sooner than under the old single-model design,
  and OpenRouter carries two of the four. When quota runs out the box says so
  plainly and the rest of the dashboard is unaffected. With free keys the
  downside is the feature pausing, **not a bill**.
- **Latency is the visible cost.** Measured 2026-07-21 on real questions: 37s,
  49s and 121s end to end. The three answers run in parallel, but the reconcile
  cannot start until the slowest of them finishes, so the total is
  *slowest answerer + reconciler*. Free tiers are not fast and the variance is
  wide.

**Add the KV rate limit before this is public**, not just before moving to a paid
key — at four calls a question, a handful of visitors can exhaust a day's free
quota between them.

## Rotating or revoking

```bash
npx wrangler secret put GROQ_API_KEY   # overwrite with a new key
npx wrangler secret list               # names are whitespace-sensitive; check here
npx wrangler delete                    # remove the Worker entirely
```

Deleting the Worker makes the ask box show "unavailable"; nothing else on the
dashboard is affected.
