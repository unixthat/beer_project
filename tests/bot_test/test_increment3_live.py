import re

from .utils import run_match

SHOT_RE = re.compile(r"^SHOT ([A-J])(10|[1-9])$")
HIT_RE = re.compile(r"^HIT")
MISS_RE = re.compile(r"^MISS")


def _coord(s: str):
    row = ord(s[0]) - ord("A")
    col = int(s[1:]) - 1
    return row, col


def parse(bot_out: str):
    shots = []
    outcomes = []
    idx = -1
    for ln in bot_out.splitlines():
        ln = ln.strip()
        m = SHOT_RE.match(ln)
        if m:
            shots.append(_coord(m.group(1) + m.group(2)))
            idx += 1
            continue
        if idx >= 0 and len(outcomes) < len(shots):
            if HIT_RE.match(ln):
                outcomes.append("HIT")
            elif MISS_RE.match(ln):
                outcomes.append("MISS")
            elif "SUNK" in ln.upper():
                outcomes.append("SUNK")
    return shots, outcomes


def monotone(seq):
    if len(seq) <= 1:
        return True
    diffs = [b - a for a, b in zip(seq, seq[1:])]
    sign = 0
    for d in diffs:
        if d == 0:
            continue
        if sign == 0:
            sign = 1 if d > 0 else -1
        elif sign * d < 0:
            return False
    return True


def test_increment3_axis_sweep_full_game():
    out1, out2 = run_match(timeout=90)

    for bot_out in (out1, out2):
        shots, outcomes = parse(bot_out)
        # find first pair of aligned hits
        first_idx = None
        second_idx = None
        for i, (rc, res) in enumerate(zip(shots, outcomes)):
            if res != "HIT":
                continue
            if first_idx is None:
                first_idx = i
            else:
                r0, c0 = shots[first_idx]
                r1, c1 = rc
                if r0 == r1 or c0 == c1:
                    second_idx = i
                    break
        assert second_idx is not None, "Bot never produced two aligned hits"

        # determine axis
        axis_row = shots[first_idx][0] if shots[first_idx][0] == shots[second_idx][0] else None
        axis_col = shots[first_idx][1] if shots[first_idx][1] == shots[second_idx][1] else None

        # collect subsequent axis shots until cluster ends (parity shot resumes)
        axis_shots = []
        axis_outcomes = []
        for rc, res in zip(shots[second_idx + 1 :], outcomes[second_idx + 1 :]):
            if axis_row is not None and rc[0] == axis_row:
                axis_shots.append(rc)
                axis_outcomes.append(res)
            elif axis_col is not None and rc[1] == axis_col:
                axis_shots.append(rc)
                axis_outcomes.append(res)
            else:
                break  # parity hunt resumed

        # Axis shots must be monotone outward
        if axis_row is not None:
            cols = [c for _, c in axis_shots]
            assert monotone(cols), f"Axis sweep changed direction {cols}"
        else:
            rows = [r for r, _ in axis_shots]
            assert monotone(rows), f"Axis sweep changed direction {rows}"

        # No duplicates
        assert len(axis_shots) == len(set(axis_shots)), "Sweep repeated a coordinate"

        # Verify that both directions were closed: need at least one MISS or SUNK at
        # the low end and at the high end of the swept indices.
        if axis_row is not None:
            cols = [c for _, c in axis_shots]
            left_idx = cols.index(min(cols))
            right_idx = cols.index(max(cols))
            assert axis_outcomes[left_idx] in {"MISS", "SUNK"}, "Left end never closed"
            assert axis_outcomes[right_idx] in {"MISS", "SUNK"}, "Right end never closed"
        else:
            rows = [r for r, _ in axis_shots]
            top_idx = rows.index(min(rows))
            bot_idx = rows.index(max(rows))
            assert axis_outcomes[top_idx] in {"MISS", "SUNK"}, "Upper end never closed"
            assert axis_outcomes[bot_idx] in {"MISS", "SUNK"}, "Lower end never closed"
