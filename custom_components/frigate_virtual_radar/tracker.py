"""Keeps Frigate tracked objects in fixed target slots (no Home Assistant imports)."""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .geometry import Calibration, foot_point


@dataclass
class Target:
    """One occupied slot."""

    frigate_id: str
    label: str
    plan_x: float
    plan_y: float
    x_cm: float
    y_cm: float
    sub_label: str | None = None
    score: float | None = None
    stationary: bool = False
    zones: list[str] = field(default_factory=list)
    last_seen: float = 0.0


def _sub_label(value) -> tuple[str | None, float | None]:
    """Frigate sends sub_label as null, a string or [name, score]."""
    if value is None:
        return None, None
    if isinstance(value, (list, tuple)):
        name = value[0] if value else None
        score = value[1] if len(value) > 1 else None
        return (str(name) if name else None), (float(score) if isinstance(score, (int, float)) else None)
    return (str(value) or None), None


class SlotTracker:
    """Assigns Frigate objects of one label group to slots 1..n."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.slots: list[Target | None] = [None] * size

    def index_of(self, frigate_id: str) -> int | None:
        for i, t in enumerate(self.slots):
            if t is not None and t.frigate_id == frigate_id:
                return i
        return None

    def upsert(self, target: Target) -> int | None:
        i = self.index_of(target.frigate_id)
        if i is None:
            i = next((k for k, t in enumerate(self.slots) if t is None), None)
            if i is None:
                return None  # more objects than slots: ignore the extra one
        self.slots[i] = target
        return i

    def remove(self, frigate_id: str) -> int | None:
        i = self.index_of(frigate_id)
        if i is not None:
            self.slots[i] = None
        return i

    def expire(self, now: float, timeout: float) -> list[int]:
        gone = []
        for i, t in enumerate(self.slots):
            if t is not None and now - t.last_seen > timeout:
                self.slots[i] = None
                gone.append(i)
        return gone

    @property
    def count(self) -> int:
        return sum(1 for t in self.slots if t is not None)


class VirtualRadar:
    """Turns Frigate event payloads for one camera into slot updates."""

    def __init__(self, camera: str, calibration: Calibration | None, groups: dict[str, tuple[set[str], int]],
                 min_move_cm: float = 5.0) -> None:
        self.camera = camera
        self.calibration = calibration
        self.labels = {lbl: g for g, (lbls, _) in groups.items() for lbl in lbls}
        self.trackers = {g: SlotTracker(n) for g, (_, n) in groups.items()}
        self.min_move_cm = min_move_cm
        self._published: dict[tuple[str, int], tuple[float, float] | None] = {}

    def handle_event(self, payload: dict, now: float) -> set[tuple[str, int]]:
        """Process one frigate/events payload; return the (group, slot) pairs to publish."""
        after = payload.get("after") or {}
        if after.get("camera") != self.camera:
            return set()
        group = self.labels.get(after.get("label"))
        if group is None:
            return set()
        tracker = self.trackers[group]
        fid = str(after.get("id", ""))
        changed: set[tuple[str, int]] = set()

        if payload.get("type") == "end" or after.get("false_positive"):
            i = tracker.remove(fid)
            if i is not None:
                changed.add((group, i))
            return self._filter(changed)

        if self.calibration is None:
            return set()
        fp = foot_point(after.get("box") or [], self.calibration.image_size)
        plan = self.calibration.to_plan(*fp) if fp else None
        if plan is None:
            return set()
        x_cm, y_cm = self.calibration.to_radar_cm(*plan)
        name, score = _sub_label(after.get("sub_label"))
        target = Target(
            frigate_id=fid, label=after.get("label"), plan_x=round(plan[0], 3), plan_y=round(plan[1], 3),
            x_cm=x_cm, y_cm=y_cm, sub_label=name, score=score if score is not None else after.get("score"),
            stationary=bool(after.get("stationary")), zones=list(after.get("current_zones") or []), last_seen=now,
        )
        old = tracker.index_of(fid)
        prev = tracker.slots[old] if old is not None else None
        i = tracker.upsert(target)
        if i is not None:
            if prev is None or prev.sub_label != target.sub_label or prev.stationary != target.stationary:
                changed.add((group, i))
                self._published.pop((group, i), None)
            else:
                changed.add((group, i))
        return self._filter(changed)

    def expire(self, now: float, timeout: float) -> set[tuple[str, int]]:
        return {(g, i) for g, t in self.trackers.items() for i in t.expire(now, timeout)}

    def target(self, group: str, slot: int) -> Target | None:
        return self.trackers[group].slots[slot]

    def count(self, group: str) -> int:
        return self.trackers[group].count

    def _filter(self, changed: set[tuple[str, int]]) -> set[tuple[str, int]]:
        """Drop position updates smaller than min_move_cm, to keep state writes down."""
        out = set()
        for key in changed:
            t = self.target(*key)
            pos = (t.x_cm, t.y_cm) if t else None
            last = self._published.get(key, "unset")
            if last == "unset" or pos is None or last is None or math.hypot(pos[0] - last[0], pos[1] - last[1]) >= self.min_move_cm:
                self._published[key] = pos
                out.add(key)
        return out
