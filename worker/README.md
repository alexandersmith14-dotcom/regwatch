# regwatch-ask — the backend for "Ask the regulations"

A Cloudflare Worker. It exists for one reason: the published dashboard is a
static file on GitHub Pages and **cannot hold an API key**. Anything in that page
is readable by anyone. So the browser does the searching, and this Worker does
the one step that must stay server-side — calling the model with the key.

```
visitor's browser                      this Worker              Groq
  searches corpus.json + the   ──────▶  adds the API key  ─────▶ answers
  tracked updates (BM25, free)          (a stored secret)
```

## Deploy (about five minutes)

You need a free Cloudflare account. Run these from this `worker/` folder.

```bash
npx wrangler login                    # opens a browser to authorise
npx wrangler secret put GROQ_API_KEY  # paste your gsk_... key when prompted
npx wrangler deploy
```

`wrangler deploy` prints the live URL, e.g.

```
https://regwatch-ask.YOUR-SUBDOMAIN.workers.dev
```

**Send that URL to Claude (or paste it into `ASK_ENDPOINT` in `dashboard.py`),
then rebuild and push.** Until that is set, the ask box is not wired up.

## What it costs, honestly

- **Cloudflare Workers** free tier: 100,000 requests/day. A public compliance
  tracker will not come close.
- **Groq** free tier: the real limit. Heavy public use can exhaust the quota, and
  when it does the Worker returns *"The assistant has hit its usage limit for
  now"* and the rest of the dashboard keeps working normally. With a free key the
  downside is the feature pausing, **not a bill**.

If you ever move to a paid key, add the KV rate limit first.

## Rotating or revoking

```bash
npx wrangler secret put GROQ_API_KEY   # overwrite with a new key
npx wrangler delete                    # remove the Worker entirely
```

Deleting the Worker makes the ask box show "unavailable"; nothing else on the
dashboard is affected.
