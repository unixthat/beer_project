import re
from collections import Counter

from .utils import run_match

SHOT_RE = re.compile(r"^SHOT ([A-J])(10|[1-9])$")
HIT_RE = re.compile(r"^HIT")
MISS_RE = re.compile(r"^MISS")


def _coord(s: str):
    row = ord(s[0]) - ord("A")
    col = int(s[1:]) - 1
    return row, col


def orthonbrs(rc):
    r, c = rc
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < 10 and 0 <= nc < 10:
            yield (nr, nc)


def parity(rc):
    return (rc[0] + rc[1]) % 2


def parse(bot_out: str):
    shots = []
    outcomes = []
    idx = -1
    for line in bot_out.splitlines():
        line = line.strip()
        m = SHOT_RE.match(line)
        if m:
            shots.append(_coord(m.group(1) + m.group(2)))
            idx += 1
            continue
        if idx >= 0 and len(outcomes) < len(shots):
            if HIT_RE.match(line):
                outcomes.append("HIT")
            elif MISS_RE.match(line):
                outcomes.append("MISS")
    return shots, outcomes


def test_increment2_first_hit_probe_full_game():
    out1, out2 = run_match()

    for bot_out in (out1, out2):
        shots, outcomes = parse(bot_out)
        # Ensure there is at least one HIT and 5 shots following it
        assert "HIT" in outcomes, "Bot never hit anything!"
        first_hit_index = outcomes.index("HIT")
        first_hit_coord = shots[first_hit_index]

        # Determine expected neighbours inside board, excluding squares already fired earlier
        prior_shots_set = set(shots[: first_hit_index])
        expected_neigh = set(orthonbrs(first_hit_coord)) - prior_shots_set

        probe_count = len(expected_neigh)
        probe_shots = shots[first_hit_index + 1 : first_hit_index + 1 + probe_count]

        assert len(probe_shots) == probe_count, "Bot did not fire correct number of neighbour probes"
        assert Counter(probe_shots).most_common(1)[0][1] == 1, "Neighbour probe repeated"
        assert set(probe_shots) == expected_neigh, "Probe shots not the expected neighbours"

        # Shot after probes resumes parity colour
        next_after_probe = shots[first_hit_index + 1 + probe_count]
        assert parity(next_after_probe) == parity(first_hit_coord), "Bot did not return to parity hunt after probes"
