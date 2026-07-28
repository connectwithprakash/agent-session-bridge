<!-- Title must be a Conventional Commit (feat:/fix:/docs:/refactor:/test:/chore:).
     It becomes the squash commit, and release-please versions the next release
     from it: feat -> minor, fix -> patch, feat!: -> major, docs/chore/test -> no release. -->

## What

<!-- One or two sentences: the concrete outcome of this PR. -->

## Why

<!-- Motivation: what breaks or is missing without this. Link the issue if one exists. -->

## Testing

<!-- Command AND observed result, e.g. `uv run --extra dev --extra tui pytest` -> 299 passed.
     The suite must pass both with and without the tui extra (CI enforces both). -->

- [ ] `uv run --extra dev pytest`
- [ ] `uv run --extra dev --extra tui pytest`

## Compatibility

<!-- Only if this touches readers/, writers/, or registrars: does the change affect
     what the README's supported-versions matrix claims? If a harness schema moved,
     follow skills/harness-recertification/SKILL.md and update the matrix row. -->
