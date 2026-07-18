import json
import os
import sys

import anthropic
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-ant-"):
    sys.exit("No valid ANTHROPIC_API_KEY found in .env — check the file.")

MODEL = "claude-opus-4-8"

# Who we are. The model scores relevance against this.
PROFILE = """We monitor regulation affecting US community banks (under ~$10B assets)
and fintechs, including BaaS/sponsor-bank arrangements, prepaid and FBO accounts,
consumer lending and credit risk, BSA/AML, and internal audit obligations."""

# What counts as genuinely fintech-specific, as opposed to general bank regulation
# that a fintech also happens to be subject to. Without this distinction the model
# labelled almost everything "fintech" because the word appears in the profile.
FINTECH_SCOPE = """Fintech-specific means the item is materially about at least one of:
BaaS or sponsor-bank arrangements; payments, money transmission or MSB rules;
prepaid, stored value or FBO/for-benefit-of accounts; stablecoins, digital assets,
crypto or virtual currency; open banking or data access (e.g. Dodd-Frank 1033);
marketplace, embedded or non-bank lending; neobanks and bank-fintech partnerships;
or a fintech charter or licensing question.

It is NOT fintech-specific merely because a fintech would also have to comply.
Routine safety-and-soundness guidance, bank failures, general fair-lending rules,
call-report changes and personnel announcements are not fintech items even though
fintechs operate in the same system."""

SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {
            "type": "boolean",
            "description": "True if this matters to community banks or fintechs per the profile.",
        },
        "fintech_specific": {
            "type": "boolean",
            "description": "True ONLY if the item is materially about a fintech topic "
                           "per the fintech scope given. False for general bank "
                           "regulation that fintechs merely also comply with.",
        },
        "update_type": {
            "type": "string",
            "enum": [
                "Final Rule",
                "Proposed Rule",
                "Guidance",
                "Enforcement Action",
                "Notice",
                "FAQ Update",
                "Other",
            ],
        },
        "urgency": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "plain_english": {
            "type": "string",
            "description": "2-3 sentences: what changed, who it hits, and the so-what.",
        },
        "effective_or_comment_date": {
            "type": "string",
            "description": "Effective date or comment deadline if stated in the source, else 'Not stated'.",
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "relevant",
        "fintech_specific",
        "update_type",
        "urgency",
        "plain_english",
        "effective_or_comment_date",
        "tags",
    ],
    "additionalProperties": False,
}

client = anthropic.Anthropic()


# Federal Register items already tell us the document type; pass it through as a hint
# rather than making the model re-derive it from the title.
def build_prompt(u):
    hint = f"\nDocument type (from source): {u['doc_type']}" if u.get("doc_type") else ""
    return f"""You are a regulatory intelligence analyst.

Our focus:
{PROFILE}

{FINTECH_SCOPE}

Analyze this regulatory update.

Agency: {u['agency']}
Title: {u['title']}
Date: {u['date']}{hint}
Summary: {u['summary'] or '(no summary provided)'}

Judge relevance against our focus above. Set relevant=false for items outside it
(agricultural lending, credit-union-only matters we don't touch, routine personnel
or administrative notices). Set fintech_specific per the scope above — be strict,
most bank regulation is not fintech-specific.

Write plain_english for a reader who already knows we cover community banks and
fintechs: say what changed and who it hits. Do not pad it with the phrase
"community banks and fintechs" when the item is simply general bank regulation.

Do not invent dates or requirements that are not in the text you were given."""


def classify(u):
    """Classify a single update. Raises on API or parse failure."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        output_config={
            "format": {"type": "json_schema", "schema": SCHEMA},
            "effort": "low",
        },
        messages=[{"role": "user", "content": build_prompt(u)}],
    )
    if message.stop_reason == "refusal":
        raise RuntimeError("model declined to answer")
    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)


def main(updates):
    results, failures = [], []

    for i, u in enumerate(updates, 1):
        print(f"[{i}/{len(updates)}] {u['agency']}: {u['title'][:55]}...")
        try:
            parsed = classify(u)
            parsed.update(
                {
                    "agency": u["agency"],
                    "title": u["title"],
                    "url": u["url"],
                    "date": u["date"],
                    "source_type": u.get("source_type", ""),
                }
            )
            results.append(parsed)
        except Exception as e:
            failures.append((u["title"][:60], str(e)))
            print(f"    FAILED: {e}")

    with open("classified.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    relevant = [r for r in results if r["relevant"]]
    high = [r for r in relevant if r["urgency"] == "High"]

    print(f"\n{len(results)} classified, {len(relevant)} relevant, {len(high)} high urgency")
    print("Saved to classified.json")

    if failures:
        print(f"\nWARNING: {len(failures)} item(s) failed:")
        for title, err in failures:
            print(f"  - {title}: {err}")


if __name__ == "__main__":
    with open("updates.json", encoding="utf-8") as f:
        all_updates = json.load(f)
    # `python classifier.py 5` classifies only the first 5 (cheap smoke test).
    if len(sys.argv) > 1:
        all_updates = all_updates[: int(sys.argv[1])]
    main(all_updates)
