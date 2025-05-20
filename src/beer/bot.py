"""Automated BEER Battleship bot entrypoint using cheat mode."""

import sys
from .client import main as client_main


def main() -> None:
    # Force cheat mode (--win flag) before any other arguments
    sys.argv.insert(1, "--win")
    sys.argv.insert(2, "--debug")
    client_main()


if __name__ == "__main__":
    main()
