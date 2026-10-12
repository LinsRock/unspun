# Grounded content quality evaluation

`quality_cases.json` contains five bounded production-audit excerpts and 25
explicit synthetic controls. They are regression inputs, not a representative
accuracy sample or complete articles. Expected source coverage, forbidden
assertions, relation kinds, and per-article retention must be reviewed together.
Quote matching does not establish semantic entailment.

Run migrations in a separate local `unspun_quality_*` database, then:

```sh
UNSPUN_GROUNDING_BUDGET_24H_USD=10 \
UNSPUN_DATABASE_URL=postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_eval \
uv run python -m unspun.evaluation.run_quality --variant both \
  --budget-usd 0.60 --max-calls 410 --workers 3 \
  --output ../docs/evaluations/quality-results.json
```

The standard environment supplies the OpenRouter key. `--key-source-ssh unspun`
can read an existing worker key directly into memory through an authorized SSH
alias; it never stores the key in files or prints it. Generation inputs remain
transient; every billed call, including retries and failures, is committed in
the isolated usage ledger. Cost caps stop subsequent calls; simultaneous calls
and provider truncation retries can cause a small overshoot.

`--variant baseline` runs frozen prompts from the pre-change main commit;
`--variant candidate` runs the production functions. Temperature is zero for
both comparisons. Baseline claims have no quotes or relation kinds, so failure
of the new evidence schema does not mean zero semantic accuracy. Review actual
summaries, translated titles, claims, and relationships against each input.
Reports include a case-suite version/hash. Source hashes describe files at report-writing
time, rather than immutable copies of loaded Python modules. Reports retain failures; a separate `--case` retry must not replace the first run.

# Explicit event repair

```sh
uv run python -m unspun.pipeline.repair_grounding --event-id 123
uv run python -m unspun.pipeline.repair_grounding --event-id 123 --apply \
  --max-articles 100 --max-calls 250
```

The first command is a read-only dry run and does not require an API key. Apply
rebuilds summaries, embeddings, centroid, representative text, score, and
viewpoint on transient copies. It commits usage after calls, then atomically
writes business data only if source inputs still match the initial fingerprint.
A failure preserves original event data and charged usage. Event membership,
news timestamps, and historical digest snapshots remain intact. The call cap
limits logical requests; provider retries can add billed calls. Apply events one
at a time from a clean session; the CLI executes each ID sequentially.
Production repair follows normal PR deployment rather than manual data edits.

The production default adds at most $0.40 of recorded review spend per rolling
24 hours before it stops subsequent requests; one request or concurrent callers
may slightly exceed that allowance. This cap covers grounding review only.
Budget fallback stores original titles and a visible review-pending status;
it never silently accepts unreviewed generated facts. An explicit repair aborts
on this fallback rather than replacing good data. Evaluation overrides the
rolling allowance only in its isolated database to exercise all cases; its
per-run CLI limits remain active.
