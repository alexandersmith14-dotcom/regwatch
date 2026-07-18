"""Federal Reserve regulation letter reference (Reg A through YY).

A lookup aid that sits beside the tracker: when an item says "Regulation B",
this says what that is and where it now lives in the CFR.

Post-Dodd-Frank, many consumer regs moved to the CFPB — same letter, new CFR
home — so both are recorded. Entries flagged UNVERIFIED come from a source that
itself said to confirm them against the Fed's official listing; they are marked
rather than quietly presented as fact.

Structure: (letter, subject, cfr_home, note)
"""

CONSUMER = [
    ("B",  "Equal Credit Opportunity Act (fair lending)", "CFPB 1002", ""),
    ("C",  "Home Mortgage Disclosure Act (HMDA)", "CFPB 1003", ""),
    ("E",  "Electronic Fund Transfer Act", "CFPB 1005", ""),
    ("F",  "Fair Debt Collection Practices Act", "CFPB 1006", ""),
    ("G",  "SAFE Act — MLO registration for bank employees", "CFPB 1007", ""),
    ("M",  "Consumer Leasing Act", "CFPB 1013", ""),
    ("P",  "GLBA privacy", "CFPB 1016", ""),
    ("V",  "Fair Credit Reporting Act", "CFPB 1022", ""),
    ("X",  "RESPA", "CFPB 1024", ""),
    ("Z",  "Truth in Lending", "CFPB 1026", ""),
    ("BB", "Community Reinvestment Act", "Fed 228", ""),
    ("CC", "Funds availability / Check 21", "Fed 229", ""),
    ("DD", "Truth in Savings", "CFPB 1030", ""),
    ("FF", "Use of medical information in credit", "Fed 232", ""),
]

PRUDENTIAL = [
    ("A",  "Discount window lending", "12 CFR 201", ""),
    ("D",  "Reserve requirements", "12 CFR 204", ""),
    ("H",  "State member bank membership", "12 CFR 208", ""),
    ("I",  "Reserve Bank capital stock", "12 CFR 209", ""),
    ("J",  "Check collection and Fedwire", "12 CFR 210", ""),
    ("K",  "International banking operations", "12 CFR 211", ""),
    ("L",  "Management official interlocks", "12 CFR 212", ""),
    ("N",  "Relations with foreign banks", "12 CFR 214", ""),
    ("O",  "Insider lending — officers, directors, principal shareholders", "12 CFR 215", ""),
    ("Q",  "Regulatory capital (Basel III minimums)", "12 CFR 217", ""),
    ("R",  "Bank broker exceptions (GLBA)", "12 CFR 218", ""),
    ("S",  "Reimbursement for producing financial records", "12 CFR 219", ""),
    ("T",  "Margin credit — brokers", "12 CFR 220", ""),
    ("U",  "Margin credit — banks", "12 CFR 221", ""),
    ("W",  "Affiliate transactions, sections 23A and 23B", "12 CFR 223", ""),
    ("Y",  "Bank holding companies and change in control", "12 CFR 225", ""),
    ("EE", "Netting eligibility", "12 CFR 231", ""),
    ("GG", "Unlawful internet gambling (UIGEA)", "12 CFR 233", ""),
]

POST_DODD_FRANK = [
    ("HH", "Designated financial market utilities", "12 CFR 234", ""),
    ("II", "Debit interchange and routing (Durbin)", "12 CFR 235", ""),
    ("KK", "Federal assistance to swaps entities (swaps pushout)", "12 CFR 237", ""),
    ("LL", "Savings and loan holding companies", "12 CFR 238", ""),
    ("MM", "Mutual holding companies", "12 CFR 239", ""),
    ("NN", "Retail forex transactions", "12 CFR 240", ""),
    ("OO", "Securities holding companies", "12 CFR 241", ""),
    ("PP", "Dodd-Frank Title I definitions", "12 CFR 242", ""),
    ("QQ", "Resolution plans (living wills)", "12 CFR 243", ""),
    ("RR", "Credit risk retention", "12 CFR 244", ""),
    ("TT", "Supervision and regulation assessment fees", "12 CFR 246", ""),
    ("VV", "Volcker Rule", "12 CFR 248", ""),
    ("WW", "Liquidity Coverage Ratio", "12 CFR 249", ""),
    ("XX", "Concentration limits", "12 CFR 251", ""),
    ("YY", "Enhanced prudential standards", "12 CFR 252", ""),
]

# Removed rather than published: AA (repealed) and JJ, SS, UU, ZZ (reserved,
# renumbered or never finalised). A reference table on a public page under a
# named practitioner's credentials should carry only entries the author has
# verified. An absent row sends the reader to the primary source; an unverified
# or obsolete row sends them somewhere worse.

GROUPS = [
    ("Consumer compliance",
     "Fair lending, deposits and consumer credit. Many moved to the CFPB after "
     "Dodd-Frank — same letter, new CFR home.",
     CONSUMER),
    ("Safety, soundness and structural",
     "Retained by the Federal Reserve.",
     PRUDENTIAL),
    ("Post-Dodd-Frank prudential",
     "Mostly large-bank and systemic-risk rules.",
     POST_DODD_FRANK),
]

# Deliberately empty. The table is a plain Reg / Subject / CFR lookup; commentary
# and interpretation belong in the practitioner's own words, not baked into a
# generated reference.
FOOTNOTES = []


def rows():
    """Flat list of (group, letter, subject, cfr, note) for rendering and search."""
    out = []
    for group, _desc, entries in GROUPS:
        for letter, subject, cfr, note in entries:
            out.append(
                {"group": group, "letter": letter, "subject": subject,
                 "cfr": cfr, "note": note}
            )
    return out
