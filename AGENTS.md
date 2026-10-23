# Repository instructions

Read `CLAUDE.md` for engineering rules and `docs/README.md` for document routing.
Then read only the task section, specifications, and decisions relevant to the
request. Do not load all of `docs/` or follow every historical evidence link.

`docs/.ignore` excludes historical material from ordinary ripgrep searches.
Use an explicit file path or `rg --no-ignore <pattern> <directory>` when evidence
or historical context is needed. These exclusions do not change Git tracking.
