# AGENTS.md
Repository-specific guidance for coding agents working in `/Users/morganjonasson/dev/cloudflare_ddns`.

## Repo Summary
- Small, flat Python repo with no package structure.
- Main updater: `cloudflare_ddns.py`.
- Interactive setup helper: `configure_cloudflare_ddns.py`.
- Docs: `README.md`.
- Config example: `.env.example`.
- Record map example: `cloudflare_records.example.json`.
- Runtime files may include `.env` and `.cloudflare_ddns_state.json`.

## Instruction Files
- No prior `AGENTS.md` existed here.
- No `.cursorrules` file exists.
- No `.cursor/rules/` directory exists.
- No `.github/copilot-instructions.md` exists.
- Do not assume hidden Cursor or Copilot instructions.

## Tooling Reality
- No `pyproject.toml`, `requirements.txt`, `setup.cfg`, `tox.ini`, `noxfile.py`, or `Makefile`.
- No CI config is present.
- No automated tests are present.
- No configured formatter or linter is present.
- The repo currently relies only on the Python standard library.
- Do not invent commands like `pytest`, `ruff`, `black`, `mypy`, or `make test` unless those tools are added later.

## Confirmed Commands

Run the updater:
```bash
python3 cloudflare_ddns.py
```

Run the setup helper:
```bash
python3 configure_cloudflare_ddns.py
```

Show helper CLI usage:
```bash
python3 configure_cloudflare_ddns.py --help
```

Syntax-check both scripts:
```bash
python3 -m py_compile cloudflare_ddns.py configure_cloudflare_ddns.py
```

Safe no-config check:
```bash
python3 cloudflare_ddns.py
```
Expected current behavior: it exits with `CF_API_TOKEN is required` when no config is present.

## Build, Lint, Test
- Build: no build step exists; use `python3 -m py_compile ...` as the closest syntax/build validation.
- Lint: no linter is configured; prefer `lsp_diagnostics` when available.
- Test: no automated tests exist.
- Single test: not supported because there are no tests.
- If tests or tooling are added later, update this file with exact commands.

## Manual Validation
- `python3 -m py_compile cloudflare_ddns.py configure_cloudflare_ddns.py`
- `python3 configure_cloudflare_ddns.py --help`
- Safe no-config runs that fail before live Cloudflare updates
- Do not run live Cloudflare update flows unless the task explicitly requires it and valid credentials are available.

## Architecture Notes
- `cloudflare_ddns.py` holds most core logic.
- `CloudflareClient` is the shared place for Cloudflare API requests.
- Config is env-driven and `.env` is loaded automatically by the updater.
- The default setup keeps the API token in `.env` and record mappings in `cloudflare_records.json`.
- The updater caches the last IP plus a config fingerprint in JSON state.
- The helper scans Cloudflare for matching `A` records and writes `.env` plus `cloudflare_records.json`.
- Prefer extending existing helpers instead of duplicating Cloudflare request code.

## Code Style to Follow

### Python and typing
- Target Python 3.10+.
- Keep `from __future__ import annotations`.
- Use built-in generics like `list[str]`, `dict[str, Any]`, and `tuple[str, ...]`.
- Use frozen dataclasses for simple structured data.
- Add type hints to functions and important variables.
- Use `Any` only where decoded JSON genuinely requires it.

### Imports
- Group imports as: future import, standard library, local imports.
- Use explicit imports.
- Avoid unused imports.

### Formatting
- Use 4-space indentation.
- Keep formatting Black-like even though Black is not configured.
- Use double quotes consistently.
- Prefer readable wrapped calls with trailing commas when multi-line.

### Naming
- `snake_case` for functions and variables.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.
- `CF_*` uppercase names for environment variables.

### Error handling
- Raise `DDNSError` for user-facing operational failures.
- Wrap lower-level exceptions with context-rich messages.
- Fail fast on invalid config or malformed API responses.
- Do not silently swallow exceptions.
- Keep `main()` entrypoints responsible for stderr output and exit codes.

### CLI and file handling
- Keep scripts directly executable via `if __name__ == "__main__"`.
- Use `argparse` for CLI flags.
- Interactive prompts should degrade safely in non-interactive environments.
- Use `pathlib.Path` for local files where practical.
- Use UTF-8 explicitly for reads and writes.
- Preserve existing `.env` keys unless intentionally replacing them.
- Quote `.env` values when writing them.
- Treat `.env` as sensitive because it may contain API tokens.

### Cloudflare integration style
- Reuse `CloudflareClient` rather than duplicating request code.
- Validate Cloudflare JSON before trusting fields.
- Prefer documented structured filters such as `name.exact` and `content.exact`.
- Preserve record metadata like `ttl` and `proxied` when updating.
- Avoid unnecessary Cloudflare API calls when local state proves nothing changed.

## Change Guidelines
- Keep the repo zero-dependency unless a new dependency is clearly justified.
- Prefer standard library solutions first.
- Avoid introducing package machinery unless explicitly requested.
- Update `README.md` when user-facing behavior changes.
- Update `.env.example` when config variables change.
- Update this file when tooling or workflow changes.

## Things Not to Assume
- Do not assume a test framework exists.
- Do not assume `pip install -r requirements.txt` is valid.
- Do not assume a formatter is available.
- Do not assume Cloudflare credentials are available locally.
- Do not assume live network calls are safe during validation.

## Default Validation Stack
For most changes in this repo:
1. Read the relevant script end-to-end.
2. Run `lsp_diagnostics` on modified Python files.
3. Run `python3 -m py_compile cloudflare_ddns.py configure_cloudflare_ddns.py`.
4. Run `python3 configure_cloudflare_ddns.py --help` if CLI flags changed.
5. Use only safe no-config execution unless live API use is explicitly required.

If tests or tooling are added later, revise this file with exact commands, including how to run a single test.
