"""CLI client wrapper in the package version."""

from __future__ import annotations

import argparse
import socket
import threading
from io import BufferedReader, BufferedWriter
from typing import TextIO

from .common import PacketType, FrameError, recv_pkt, enable_encryption, DEFAULT_KEY

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


def _recv_loop(sock: socket.socket) -> None:  # pragma: no cover
    """Continuously print messages from the server (framed packets only)."""
    br = sock.makefile("rb")  # buffered reader
    try:
        while True:
            try:
                ptype, seq, obj = recv_pkt(br)  # type: ignore[arg-type]
            except FrameError as exc:
                print(f"[WARN] Frame error: {exc}.")
                break
            except Exception:
                # Socket closed or unreadable – terminate receiver thread.
                break

            if ptype == PacketType.GAME and isinstance(obj, dict):
                if obj.get("type") == "grid":
                    _print_grid(obj["rows"])
                else:
                    print(obj.get("msg", obj))
            elif ptype == PacketType.CHAT:
                print(f"[CHAT] {obj.get('name')}: {obj.get('msg')}")
            else:
                print(obj)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Receiver thread crashed: {exc!r}")


# ----------------------------- main -------------------------------


def main() -> None:  # pragma: no cover – CLI entry
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
        s.connect((args.host, args.port))

        receiver = threading.Thread(target=_recv_loop, args=(s,), daemon=True)
        receiver.start()

        wfile = s.makefile("w")

        try:
            while True:
                user_input = input(">> ")
                if not user_input:
                    continue
                if user_input.startswith("/chat "):
                    user_input = "CHAT " + user_input[6:]
                wfile.write(user_input + "\n")
                wfile.flush()
        except KeyboardInterrupt:
            print("\n[INFO] Client exiting.")


if __name__ == "__main__":  # pragma: no cover
    main()
