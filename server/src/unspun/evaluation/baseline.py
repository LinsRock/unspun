"""Frozen pre-grounding prompts from commit 7f086cd for evaluation only."""

SUMMARY_SYSTEM = (
    "You summarize news articles for a personal intelligence reader. R"
    'espond with a JSON object: {"title_zh": "...", "summary_zh": "...'
    '"}. title_zh is the story title in Simplified Chinese (translate '
    "when the original is not Chinese). summary_zh is 2-4 factual sent"
    "ences in Simplified Chinese covering what happened, who is involv"
    "ed, and concrete numbers from the text; no opinions, no hype."
)

VIEWPOINT_SYSTEM = (
    "You compare how different news sources report the same event. Eac"
    "h input article is one source's coverage, labeled with its articl"
    'e_id. Respond with a JSON object: {"claims": [{"article_id": n, "'
    'claim": "..."}], "disagreements": [{"point": "...", "claim_indexe'
    's": [i, ...]}]}.\n- claims: one entry per article, in any order. c'
    "laim is ONE sentence in Simplified Chinese stating that source's "
    "stance or central assertion — what THIS source emphasizes or clai"
    "ms, not a neutral summary of the event. Use only the provided art"
    "icle_id values.\n- disagreements: points where sources genuinely d"
    "iffer (facts, framing, attribution of blame, projected impact). p"
    "oint is 1-2 sentences in Simplified Chinese; claim_indexes are 0-"
    "based indexes into your claims list, at least two per point. An e"
    "mpty list is correct when sources agree."
)
