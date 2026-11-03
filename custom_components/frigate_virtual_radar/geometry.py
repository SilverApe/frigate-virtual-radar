"""Camera-to-floor-plan geometry (no Home Assistant imports, so it can be tested on its own).

A homography maps a pixel (u, v) in the camera image onto a point (X, Y) on the floor
plan, as long as that point lies on the floor. Four or more point pairs define it.

The floor plan frame is the one used by the floor plan editor: metres, X to the right,
Y downwards, same orientation as the PNG that Radar Map Manager shows.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math


class CalibrationError(ValueError):
    """Raised when a calibration is missing, malformed or degenerate."""


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve a square linear system with Gaussian elimination and partial pivoting."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise CalibrationError("points are degenerate (three or more on one line?)")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                if f:
                    for c in range(col, n + 1):
                        m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(pairs: list[tuple[tuple[float, float], tuple[float, float]]]) -> list[float]:
    """Return the 3x3 homography (row-major, h33 = 1) for >= 4 (img, plan) pairs.

    With more than four pairs the least-squares solution is used.
    """
    if len(pairs) < 4:
        raise CalibrationError("at least 4 point pairs are needed")
    rows: list[list[float]] = []
    rhs: list[float] = []
    for (u, v), (x, y) in pairs:
        rows.append([u, v, 1, 0, 0, 0, -u * x, -v * x]); rhs.append(x)
        rows.append([0, 0, 0, u, v, 1, -u * y, -v * y]); rhs.append(y)
    if len(rows) == 8:
        h = _solve(rows, rhs)
    else:  # normal equations
        ata = [[sum(r[i] * r[j] for r in rows) for j in range(8)] for i in range(8)]
        atb = [sum(r[i] * rhs[k] for k, r in enumerate(rows)) for i in range(8)]
        h = _solve(ata, atb)
    return h + [1.0]


def apply(h: list[float], u: float, v: float) -> tuple[float, float] | None:
    """Map pixel (u, v) to plan (X, Y); None when the point lies on or above the horizon."""
    w = h[6] * u + h[7] * v + h[8]
    if abs(w) < 1e-9:
        return None
    x = (h[0] * u + h[1] * v + h[2]) / w
    y = (h[3] * u + h[4] * v + h[5]) / w
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return x, y


@dataclass(frozen=True)
class Calibration:
    """A parsed calibration as produced by the calibration tool."""

    image_size: tuple[int, int]
    pairs: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
    origin: tuple[float, float]
    matrix: tuple[float, ...]
    camera: str | None = None

    def to_plan(self, u: float, v: float) -> tuple[float, float] | None:
        return apply(list(self.matrix), u, v)

    def to_radar_cm(self, plan_x: float, plan_y: float) -> tuple[float, float]:
        """Plan metres -> RMM radar frame in cm (radar at the origin, rotation 0).

        RMM, with rotation 0 and no mirror, draws +x to the right and +y upwards,
        so the plan's downward Y is inverted.
        """
        ox, oy = self.origin
        return round((plan_x - ox) * 100.0, 1), round(-(plan_y - oy) * 100.0, 1)

    def reprojection_error_m(self) -> float:
        """Largest distance (m) between a calibration point and where the homography puts it."""
        err = 0.0
        for (u, v), (x, y) in self.pairs:
            p = self.to_plan(u, v)
            if p is None:
                return math.inf
            err = max(err, math.hypot(p[0] - x, p[1] - y))
        return err


def parse_calibration(text: str) -> Calibration:
    """Parse the JSON block copied from the calibration tool."""
    if not text or not text.strip():
        raise CalibrationError("calibration is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise CalibrationError(f"not valid JSON: {err.msg}") from err
    try:
        size = data["image_size"]
        image_size = (int(size[0]), int(size[1]))
        pairs = tuple(
            ((float(p["img"][0]), float(p["img"][1])), (float(p["plan"][0]), float(p["plan"][1])))
            for p in data["points"]
        )
        origin = (float(data["origin"][0]), float(data["origin"][1]))
    except (KeyError, TypeError, IndexError, ValueError) as err:
        raise CalibrationError("expected image_size, points[{img, plan}] and origin") from err
    if image_size[0] <= 0 or image_size[1] <= 0:
        raise CalibrationError("image_size must be positive")
    h = homography(list(pairs))
    cal = Calibration(image_size=image_size, pairs=pairs, origin=origin, matrix=tuple(h),
                      camera=data.get("camera"))
    if cal.reprojection_error_m() > 0.05:
        raise CalibrationError("points do not fit one floor plane (error above 5 cm)")
    return cal


def foot_point(box: list[float], image_size: tuple[int, int]) -> tuple[float, float] | None:
    """Bottom-centre of a Frigate box, in pixels of the detect resolution.

    Frigate MQTT events send [x_min, y_min, x_max, y_max] in pixels. A box whose values
    are all <= 1 is read as relative [x, y, width, height], the format of the HTTP API.
    """
    if not box or len(box) != 4:
        return None
    a, b, c, d = (float(v) for v in box)
    if max(abs(a), abs(b), abs(c), abs(d)) <= 1.0:
        w, h = image_size
        return (a + c / 2.0) * w, (b + d) * h
    return (a + c) / 2.0, d
