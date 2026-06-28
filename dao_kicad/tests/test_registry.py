"""Tests for the capability registry / adapter spine (pure logic, no tools)."""
from __future__ import annotations

from daokicad import adapters
from daokicad.registry import (CAPABILITIES, Backend, CapabilityError, Probe,
                               Registry)


def test_probe_kinds_are_honest():
    assert Probe("builtin").check()[0] is True
    # a module that certainly does not exist must report unavailable
    assert Probe("python", module="no_such_module_xyz").check()[0] is False
    assert Probe("cli", cli="definitely-not-a-real-exe-xyz").check()[0] is False
    assert Probe("cloud", env="DAO_TEST_UNSET_ENV_XYZ").check()[0] is False
    assert Probe("func", func=lambda: True, label="t").check() == (True, "t")
    # a raising func degrades to unavailable, never crashes
    def boom():
        raise RuntimeError("x")
    assert Probe("func", func=boom).check()[0] is False


def test_best_picks_highest_priority_available():
    reg = Registry()
    reg.register(Backend("low", "route", "", "", "", Probe("builtin"), priority=10))
    reg.register(Backend("high", "route", "", "", "", Probe("builtin"), priority=90))
    reg.register(Backend("absent", "route", "", "", "",
                         Probe("python", module="no_such_xyz"), priority=99))
    best = reg.best("route")
    assert best is not None and best.name == "high"      # absent is skipped
    assert reg.best("route", prefer="low").name == "low"  # explicit choice wins


def test_run_uses_first_runnable_and_tags_backend():
    reg = Registry()
    reg.register(Backend("declared", "drc", "", "", "", Probe("builtin"),
                         priority=80))  # available but no invoke
    reg.register(Backend("runner", "drc", "", "", "", Probe("builtin"),
                         priority=50, invoke=lambda **k: {"ok": True}))
    out = reg.run("drc")
    assert out["ok"] is True and out["backend"] == "runner"


def test_run_without_runnable_raises():
    reg = Registry()
    reg.register(Backend("declared", "bom", "", "", "", Probe("builtin")))
    try:
        reg.run("bom")
        assert False, "expected CapabilityError"
    except CapabilityError:
        pass


def test_unknown_capability_rejected():
    reg = Registry()
    try:
        reg.register(Backend("x", "not_a_capability", "", "", "", Probe("builtin")))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_default_registry_covers_every_capability():
    """Every declared capability domain must have at least one backend, and the
    whole-chain anchors (place/route/drc/fabricate) a builtin always-present one
    so the system is never dead in the water."""
    reg = adapters.default_registry()
    desc = reg.describe()
    assert set(desc) == set(CAPABILITIES)
    for cap in CAPABILITIES:
        assert desc[cap]["backends"], f"{cap} has no backend"
    # route always has the builtin daisy fallback declared
    names = {b["name"] for b in desc["route"]["backends"]}
    assert {"freerouting", "daisy"} <= names


def test_describe_is_json_safe():
    import json
    json.dumps(adapters.default_registry().describe())  # must not raise
