"""CLI client wrapper in the package version."""

from __future__ import annotations

import argparse
import socket
import threading
from io import BufferedReader, BufferedWriter
from typing import TextIO, Optional

from .common import (
    PacketType,
    FrameError,
    IncompleteError,
    recv_pkt,
    enable_encryption,
    DEFAULT_KEY,
)
from .battleship import SHIP_LETTERS

HOST = "127.0.0.1"
PORT = 5000


# ---------------------------- receiver -----------------------------


def _print_grid(rows: list[str]) -> None:
    print("\n[Board]")
    columns = len(rows[0].split())
    header = "   " + " ".join(f"{i:>2}" for i in range(1, columns + 1))
    print(header)
    for idx, row in enumerate(rows):
        label = chr(ord("A") + idx)
        cells = row.split()
        formatted = " ".join(f"{c:>2}" for c in cells)
        print(f"{label:2} {formatted}")


# ------------------------------------------------------------
# Enhanced dual-board renderer
# ------------------------------------------------------------


_SHIP_CHARS = set(SHIP_LETTERS.values())


def _is_reveal_grid(rows: list[str]) -> bool:
    """Return True if *rows* contain ship letters, i.e. own fleet view."""
    for row in rows:
        for cell in row.split():
            if cell in _SHIP_CHARS:
                return True
    return False


def _print_dual_grid(opp_rows: list[str], own_rows: list[str]) -> None:
    """Pretty-print *opp_rows* and *own_rows* side by side."""

    if not opp_rows or not own_rows:
        return

    print("\n[Opponent Board]                        |   [Your Fleet]")
    columns = len(opp_rows[0].split())
    header = "   " + " ".join(f"{i:>2}" for i in range(1, columns + 1))
    print(f"{header}   |   {header}")

    for idx in range(len(opp_rows)):
        label = chr(ord("A") + idx)
        opp_cells = opp_rows[idx].split()
        own_cells = own_rows[idx].split()
        left = " ".join(f"{c:>2}" for c in opp_cells)
        right = " ".join(f"{c:>2}" for c in own_cells)
        print(f"{label:2} {left}   |   {label:2} {right}")


# ------------------------------------------------------------
# Receiver
# ------------------------------------------------------------


def _recv_loop(sock: socket.socket, stop_evt: threading.Event) -> None:  # pragma: no cover
    """Continuously print messages from the server (framed packets only)."""
    br = sock.makefile("rb")  # buffered reader

    last_opp: Optional[list[str]] = None
    last_own: Optional[list[str]] = None

    try:
        while True:
            try:
                ptype, seq, obj = recv_pkt(br)  # type: ignore[arg-type]
            except IncompleteError:
                # Stream closed cleanly – exit receiver loop without warning.
                stop_evt.set(); break
            except FrameError as exc:
                print(f"[WARN] Frame error: {exc}.")
                stop_evt.set(); break
            except Exception:
                # Socket closed or unreadable – terminate receiver thread.
                stop_evt.set(); break

            if ptype == PacketType.GAME and isinstance(obj, dict):
                if obj.get("type") == "grid":
                    rows = obj["rows"]
                    if _is_reveal_grid(rows):
                        # Own fleet grid – store for later but don't print yet.
                        last_own = rows
                    else:
                        # Opponent board grid – print combined view using the
                        # latest own-grid snapshot (if any). This happens once
                        # at the start of *our* turn and avoids the duplicate
                        # print that previously occurred right after our shot.
                        last_opp = rows
                        if last_own:
                            _print_dual_grid(last_opp, last_own)
                else:
                    msg = obj.get("msg", obj)
                    # Ignore low-level HIT/MISS/SUNK protocol lines – we rely on
                    # descriptive messages instead.
                    if isinstance(msg, str) and msg.startswith(("HIT ", "MISS", "SUNK")):
                        continue
                    print(msg)
            elif ptype == PacketType.CHAT:
                print(f"[CHAT] {obj.get('name')}: {obj.get('msg')}")
            else:
                print(obj)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Receiver thread crashed: {exc!r}")
    finally:
        stop_evt.set()


# ----------------------------- main -------------------------------


def main() -> None:    # pragma: no cover – CLI entry
    """Interactive CLI client."""

    parser = argparse.ArgumentParser(description="BEER CLI client")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--secure", nargs="?", const="default", help="Enable AES-CTR encryption optionally with hex key"
    )
    args = parser.parse_args()

    if args.secure is not None:
        key = DEFAULT_KEY if args.secure == "default" else bytes.fromhex(args.secure)
        enable_encryption(key)
        print("[INFO] Encryption enabled in client")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        _extracted_from_main_18(s, args)


# TODO Rename this here and in `main`
def _extracted_from_main_18(s, args):
    s.connect((args.host, args.port))

    stop_evt = threading.Event()
    receiver = threading.Thread(target=_recv_loop, args=(s, stop_evt), daemon=True)
    receiver.start()

    wfile = s.makefile("w")

    try:
        while True:
            if stop_evt.is_set():
                print("[INFO] Disconnected from server. Exiting client.")
                break

            # Non-blocking prompt when server disconnected: input would still block.
            # Use select on stdin to avoid hang after disconnection.
            import sys, select
            if not locals().get("_prompt_shown", False):
                print(">> ", end="", flush=True)
                _prompt_shown = True  # type: ignore[var-annotated]

            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not ready:
                continue
            user_input = sys.stdin.readline().rstrip("\n")
            _prompt_shown = False
            if not user_input:
                continue
            if user_input.startswith("/chat "):
                user_input = f"CHAT {user_input[6:]}"
            wfile.write(user_input + "\n")
            wfile.flush()
    except KeyboardInterrupt:
        print("\n[INFO] Client exiting.")
    finally:
        stop_evt.set()


if __name__ == "__main__":  # pragma: no cover
    main()
