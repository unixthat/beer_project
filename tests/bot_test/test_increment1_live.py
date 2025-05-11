import re

from .utils import run_match

SHOT_RE = re.compile(r"^SHOT ([A-J])(10|[1-9])$")


def _coord(rc_str: str):
    row = ord(rc_str[0]) - ord("A")
    col = int(rc_str[1:]) - 1
    return row, col


def parity(rc):
    return (rc[0] + rc[1]) % 2


def test_increment1_parity_full_game():
    out1, out2 = run_match()

    for bot_out in (out1, out2):
        evens = True
        for line in bot_out.splitlines():
            m = SHOT_RE.match(line.strip())
            if not m:
                continue
            rc = _coord(m.group(1) + m.group(2))
            if evens:
                assert parity(rc) == 0, "Found odd-parity shot before even squares exhausted"
                if len([None for l in bot_out.splitlines() if SHOT_RE.match(l) and parity(_coord(SHOT_RE.match(l).group(1)+SHOT_RE.match(l).group(2)))==0])>=50:
                    evens=False
            else:
                assert parity(rc) == 1, "Found even-parity shot after odd squares started"
