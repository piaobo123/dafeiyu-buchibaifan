"""Timing tests for ActionScheduler (pure Python, no Qt)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime"))

from animation_model import AnimationModel, ActionScheduler  # noqa: E402

MANIFEST = {
    "clips": {
        "idle": {"frames": ["i"], "frameMs": 180, "loop": True},
        "thinking": {"frames": ["t"], "frameMs": 180, "loop": True},
        "working": {"frames": ["w"], "frameMs": 180, "loop": True},
        "working_search": {"frames": ["s1", "s2"], "frameMs": 135, "loop": True},
        "waiting": {"frames": ["wa"], "frameMs": 180, "loop": True},
        "error": {"frames": ["e"], "frameMs": 180, "loop": True},
        "blink": {"frames": ["b1", "b2"], "frameMs": 100, "loop": False},
        "glance": {"frames": ["g1", "g2"], "frameMs": 160, "loop": False},
        "head_pat": {"frames": ["h1", "h2"], "frameMs": 180, "loop": False},
    },
    "stateMap": {
        "IDLE": "idle",
        "THINKING": "thinking",
        "WORKING": "working",
        "WAITING": "waiting",
        "ERROR": "error",
        "SUCCESS": "working",
        "DISCONNECTED": "idle",
    },
    "workingActivityMap": {"searching": "working_search"},
    "idleMicroClips": ["blink", "glance"],
}


def make(**kwargs):
    model = AnimationModel(MANIFEST)
    return model, ActionScheduler(model, cooldown_ms=800, dwell_ms=1500, now_ms=0, **kwargs)


def test_burst_collapses_to_one_request():
    model, scheduler = make()
    for index in range(20):
        state = "THINKING" if index % 2 == 0 else "WORKING"
        scheduler.request_state(state, None, 0)
    assert scheduler.pending() == 1, "a state burst must collapse to the newest request"
    assert scheduler.tick(0) is False
    assert model.active_clip_name == "idle", "nothing may switch before the dwell floor"
    assert scheduler.tick(1000) is False
    assert scheduler.tick(1500) is True
    assert model.active_clip_name == "working"
    assert scheduler.pending() == 0


def test_dwell_and_cooldown_between_switches():
    model, scheduler = make()
    scheduler.request_state("THINKING", None, 0)
    assert scheduler.tick(1500) is True
    scheduler.request_state("WORKING", None, 1600)
    assert scheduler.tick(1600) is False
    assert scheduler.tick(2400) is False, "only 900ms since the last switch"
    assert model.active_clip_name == "thinking"
    assert scheduler.tick(3000) is True
    assert model.active_clip_name == "working"


def test_urgent_preempts_before_dwell():
    model, scheduler = make()
    scheduler.request_state("WORKING", None, 0)
    assert scheduler.tick(1500) is True
    scheduler.request_state("WAITING", None, 1600)
    assert scheduler.tick(1700) is False, "urgent floor is 250ms"
    assert scheduler.tick(1750) is True
    assert model.active_clip_name == "waiting"


def test_micro_dropped_when_busy_and_global_cooldown():
    model, scheduler = make()
    scheduler.request_state("WORKING", None, 0)
    assert scheduler.tick(1500) is True
    assert scheduler.request_micro("blink", 1600) is True
    assert scheduler.tick(3000) is False, "a micro must not interrupt WORKING"
    assert model.overlay_clip_name is None
    scheduler.request_state("IDLE", None, 3100)
    assert scheduler.tick(5000) is True
    assert model.active_clip_name == "idle"
    assert scheduler.request_micro("blink", 50000) is True
    assert scheduler.tick(51500) is True
    assert model.overlay_clip_name == "blink"
    model.clear_overlay()
    scheduler.note_passive_switch(52000)
    assert scheduler.request_micro("blink", 80000) is False, "same clip repeat cooldown"
    assert scheduler.request_micro("glance", 80000) is True


def test_interaction_guard():
    model, scheduler = make()
    assert scheduler.request_interaction("head_pat", 0) is True
    assert scheduler.request_interaction("head_pat", 100) is False, "an overlay is already playing"
    model.clear_overlay()
    scheduler.note_passive_switch(200)
    assert scheduler.request_interaction("head_pat", 300) is False, "interaction cooldown 400ms"
    assert scheduler.request_interaction("head_pat", 1400) is True


def test_force_state_clears_queue():
    model, scheduler = make()
    for _ in range(5):
        scheduler.request_state("WORKING", None, 0)
    scheduler.force_state("ERROR", None, 0)
    assert model.active_clip_name == "error"
    assert scheduler.pending() == 0


def test_activity_change_is_paced_too():
    model, scheduler = make()
    scheduler.request_state("WORKING", "searching", 0)
    assert scheduler.tick(1500) is True
    assert model.active_clip_name == "working_search"
    scheduler.request_state("WORKING", "editing", 1600)
    assert scheduler.tick(2000) is False, "activity flips wait for the dwell floor"
    assert model.active_clip_name == "working_search"
    assert scheduler.tick(3100) is True
    assert model.active_clip_name == "working"


if __name__ == "__main__":
    import traceback
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL {name}: {error!r}")
            traceback.print_exc()
    print("failures:", failures)
    raise SystemExit(1 if failures else 0)
