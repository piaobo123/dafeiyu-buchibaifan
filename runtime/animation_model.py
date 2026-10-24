"""Pure animation state model for the BigFish native helper.

The model intentionally has no Qt dependency. It keeps durable DSH state
separate from temporary visual overlays so a click, idle micro-animation, or
success pulse always returns to the newest Agent state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STATES = {"IDLE", "THINKING", "WORKING", "WAITING", "SUCCESS", "ERROR", "DISCONNECTED"}


@dataclass(frozen=True)
class Clip:
    name: str
    frames: tuple[str, ...]
    frame_ms: int
    loop: bool
    motion: str | None = None


class AnimationModel:
    """Pure animation state model for the BigFish native helper.

    The model intentionally has no Qt dependency. It keeps durable DSH state
    separate from temporary visual overlays so a click, idle micro-animation, or
    success pulse always returns to the newest Agent state.
    """

    def __init__(self, manifest: dict[str, Any]) -> None:
        self.clips = {
            name: Clip(
                name=name,
                frames=tuple(value["frames"]),
                frame_ms=int(value["frameMs"]),
                loop=bool(value["loop"]),
                motion=value.get("motion"),
            )
            for name, value in manifest["clips"].items()
        }
        self.state_map = dict(manifest["stateMap"])
        self.working_activity_map = dict(manifest.get("workingActivityMap", {}))
        self.idle_micro_clips = tuple(manifest.get("idleMicroClips", ()))
        self.base_state = "IDLE"
        self.base_activity: str | None = None
        self.base_clip_name = self.state_map["IDLE"]
        self.overlay_clip_name: str | None = None
        self.pulse_state: str | None = None
        self.pulse_deadline_ms: int | None = None
        self.pulse_clip_name: str | None = None
        self.active_clip_name = self.base_clip_name
        self.frame_index = 0
        self.frame_elapsed_ms = 0

    @property
    def active_clip(self) -> Clip:
        return self.clips[self.active_clip_name]

    @property
    def frame(self) -> str:
        return self.active_clip.frames[self.frame_index]

    def apply_state(self, state: str, activity: str | None = None) -> None:
        if state not in STATES:
            return
        self.base_state = state
        self.base_activity = activity
        self.base_clip_name = self._clip_for(state, activity)
        self.pulse_state = None
        self.pulse_deadline_ms = None
        self.pulse_clip_name = None
        if self.overlay_clip_name is None:
            self._activate(self.base_clip_name)

    def apply_pulse(
        self,
        state: str,
        ttl_ms: int,
        now_ms: int,
        resume_state: str | None = None,
        resume_activity: str | None = None,
    ) -> None:
        if state not in STATES or ttl_ms <= 0:
            return
        if resume_state in STATES:
            self.base_state = resume_state
            self.base_activity = resume_activity
            self.base_clip_name = self._clip_for(resume_state, resume_activity)
        self.pulse_state = state
        self.pulse_deadline_ms = now_ms + ttl_ms
        self.pulse_clip_name = self._clip_for(state, None)
        if self.overlay_clip_name is None:
            self._activate(self.pulse_clip_name)

    def play_overlay(self, clip_name: str) -> bool:
        if clip_name not in self.clips:
            return False
        self.overlay_clip_name = clip_name
        self._activate(clip_name)
        return True

    def clear_overlay(self) -> None:
        self.overlay_clip_name = None
        self._activate(self._underlay_clip_name())

    def play_idle_micro(self, index: int = 0) -> bool:
        if self.base_state != "IDLE" or self.overlay_clip_name is not None or self.pulse_state is not None:
            return False
        if not self.idle_micro_clips:
            return False
        return self.play_overlay(self.idle_micro_clips[index % len(self.idle_micro_clips)])

    def advance(self, elapsed_ms: int, now_ms: int) -> None:
        if elapsed_ms < 0:
            return
        if self.pulse_deadline_ms is not None and now_ms >= self.pulse_deadline_ms:
            self.pulse_state = None
            self.pulse_deadline_ms = None
            self.pulse_clip_name = None
            if self.overlay_clip_name is None:
                self._activate(self.base_clip_name)

        clip = self.active_clip
        if len(clip.frames) <= 1:
            return
        self.frame_elapsed_ms += elapsed_ms
        while self.frame_elapsed_ms >= clip.frame_ms:
            self.frame_elapsed_ms -= clip.frame_ms
            if self.frame_index + 1 < len(clip.frames):
                self.frame_index += 1
                continue
            if clip.loop:
                self.frame_index = 0
                continue
            if self.overlay_clip_name is not None:
                self.overlay_clip_name = None
                self._activate(self._underlay_clip_name())
            else:
                self.frame_index = len(clip.frames) - 1
            break

    def _clip_for(self, state: str, activity: str | None) -> str:
        if state == "WORKING" and activity in self.working_activity_map:
            return self.working_activity_map[activity]
        return self.state_map.get(state, self.state_map["IDLE"])

    def _underlay_clip_name(self) -> str:
        return self.pulse_clip_name or self.base_clip_name

    def _activate(self, clip_name: str) -> None:
        if self.active_clip_name == clip_name:
            return
        self.active_clip_name = clip_name
        self.frame_index = 0
        self.frame_elapsed_ms = 0


# --- Action pacing ---------------------------------------------------------
# Session events can arrive dozens of times per second (thinking -> tool call
# -> thinking), and every one of them used to restart the pose. The scheduler
# keeps a small priority queue of desired actions and lets one through only
# after the current pose has dwelled long enough and the global cooldown has
# lapsed. Texts and the status card stay instant; only the pose is paced.

STATE_PRIORITY = {
    "DISCONNECTED": -1,
    "IDLE": 0,
    "THINKING": 20,
    "WORKING": 30,
    "SUCCESS": 40,
    "ERROR": 50,
    "WAITING": 60,
}

MICRO_PRIORITY = 5
INTERACTION_PRIORITY = 55
URGENT_PRIORITY = 50


@dataclass(frozen=True)
class ActionRequest:
    """One queued pose request created from a state, micro or interaction."""

    state: str
    activity: str | None
    priority: int
    queued_at_ms: int
    clip: str | None = None


class ActionScheduler:
    """Bounds how often the visible animation may change.

    Only the newest request per lane survives in the queue (a burst of
    THINKING/WORKING events collapses to the freshest pose), the current pose
    must dwell before it is replaced, and every swap waits for the global
    cooldown. WAITING/ERROR may preempt earlier than the dwell floor.
    """

    MAX_QUEUE = 8
    MICRO_STALE_MS = 4000

    def __init__(
        self,
        model: AnimationModel,
        *,
        cooldown_ms: int = 800,
        dwell_ms: int = 1500,
        urgent_after_ms: int = 250,
        micro_cooldown_ms: int = 26000,
        micro_repeat_ms: int = 90000,
        interaction_cooldown_ms: int = 400,
        interaction_repeat_ms: int = 1200,
        now_ms: int = 0,
    ) -> None:
        self.model = model
        self.cooldown_ms = max(0, int(cooldown_ms))
        self.dwell_ms = max(0, int(dwell_ms))
        self.urgent_after_ms = max(0, int(urgent_after_ms))
        self.micro_cooldown_ms = max(0, int(micro_cooldown_ms))
        self.micro_repeat_ms = max(0, int(micro_repeat_ms))
        self.interaction_cooldown_ms = max(0, int(interaction_cooldown_ms))
        self.interaction_repeat_ms = max(0, int(interaction_repeat_ms))
        self._queue: list[ActionRequest] = []
        self._last_switch_ms = int(now_ms)
        self._last_micro_ms = int(now_ms) - self.micro_cooldown_ms
        self._micro_clip_ms: dict[str, int] = {}
        self._last_interaction_ms = int(now_ms) - self.interaction_cooldown_ms
        self._interaction_clip_ms: dict[str, int] = {}
        self._applied_state = model.base_state
        self._applied_activity = model.base_activity
        self._applied_clip: str | None = None
        self.current_priority = STATE_PRIORITY.get(model.base_state, 0)

    # -- configuration ---------------------------------------------------
    def configure(self, *, cooldown_ms: Any = None, dwell_ms: Any = None) -> None:
        if isinstance(cooldown_ms, (int, float)) and not isinstance(cooldown_ms, bool):
            self.cooldown_ms = max(200, min(4000, int(cooldown_ms)))
        if isinstance(dwell_ms, (int, float)) and not isinstance(dwell_ms, bool):
            self.dwell_ms = max(400, min(6000, int(dwell_ms)))

    # -- queue -----------------------------------------------------------
    def request_state(self, state: str, activity: str | None, now_ms: int) -> None:
        if state not in STATE_PRIORITY:
            return
        self._enqueue(ActionRequest(state, activity, STATE_PRIORITY[state], int(now_ms)))

    def request_micro(self, clip: str, now_ms: int) -> bool:
        if int(now_ms) - self._last_micro_ms < self.micro_cooldown_ms:
            return False
        if clip in self._micro_clip_ms:
            if int(now_ms) - self._micro_clip_ms[clip] < self.micro_repeat_ms:
                return False
        self._enqueue(ActionRequest("MICRO", None, MICRO_PRIORITY, int(now_ms), clip=clip))
        return True

    def request_interaction(self, clip: str, now_ms: int) -> bool:
        """Click/drag reactions stay immediate but never stack on each other."""
        now = int(now_ms)
        if now - self._last_interaction_ms < self.interaction_cooldown_ms:
            return False
        if now - self._interaction_clip_ms.get(clip, -10**9) < self.interaction_repeat_ms:
            return False
        if self.model.overlay_clip_name is not None:
            return False
        if not self.model.play_overlay(clip):
            return False
        self._last_interaction_ms = now
        self._interaction_clip_ms[clip] = now
        self._last_switch_ms = now
        self._applied_clip = clip
        self.current_priority = INTERACTION_PRIORITY
        return True

    def force_overlay(self, clip: str, now_ms: int) -> bool:
        if not self.model.play_overlay(clip):
            return False
        self._last_switch_ms = int(now_ms)
        self._applied_clip = clip
        self.current_priority = INTERACTION_PRIORITY
        return True

    def force_state(self, state: str, activity: str | None, now_ms: int) -> None:
        self._queue.clear()
        if self.model.overlay_clip_name is not None:
            self.model.clear_overlay()
        self.model.apply_state(state, activity)
        self._last_switch_ms = int(now_ms)
        self.current_priority = STATE_PRIORITY.get(state, 0)
        self._applied_state = state
        self._applied_activity = activity
        self._applied_clip = None

    def note_passive_switch(self, now_ms: int) -> None:
        """The model returned to its base pose on its own (pulse expiry etc.)."""
        self._last_switch_ms = int(now_ms)
        self.current_priority = STATE_PRIORITY.get(self.model.base_state, 0)
        self._applied_state = self.model.base_state
        self._applied_activity = self.model.base_activity
        self._applied_clip = None

    def pending(self) -> int:
        return len(self._queue)

    # -- pump ------------------------------------------------------------
    def tick(self, now_ms: int) -> bool:
        if not self._queue:
            return False
        now = int(now_ms)
        ready = max(self._queue, key=lambda item: (item.priority, item.queued_at_ms))

        if ready.clip is not None and now - ready.queued_at_ms > self.MICRO_STALE_MS:
            self._queue.remove(ready)
            return False
        if ready.clip is not None:
            if ready.clip == self._applied_clip and self.model.overlay_clip_name is not None:
                self._queue.remove(ready)
                return False
        elif ready.state == self._applied_state and ready.activity == self._applied_activity:
            self._queue.remove(ready)
            return False

        waited = now - self._last_switch_ms
        urgent = ready.priority >= URGENT_PRIORITY and ready.priority > self.current_priority
        if urgent:
            if waited < self.urgent_after_ms:
                return False
        elif waited < self.cooldown_ms or waited < self.dwell_ms:
            return False

        if ready.clip is not None:
            if now - self._last_micro_ms < self.micro_cooldown_ms:
                self._queue.remove(ready)
                return False
            if now - self._micro_clip_ms.get(ready.clip, -10**9) < self.micro_repeat_ms:
                self._queue.remove(ready)
                return False
            if self.model.base_state != "IDLE" or self.model.pulse_state is not None:
                self._queue.remove(ready)
                return False
            if self.model.overlay_clip_name is not None:
                self.model.clear_overlay()
            if not self.model.play_overlay(ready.clip):
                self._queue.remove(ready)
                return False
            self._last_micro_ms = now
            self._micro_clip_ms[ready.clip] = now
            self._applied_clip = ready.clip
        else:
            if self.model.overlay_clip_name is not None:
                self.model.clear_overlay()
            self.model.apply_state(ready.state, ready.activity)
            self._applied_state = ready.state
            self._applied_activity = ready.activity
            self._applied_clip = None

        self._queue.remove(ready)
        self._last_switch_ms = now
        self.current_priority = ready.priority
        return True

    # -- internals -------------------------------------------------------
    def _enqueue(self, request: ActionRequest) -> None:
        if request.clip is None:
            # State events describe one moving truth: keep only the newest.
            self._queue = [item for item in self._queue if item.clip is not None]
        else:
            for item in list(self._queue):
                if item.clip == request.clip:
                    self._queue.remove(item)
        self._queue.append(request)
        if len(self._queue) > self.MAX_QUEUE:
            lowest = min(self._queue, key=lambda item: (item.priority, -item.queued_at_ms))
            self._queue.remove(lowest)
