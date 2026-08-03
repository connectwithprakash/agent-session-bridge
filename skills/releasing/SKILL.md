---
name: session-bridge-releasing
description: Cut, verify, or troubleshoot a session-bridge release. Use when asked to release a version, publish to PyPI, update the Homebrew formula, or when the release-please PR or publish workflow needs attention.
---

# Releasing session-bridge

Releases are automated by release-please from Conventional Commits on `main`.
A release is one action: **merge the open `chore(main): release X.Y.Z` PR.**

## How the pipeline works

```
conventional commits on main
  -> release-please keeps a release PR open (CHANGELOG + pyproject version)
  -> merging it tags vX.Y.Z and creates the GitHub release
  -> the publish job (same workflow, gated on release_created) builds with uv
     and publishes to PyPI via trusted publishing (environment: pypi)
```

- Commit types drive the version: `feat` -> minor, `fix` -> patch,
  `feat!:`/`BREAKING CHANGE` -> major. `docs`/`chore`/`test`/`ci` do not
  trigger a release.
- **Never hand-edit `CHANGELOG.md` or the `version` in `pyproject.toml`** —
  release-please owns both; manual edits cause conflicting release PRs.

## Cutting a release

1. Confirm CI is green on `main` and the release PR's changelog reads sanely.
2. Merge the release PR (squash). Watch `gh run list --workflow=release` —
   the chain runs tag -> GitHub release -> PyPI publish -> Homebrew formula
   bump (the `bump-tap` job pushes to homebrew-tap over a deploy key).
3. Verify: `curl -s https://pypi.org/pypi/agent-session-bridge/<version>/json | jq .info.version`
   (the unversioned JSON endpoint can serve a ~15-minute CDN cache),
   `uvx agent-session-bridge --version` from a clean shell, and the new
   `session-bridge <version>` commit in homebrew-tap.
4. Pull main afterward and run `uv sync`; commit the lockfile's own version
   churn as a `chore:` (release-please does not manage `uv.lock`).

The formula bump is also manually dispatchable (`gh workflow run bump-tap.yml
-f version=<X.Y.Z>`), e.g. after fixing a failed run. It only rewrites the
main url/sha pair; when a new textual release changes the dependency tree,
regenerate the resource stanzas manually per the Homebrew section below.

## Troubleshooting

- **Publish job fails with an OIDC/trusted-publishing error:** the PyPI
  trusted publisher must exist and every field must match the workflow's
  claims exactly (pypi.org -> Publishing: project `agent-session-bridge`,
  owner `connectwithprakash`, repository `agent-session-bridge`, workflow
  `release.yml`, environment `pypi`). The failed job's log prints the actual
  claims GitHub sent — trust those over memory. Fix, then re-run just the
  failed job.
- **release-please fails to create the PR:** the repo setting "Allow GitHub
  Actions to create and approve pull requests" must be enabled
  (`gh api -X PUT repos/<repo>/actions/permissions/workflow -F can_approve_pull_request_reviews=true`).
- **A release PR is always open, sometimes docs-only:** release-please keeps
  a rolling release PR that accumulates commits (docs included, as a patch
  proposal). Leaving it unmerged is the steady state; merge it only when it
  contains changes users should get. Never close it, it will recreate.
- **Branch protection:** main has a ruleset blocking force-pushes and
  deletion only. Do NOT add required status checks or required PRs without
  planning around two facts: checks run after direct pushes (so requiring
  them blocks the direct-push workflow), and release-please's PRs never
  receive checks (default-token events don't trigger workflows), making the
  release PR unmergeable unless the action gets a PAT or a bypass.
- **Version jumps higher than expected after deleting a tag:** release-please
  also reads its own merged `chore(main): release X.Y.Z` commits in history,
  so deleting a release/tag does not roll the version back. Accept the bump;
  do not fight it by hand-editing versions.
- **Scripted merges race release-please:** after pushing a release-triggering
  commit, the release PR only appears once that push's release workflow run
  completes (~1 min). A script that runs `gh pr list` immediately finds
  nothing, silently skips the merge, and downstream chain checks print empty
  conclusions — which reads like a failed release but means the script ran
  too early. Poll until the `chore(main): release X.Y.Z` PR exists before
  merging.
- **`brew upgrade` says already up to date after the tap bumped:** brew reads
  the local tapped clone, which does not auto-pull. Run `brew update` (or
  `git -C "$(brew --repository connectwithprakash/tap)" pull`) first, then
  upgrade.

## Homebrew formula (connectwithprakash/homebrew-tap)

The formula builds from the PyPI sdist and bundles the `tui` extra so brew
users get the full experience.

1. In the tap repo: update `url`/`sha256` to the new sdist
   (`https://pypi.org/pypi/agent-session-bridge/json` lists them under `urls`).
2. Regenerate dependency resources: `brew update-python-resources session-bridge`
   (covers textual and its dependencies).
3. Verify locally before pushing: `brew install --build-from-source ./Formula/session-bridge.rb`
   then `session-bridge --version` and `session-bridge --help`.
4. Commit to the tap with the version in the message.
