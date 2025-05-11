import re

from .utils import run_match

SHOT_RE = re.compile(r"^SHOT ([A-J])(10|[1-9])$")
HIT_RE = re.compile(r"^HIT")
MISS_RE = re.compile(r"^MISS")
SUNK_RE = re.compile(r"^SUNK")


def _coord(s: str):
    return ord(s[0]) - ord("A"), int(s[1:]) - 1


def ortho(rc):
    r, c = rc
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < 10 and 0 <= nc < 10:
            yield (nr, nc)


def test_increment5_halo_block_full_game():
    out1, out2 = run_match(timeout=120)

    for bot_out in (out1, out2):
        blocked_coords = set()
        shots = []
        for line in bot_out.splitlines():
            line = line.strip()
            if m := SHOT_RE.match(line):
                shots.append(_coord(m.group(1) + m.group(2)))
                continue
            if SUNK_RE.match(line):
                # Last shot sank a ship
                if shots:
                    sunk_coord = shots[-1]
                    blocked_coords.update(ortho(sunk_coord))
                continue
            # For every new shot ensure it's not firing into blocked halo
            if blocked_coords and SHOT_RE.match(line):
                rc = shots[-1]
                assert rc not in blocked_coords, f"Bot fired into halo square {rc} after SUNK"
