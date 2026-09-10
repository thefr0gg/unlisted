# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`unlisted` is a CLI tool that brute-forces YouTube's 11-character video ID space (`[a-zA-Z0-9_-]`) and checks candidates against YouTube's oEmbed endpoint to discover unlisted videos, either scoped to one channel or across all of YouTube (`--open`).

## Commands

```bash
poetry install          # install dependencies into a poetry-managed venv
poetry build             # build sdist/wheel to ./dist
pip install ./dist/unlisted-*.tar.gz   # install the built package
poetry run unlisted dig --channel-identifier <handle> --threads 7
poetry run unlisted dig --open --threads 5
poetry run unlisted version
```

There is no test suite, linter, or CI config in this repo currently.

## Architecture

Entry point: `unlisted:cli.run` (declared in [pyproject.toml](pyproject.toml)) → [unlisted/cli.py](unlisted/cli.py) prints the banner, parses args with `argparse`, and dispatches to `version()`/`dig()`. The package is a flat, single-level module layout (no subpackages).

- **[unlisted/cli.py](unlisted/cli.py)** — `_build_parser()` defines the `argparse` subcommands (`version`, `dig`); `run()` parses and dispatches. `dig()` validates flags/paths, loads a previous result file to resume from (`--ignore-uids-from-result`), constructs `Dig`, then streams output as a plain log: each `console_log(...)` message from worker threads (delivered via a `Queue`) is printed with `console.log(...)` as it arrives, no live-updating panel. On exit (normal completion or `Ctrl+C`) it prints a final summary table (found/checked/failed/blocked/elapsed) via `_print_summary()`.
- **[unlisted/dig.py](unlisted/dig.py)** — the `Dig` class is the core engine:
  - `start()` resolves the channel's known public video IDs via `pytube.Channel` (skipped in `--open` mode) and seeds `_used_set`/`used_videos_uid` so those IDs are never re-tested, registers a `SIGINT` handler that flips `exit_flag` and force-saves, starts a daemon thread that autosaves every 30s, then spawns N daemon worker threads directly (`threading.Thread(..., daemon=True)`) all running `dig()`.
  - `dig()` is the per-thread loop: generate a random unused 11-char candidate ID → hit `https://www.youtube.com/oembed?url=...&format=json` directly (no proxy layer — see note below) → on `200`, record the video (and, in channel mode, only flag it as "found" if the oEmbed author matches the target channel — otherwise it's just logged as belonging to another channel); on `429` back off exponentially (capped at 60s) and increment `rate_limited`; other non-200s (expected: most random IDs don't exist, so `400`/`404` is the common case) increment `faild_attempts`. All shared-state mutations go through `_state_lock` / `_data_lock`.
  - Results are persisted as JSON matching the `UNLISTED_VIDEOS_DATA` template in [unlisted/constants.py](unlisted/constants.py); `_save_results()` is guarded by `_save_lock` and snapshots both `unlisted_videos_data` and `used_videos_uid` on every save.
- **[unlisted/utils.py](unlisted/utils.py)** — small stubbed-then-implemented helpers (`is_url`, `channel_url`) for validating/building channel URLs.
- **[unlisted/messages.py](unlisted/messages.py)** — all user-facing rich-formatted strings (errors and info), some as plain strings and some as lambdas taking interpolation args. Per the in-file NOTE comments, don't reword these except to fix typos or genuine clarity issues.
- **[unlisted/constants.py](unlisted/constants.py)** — package metadata, the banner, and `UNLISTED_VIDEOS_DATA` (the canonical result-file schema: `package`, `version`, `author`, `channel_name`, `unlisted_videos_data`, `used_videos_uid`). Per the in-file NOTE, treat these as stable/important — don't casually edit.

## Key invariants

- Concurrency model is threads (not asyncio); any new shared mutable state on `Dig` needs to go through one of the existing locks (`_state_lock`, `_data_lock`, `_save_lock`) or a new one.
- The result-file schema (`regular_result_keys` in [unlisted/cli.py](unlisted/cli.py) and `UNLISTED_VIDEOS_DATA` in [unlisted/constants.py](unlisted/constants.py)) must stay in sync — both list the same keys and are used to validate `--ignore-uids-from-result` input files.
- Video IDs already known (channel's public videos, or IDs loaded from a resume file) must end up in both `_used_set` (fast membership check) and `used_videos_uid` (serializable list) before workers start.
- Requests to YouTube go out directly, not through a proxy pool — an earlier `proxy_handler.py` (wrapping the `py-proxy` package) was removed because `py-proxy`'s proxy list is unvalidated free/public proxies, most of which are dead; its own validation path has no timeout and narrow exception handling, so it hangs for minutes and returns zero usable proxies. Re-adding IP rotation would need a validator written in this repo (short timeout, broad exception handling, tested against the real oEmbed endpoint) rather than relying on `py-proxy`'s.
