"""One-off CL-00 repository/local metadata inventory. Never deletes or starts apps.

Run at the inventory worktree root, passing a JSON file from:
gh pr list --state merged --limit 200 --json number,url,headRefName,headRefOid,mergeCommit
File sizes are logical bytes; du_bytes are allocated blocks (symlinks not followed).
No environment values, raw documents, database payloads or process env are exported.
"""

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

root = Path.cwd()
outdir = root / "docs/acceptance/cl-00"


def run(*args, cwd=root):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return p.stdout.strip()


def dump(name, data):
    (outdir / name).write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n")


def allocated(path):
    value = run("du", "-sk", str(path)).split()
    return int(value[0]) * 1024 if value else None


tracked = run("git", "ls-files").splitlines()
texts = {}
for name in tracked:
    p = root / name
    with suppress(UnicodeDecodeError, OSError):
        texts[name] = p.read_text()
inbound = {}
links = []
for source, body in texts.items():
    for raw in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", body):
        target = raw.split("#")[0].split("?")[0].strip("<>")
        if not target or urlsplit(target).scheme:
            continue
        path = ((root / source).parent / unquote(target)).resolve()
        if path.is_relative_to(root):
            key = str(path.relative_to(root))
            inbound.setdefault(key, set()).add(source)
            links.append({"source": source, "target": key, "exists": path.exists()})
imports = []
for source, body in texts.items():
    if not source.endswith(".py"):
        continue
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.append(
                    {
                        "source": source,
                        "line": node.lineno,
                        "module": node.module,
                        "name": alias.name,
                    }
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {"source": source, "line": node.lineno, "module": alias.name, "name": ""}
                )
code = []
for name in tracked:
    if not (name.startswith("server/src/unspun/pipeline/") and name.endswith(".py")):
        continue
    module = name.removeprefix("server/src/").removesuffix(".py").replace("/", ".")
    uses = [r for r in imports if r["module"] == module or r["module"] + "." + r["name"] == module]
    code.append(
        {
            "path": name,
            "bytes": (root / name).stat().st_size,
            "imports": uses,
            "document_links": sorted(inbound.get(name, [])),
        }
    )
dump(
    "code-references.json",
    {
        "base": run("git", "rev-parse", "HEAD"),
        "method": (
            "AST imports of every tracked Python file plus resolved Markdown links; "
            "rg/manual review supplements dynamic/string entry points"
        ),
        "pipeline": code,
        "entry_strings": [
            {"path": n, "line": i, "text": line.strip()}
            for n, body in texts.items()
            for i, line in enumerate(body.splitlines(), 1)
            if ("pipeline.main" in line or "worker=0" in line)
        ],
    },
)
docs = []
hashes = {}
for name in tracked:
    if not name.startswith("docs/"):
        continue
    p = root / name
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    hashes.setdefault(digest, []).append(name)
    docs.append(
        {
            "path": name,
            "bytes": p.stat().st_size,
            "sha256": digest,
            "markdown_inbound": sorted(inbound.get(name, [])),
        }
    )
dump(
    "documents.json",
    {
        "base": run("git", "rev-parse", "HEAD"),
        "files": docs,
        "exact_duplicate_groups": [v for v in hashes.values() if len(v) > 1],
        "markdown_links": links,
        "limits": (
            "Inbound lists resolve literal Markdown links only. No inbound link is not proof "
            "of disuse; JSON freezes, code strings, history and unique content "
            "were reviewed separately."
        ),
    },
)

prs = json.loads(Path(sys.argv[1]).read_text())
bybranch = {}
for pr in prs:
    bybranch.setdefault(pr["headRefName"], []).append(pr)
worktrees = []
for block in run("git", "worktree", "list", "--porcelain").split("\n\n"):
    fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.splitlines())
    path = Path(fields["worktree"])
    branch = fields.get("branch", "").removeprefix("refs/heads/")
    status = run("git", "status", "--porcelain=v1", cwd=path)
    worktrees.append(
        {
            "path": str(path),
            "head": fields["HEAD"],
            "branch": branch,
            "status": status.splitlines(),
            "du_bytes": allocated(path),
            "nonancestor_commits": int(
                run("git", "rev-list", "--count", "origin/main..HEAD", cwd=path)
            ),
            "merged_prs": bybranch.get(branch, []),
        }
    )
