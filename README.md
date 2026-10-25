# refspec-lens

[![CI](https://github.com/KanadeK/refspec-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/KanadeK/refspec-lens/actions/workflows/ci.yml)

Explain what a set of Git **fetch refspecs** maps, excludes and exposes to pruning,
using saved ref snapshots. Review a configuration change offline, including negative
rules, tag destinations and overlapping mappings. No Git command, network access or
repository mutation is performed by the CLI.

Python 3.11+, no runtime dependencies. Git is needed only to capture real snapshots
and run the integration tests. [中文说明](README.zh-CN.md)

## Install

```sh
git clone https://github.com/KanadeK/refspec-lens.git
cd refspec-lens
python -m venv .venv
```

Activate `.venv` (`source .venv/bin/activate` on macOS/Linux or
`.venv\Scripts\Activate.ps1` in PowerShell), then:

```sh
python -m pip install .
python examples/demo.py
```

The demo uses explicitly synthetic snapshots. It verifies that `main` maps,
`private/demo` is excluded and a retired local ref is exposed to pruning. Real-Git
integration tests separately compare actual fetch and prune results. Wheels are
available in [Releases](https://github.com/KanadeK/refspec-lens/releases); there is
no PyPI publication.

## Capture and inspect a real configuration

Run these commands in the repository whose fetch settings you are reviewing:

```sh
git ls-remote --refs origin > remote.txt
git for-each-ref --format='%(if)%(symref)%(then)%(else)%(objectname) %(refname)%(end)' > local.txt
git config --get-all remote.origin.fetch
```

The local command excludes symbolic refs such as `refs/remotes/origin/HEAD`, because
plain two-column snapshots cannot represent their targets. In Windows PowerShell
5, replace `> file.txt` with `| Set-Content -Encoding utf8 file.txt` to avoid UTF-16.
UTF-8 with or without BOM and LF/CRLF record endings are accepted.

Pass the complete set of explicit fetch rules, each in quotes:

```sh
refspec-lens --remote remote.txt --local local.txt --refspec '+refs/heads/*:refs/remotes/origin/*' --refspec '^refs/heads/private/*' --prune --json
```

| Output field | Meaning |
|---|---|
| `sources` | Each advertised ref, matched rule numbers, exclusions and destinations |
| `mappings` | Source/destination pairs, object IDs, matching and force-rule numbers |
| `conflicts` | Multiple sources sharing a destination, or mapped file/directory conflicts |
| `local_scope` | Inverse mapping for each local ref: advertised, excluded, unadvertised or outside scope |
| `prune_candidates` | Covered local destinations with no eligible source in the supplied advertisement |
| `missing_exact_rules` | Exact positive sources absent from the advertisement |

`mappings[].state` is `new`, `same` or `different` compared with the local snapshot.
Without `--local`, all mappings are `new` relative to an empty supplied inventory;
`local_snapshot_supplied` is false. `force_rules` preserves syntax/provenance; it
does not claim Git will allow the update.

Tag pruning deserves attention: supplying `refs/tags/*:refs/tags/*` puts local tags
in scope, including tags created locally or obtained from a different remote. The
report names those candidates for review. It never removes them.

Exit **0** means no mapping conflict or missing exact source was found. Exit **1**
means one of those findings exists, or `--prune` was requested and pruning exposure
exists. Exit **2** means invalid/unsupported input or a resource failure. `--prune`
requires `--local`. Runtime JSON errors have `schema_version: 1` and `error`;
argparse usage errors use stderr.

## Exact scope

- Supports fully qualified `refs/...:refs/...`, optional `+`, one matching wildcard
  per side, and `^refs/...` negative rules with zero or one wildcard. A wildcard
  may match slashes. Duplicate rules retain their provenance without duplicating
  source/destination rows. SHA-1 and SHA-256 snapshots are supported, but cannot mix.
- Rejects short names, raw object IDs as sources, source-only rules, empty
  destinations, `tag NAME` shorthand, symbolic advertisements and peeled tag
  lines. Expand shorthand yourself and capture with `ls-remote --refs`.
- Models only explicit rules. It does not infer auto-followed tags, `--prune-tags`,
  command-line override semantics, mirror settings, remote groups or server-hidden
  refs. Supply rules representing the exact scenario you want to inspect.
- Prune candidates assume complete, contemporaneous direct-ref snapshots. They are
  **exposure evidence, not an execution plan**. Git version, symbolic refs, checked-out
  branches, permissions, missing objects or failed fetches can change actual results.
  Verify operational changes with `git fetch --dry-run --prune` in the live context.
- No ancestry or object-type data is read, so fast-forward eligibility and tag update
  acceptance cannot be inferred. Existing local prefix blockers and filesystem case
  collisions are not modeled; `conflicts` compares the mapped destinations only.
- Defaults: 16 MiB per snapshot, 100,000 refs per snapshot, at most 128 rules and
  200,000 total rule matches across remote and local inventories. `--max-bytes` and
  `--max-refs` can change the first two bounds. Reports can be large.
- Snapshots/reports contain ref names and object IDs. Keep them private when needed.

Uninstall with `python -m pip uninstall refspec-lens`; delete your venv, checkout
and captured snapshot files when no longer needed. No cache or service is created.

## Why an offline explainer

Native [`git fetch`](https://git-scm.com/docs/git-fetch) supplies the authoritative
mapping and pruning behavior. `git fetch --dry-run` and `git remote prune --dry-run`
are preferable for live operation checks. This tool makes saved inputs reviewable
and gives reasons for exclusions and overlaps. A historical
[lazygit negative-refspec issue](https://github.com/jesseduffield/lazygit/issues/1967)
illustrates real use of this configuration; it has been fixed upstream.

The implementation is original, MIT-licensed and checked against native Git in
temporary local repositories. See [CONTRIBUTING](CONTRIBUTING.md) and [SECURITY](SECURITY.md).
