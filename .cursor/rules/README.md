# Cursor project rules

Project-scoped Cursor rules live in this directory as `.mdc` files. They are versioned in git so every clone and contributor gets the same agent guidance.

## Rules

| File | Always apply | Purpose |
|------|--------------|---------|
| `language-english.mdc` | yes | Code, comments, docs, and commit messages in English |
| `documentation.mdc` | yes | Keep README and rule docs in sync with changes |
| `git-branching.mdc` | yes | Work on dedicated branches; do not develop on `main` |
| `git-commit-push.mdc` | yes | Commit and push when a feature/fix is done or before switching topics |

## Format

Each rule uses YAML frontmatter:

```markdown
---
description: Short summary shown in the rule picker
alwaysApply: true
---

# Title

Rule body...
```

For file-scoped rules, set `alwaysApply: false` and add a `globs` pattern (for example `**/*.ts`).

## Adding a rule

1. Create a branch (not `main`)
2. Add a focused `.mdc` file in this folder
3. Update this README table
4. Mention notable conventions in the root `README.md` if needed
5. Commit and push

Keep each rule concise, actionable, and preferably under ~50 lines.
