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
2. Merge the release PR (squash). Watch `gh run list --workflow=release`.
3. Verify publish: `curl -s https://pypi.org/pypi/agent-session-bridge/json | jq .info.version`
   and `uvx session-bridge@latest --version` from a clean shell.
4. Update the Homebrew formula (below) when the release is user-facing.

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
- **No release PR appears:** there are no releasable commits (only
  docs/chore/test since the last tag). That is correct behavior.
- **Version jumps higher than expected after deleting a tag:** release-please
  also reads its own merged `chore(main): release X.Y.Z` commits in history,
  so deleting a release/tag does not roll the version back. Accept the bump;
  do not fight it by hand-editing versions.

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
