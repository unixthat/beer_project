import re

from .utils import run_match

SHOT_RE = re.compile(r"^SHOT ([A-J])(10|[1-9])$")
HIT_RE = re.compile(r"^HIT")
MISS_RE = re.compile(r"^MISS")
SUNK_RE = re.compile(r"^SUNK")


def _coord(s: str):
    return ord(s[0]) - ord("A"), int(s[1:]) - 1


def parse(bot_out: str):
    shots, outcomes = [], []
    idx = -1
    for ln in bot_out.splitlines():
        ln = ln.strip()
        if m := SHOT_RE.match(ln):
            shots.append(_coord(m.group(1) + m.group(2)))
            idx += 1
            continue
        if idx >= 0 and len(outcomes) < len(shots):
            if HIT_RE.match(ln):
                outcomes.append("HIT")
            elif MISS_RE.match(ln):
                outcomes.append("MISS")
            elif SUNK_RE.match(ln):
                outcomes.append("SUNK")
    return shots, outcomes


def contiguous(indices):
    return max(indices) - min(indices) + 1 == len(indices)


def test_increment4_gap_fill_full_game():
    out1, out2 = run_match(timeout=120)

    for bot_out in (out1, out2):
        shots, outcomes = parse(bot_out)
        # locate first aligned cluster as before
        first, second = None, None
        for i, (rc, res) in enumerate(zip(shots, outcomes)):
            if res != "HIT":
                continue
            if first is None:
                first = i
            else:
                r0, c0 = shots[first]
                r1, c1 = rc
                if r0 == r1 or c0 == c1:
                    second = i
                    break
        assert second is not None, "No aligned cluster"

        axis_row = shots[first][0] if shots[first][0] == shots[second][0] else None
        axis_col = shots[first][1] if shots[first][1] == shots[second][1] else None

        fired_on_axis = set()
        cluster_active = True
        for rc, res in zip(shots[first:], outcomes[first:]):
            if not cluster_active:
                break
            if axis_row is not None:
                if res == "HIT" and rc[0] == axis_row:
                    fired_on_axis.add(rc[1])
                if res in {"MISS", "SUNK"} and rc[0] == axis_row:
                    fired_on_axis.add(rc[1])
            else:
                if res == "HIT" and rc[1] == axis_col:
                    fired_on_axis.add(rc[0])
                if res in {"MISS", "SUNK"} and rc[1] == axis_col:
                    fired_on_axis.add(rc[0])

            # detect cluster end: parity resumes (off axis shot)
            if axis_row is not None and rc[0] != axis_row:
                cluster_active = False
            elif axis_col is not None and rc[1] != axis_col:
                cluster_active = False

        assert contiguous(sorted(fired_on_axis)), "Gap in fired squares along axis – gap fill missing"
