# Offline regression

`uv run pytest` includes all 1,383 cases. `legacy_batch` classifies 13 retained
mock regressions; it does not exclude them from the default suite or CI.
`uv run pytest -m legacy_batch` selects those 13 for the preliminary check.

Run them only with a newly created isolation database, an empty real
`UNSPUN_OPENROUTER_API_KEY`, mock model clients and external networking blocked.
Do not use production, retained evaluation or preview databases, or start the
retired worker. The four removed CL-04A entrypoints remain absent.

[CI](../../.github/workflows/ci.yml) builds the dependency-only
[test image](Dockerfile), then moves its fresh Postgres service to a Docker
`--internal` network. Test containers share that service's network namespace,
so `127.0.0.1:5432` reaches only the new database. The repository is mounted read
only, and dependencies are installed before egress is blocked.

The execution order is migration, `check_isolation.py`, the 13 mock cases, then
the default full suite. The preflight verifies an empty real key, an empty
migrated database and failed native IPv4/IPv6 external connections. CI also
verifies that the database has exactly one network and that it is internal.
It restores the job service's original network on exit and preserves failures
as failures. The fixed 40-event ranking check remains a separate required step.
