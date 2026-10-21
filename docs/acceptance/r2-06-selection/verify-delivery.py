"""Reuse the v5 read-only delivery assertions for this zero-query v6 batch."""

from pathlib import Path

root = Path(__file__).resolve().parents[3]
source = root / "docs/acceptance/r2-06-zero-paid/final-audit.py"
code = source.read_text()
replacements = {
    'read("ledger-audit")': 'json.loads((ROOT / "docs/acceptance/r2-06-zero-paid/ledger-audit.json").read_text())',
    'validation["regression_passed"] == 1112': 'validation["regression_passed"] == 1164',
    'lookups = read("provider-receipts-v2")["generation"]\nassert len(lookups) == 12 and all(row.get("http_status") == 404 for row in lookups)':
        'assert "provider" not in read("predeploy-production")\nassert validation["provider_queries"] == 0',
    '"paid_generation": 0,': '"provider_queries": 0,\n    "offline_original_cases": 17,\n    "paid_generation": 0,',
}
for old, new in replacements.items():
    assert code.count(old) == 1, old
    code = code.replace(old, new)
# __file__ intentionally selects this batch's output; the retained original
# verifier, ledgers and all historical evidence are never edited.
exec(compile(code, str(source), "exec"))
