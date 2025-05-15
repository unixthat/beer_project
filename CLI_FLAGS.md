# CLI Flags Reference

This document summarizes the effect of command-line flags on BEER tools.

| Tool          | No flags                                                                                  | -q / --quiet                                     | -v / --verbose (once)                                          | -vv / --verbose --verbose                                     | --debug                                                   | --host / --port                     | --secure[=<hex>]                                            | --one-ship / --solo                                  | --seed                            |
|---------------|-------------------------------------------------------------------------------------------|--------------------------------------------------|----------------------------------------------------------------|----------------------------------------------------------------|-----------------------------------------------------------|-------------------------------------|------------------------------------------------------------|--------------------------------------------------------|----------------------------------|
| **beer-client** | Shows grid/shot/chat messages; **prints server INFO/ERR lines** (e.g. manual placement prompt, errors); hides spec-grid frames; other raw/unrecognized frames suppressed. | Suppress **all** runtime output except final WIN/LOSE summary. | Identical to no flags (grid/shot/chat); raw frames (unrecognized) now printed. | + Also print spec-grid frames every two shots.                 | Sets `BEER_DEBUG=1` → logger level = DEBUG in client module. | Override default connection endpoint. | Enables AES-CTR encryption (default key or provided hex).     | n/a                                                    | n/a                              |
| **beer-bot**  | Auto-plays: prints grid/shot/chat messages; hides spec-grid; raw frames suppressed.       | Final summary only (WIN/LOSE).                    | + Prints grid/shot/chat; prints raw fallback frames.            | + Also prints spec-grid frames.                                 | Sets `BEER_DEBUG=1` → logger level = DEBUG in bot module.    | Override host/port for server.      | AES-CTR encryption same as client.                           | n/a                                                    | Seed for deterministic play.       |
| **beer-server** | Prints INFO logs (lobby/session lifecycle); config DEFAULT_HOST/PORT. | Alias `-q/--quiet`/`-s/--silent`: suppress all console output. | No effect (verbose parsed but not wired). | No extra behaviour. |

> **Verbosity levels:**
> - `-q` sets verbosity = -1 (quiet).
> - default (no `-q`, no `-v`): verbosity = 0.
> - `-v`: verbosity = 1.
> - `-vv`: verbosity = 2.

> **Printing thresholds (client & bot):**
> - `verbosity >= 0`: grid, shot, chat.
> - `verbosity >= 1`: raw fallback messages.
> - `verbosity >= 2`: spec-grid frames.