branches = []
for line in run(
    "git",
    "for-each-ref",
    "--format=%(refname:short) %(objectname) %(upstream:short)",
    "refs/heads/",
).splitlines():
    parts = line.split()
    name, head = parts[:2]
    branches.append(
        {
            "name": name,
            "head": head,
            "upstream": parts[2:] or None,
            "nonancestor_commits": int(run("git", "rev-list", "--count", "origin/main.." + name)),
            "merged_prs": bybranch.get(name, []),
        }
    )

cwd_records = []
pid, command = None, None
for line in run("lsof", "-nP", "-d", "cwd", "-Fpcn").splitlines():
    if line.startswith("p"):
        pid = int(line[1:])
    elif line.startswith("c"):
        command = line[1:]
    elif line.startswith("n") and ("/unspun" in line or "cl00" in line):
        cwd_records.append({"pid": pid, "command": command, "cwd": line[1:]})
listeners = []
for line in run("lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn").splitlines():
    if line.startswith("p"):
        pid = int(line[1:])
    elif line.startswith("c"):
        command = line[1:]
    elif line.startswith("n") and pid in {r["pid"] for r in cwd_records}:
        listeners.append({"pid": pid, "command": command, "listener": line[1:]})

links = []
artifacts = []
excluded = {
    "node_modules",
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    ".vite",
}
for w in worktrees:
    for base, dirs, files in os.walk(w["path"], followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            if path.is_symlink():
                links.append(
                    {
                        "path": str(path),
                        "target": os.readlink(path),
                        "resolved": str(path.resolve()),
                        "exists": path.exists(),
                    }
                )
            if name in excluded and name != ".git":
                artifacts.append(
                    {
                        "path": str(path),
                        "kind": name,
                        "symlink": path.is_symlink(),
                        "du_bytes": allocated(path),
                    }
                )
        dirs[:] = [d for d in dirs if d not in excluded and not (Path(base) / d).is_symlink()]
main = Path("/Users/li.cong/Documents/personal/unspun")
editable = []
site = main / "server/.venv/lib"
for p in site.glob("python*/site-packages/*"):
    if p.name.endswith(".pth") and "unspun" in p.name:
        editable.append({"path": str(p), "content": p.read_text()})
    if p.is_dir() and "unspun" in p.name and (p / "direct_url.json").exists():
        editable.append(
            {
                "path": str(p / "direct_url.json"),
                "content": json.loads((p / "direct_url.json").read_text()),
            }
        )
temporary = []
for p in sorted(Path("/private/tmp").glob("*unspun*")):
    temporary.append({"path": str(p), "du_bytes": allocated(p), "is_directory": p.is_dir()})
caches = []
for p in (
    Path.home() / ".cache/uv",
    Path.home() / "Library/Caches/uv",
    Path.home() / "Library/pnpm/store",
    Path.home() / "Library/Caches/pnpm",
):
    if p.exists():
        caches.append(
            {
                "path": str(p),
                "du_bytes": allocated(p),
                "ownership": "shared across projects; not attributable wholly to unspun",
            }
        )
dump(
    "local.json",
    {
        "captured_at": datetime.now(UTC).isoformat(),
        "worktrees": worktrees,
        "branches": branches,
        "process_cwds": cwd_records,
        "listeners": listeners,
        "symlinks": links,
        "artifacts": artifacts,
        "editable": editable,
        "temporary": temporary,
        "shared_caches": caches,
        "limits": (
            "Nonancestor commits may be squash-merged; matched PRs are evidence, not proof all "
            "later changes were integrated. Open/suspended AI sessions cannot be exhaustively "
            "identified by OS cwd. Shared cache and du sizes are not additive reclaim estimates."
        ),
    },
)
