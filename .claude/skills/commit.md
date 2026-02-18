---
name: commit
description: Create commits following the project's commitizen conventional commits convention. Use this skill whenever committing changes.
user_invocable: true
---

# Commitizen Conventional Commits

This project uses commitizen with `cz_conventional_commits`. All commits MUST follow this format. The pre-commit hook (`commitizen check`) will reject non-compliant messages.

## Commit Message Format

```
<type>(<optional scope>): <description>

<optional body>

<optional footer>
```

## Allowed Types

| Type       | When to use                                      |
|------------|--------------------------------------------------|
| `feat`     | New feature                                      |
| `fix`      | Bug fix                                          |
| `docs`     | Documentation only                               |
| `style`    | Formatting, missing semicolons, etc. (no logic)  |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf`     | Performance improvement                          |
| `test`     | Adding or updating tests                         |
| `build`    | Build system or external dependencies            |
| `ci`       | CI configuration                                 |
| `chore`    | Other changes that don't modify src or tests     |
| `revert`   | Reverts a previous commit                        |

## Rules

1. **type** is mandatory and must be one of the types above (lowercase).
2. **scope** is optional, in parentheses: `feat(parser): ...`
3. **description** is mandatory, lowercase start, no period at end, imperative mood.
4. **body** is optional. Separate from description with a blank line. Explain *why*, not *what*.
5. **BREAKING CHANGE**: Put `BREAKING CHANGE: <explanation>` in the footer for breaking changes.
6. Keep the first line (type + scope + description) under 72 characters.

## Workflow

When the user asks to commit:

1. Run `git status` (never use `-uall`), `git diff` (staged + unstaged), and `git log --oneline -5` in parallel.
2. Analyze the changes and determine the appropriate type and optional scope.
3. Draft a concise description in imperative mood (e.g., "add retry logic" not "added retry logic").
4. Add a body only if the *why* isn't obvious from the description.
5. Stage the relevant files by name (avoid `git add -A` or `git add .`).
6. Commit using a HEREDOC for the message, always appending the co-author trailer:

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <description>

<optional body>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

7. Run `git status` after committing to verify success.
8. If the pre-commit hook rejects the commit, fix the issue and create a NEW commit (never amend).
