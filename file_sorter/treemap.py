"""Treemap layout (no tkinter, so it can be tested anywhere)."""

from __future__ import annotations


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap layout. values must be sorted largest first and sum to w*h."""
    rects: list[tuple[float, float, float, float]] = []
    vals = [v for v in values if v > 0]

    def worst(row: list[float], side: float) -> float:
        s = sum(row)
        return max(max(side * side * v / (s * s), (s * s) / (side * side * v)) for v in row)

    while vals:
        side = min(w, h)
        if side <= 0:
            break
        row = [vals[0]]
        i = 1
        while i < len(vals) and worst(row + [vals[i]], side) <= worst(row, side):
            row.append(vals[i])
            i += 1
        s = sum(row)
        if w >= h:
            rw, yy = s / h, y
            for v in row:
                rects.append((x, yy, rw, v / rw))
                yy += v / rw
            x, w = x + rw, w - rw
        else:
            rh, xx = s / w, x
            for v in row:
                rects.append((xx, y, v / rh, rh))
                xx += v / rh
            y, h = y + rh, h - rh
        vals = vals[i:]
    return rects
