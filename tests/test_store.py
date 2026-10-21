import json

from hetzner import Product
from store import Store


def product(model, available):
    return Product(model, f"Dedicated Server {model}", available, "€ 1.00", (), None, "1")


def test_no_alert_without_transition(tmp_path):
    s = Store(tmp_path / "state.json")
    s.add(1, "AX42-1", False)
    assert s.apply({"AX42-1": product("AX42-1", False)}) == []


def test_alerts_on_available_then_sold_out(tmp_path):
    s = Store(tmp_path / "state.json")
    s.add(1, "AX42-1", False)
    [c] = s.apply({"AX42-1": product("AX42-1", True)})
    assert (c.model, c.channel_id, c.available) == ("AX42-1", 1, True)
    assert s.apply({"AX42-1": product("AX42-1", True)}) == []
    [c] = s.apply({"AX42-1": product("AX42-1", False)})
    assert not c.available


def test_missing_model_is_unknown_then_recovers(tmp_path):
    s = Store(tmp_path / "state.json")
    s.add(1, "AX42-1", True)
    [c] = s.apply({})
    assert (c.available, c.was, c.product) == (None, True, None)
    assert s.apply({}) == []  # unknown alerts once
    [c] = s.apply({"AX42-1": product("AX42-1", False)})
    assert (c.available, c.was) == (False, None)


def test_unrecognised_button_is_unknown(tmp_path):
    s = Store(tmp_path / "state.json")
    s.add(1, "AX42-1", False)
    [c] = s.apply({"AX42-1": product("AX42-1", None)})
    assert c.available is None


def test_add_while_unknown_sets_baseline(tmp_path):
    s = Store(tmp_path / "state.json")
    s.add(1, "AX42-1", None)
    assert s.apply({"AX42-1": product("AX42-1", None)}) == []
    [c] = s.apply({"AX42-1": product("AX42-1", True)})
    assert (c.available, c.was) == (True, None)


def test_unfocused_models_ignored(tmp_path):
    s = Store(tmp_path / "state.json")
    assert s.apply({"AX42-1": product("AX42-1", True)}) == []


def test_lists_are_per_channel(tmp_path):
    s = Store(tmp_path / "state.json")
    s.add(1, "AX42-1", False)
    s.add(2, "AX42-1", False)
    s.add(2, "EX44-1", False)
    assert s.watched(1) == ["AX42-1"]
    assert s.watched(2) == ["AX42-1", "EX44-1"]
    assert s.watched(3) == []
    changes = s.apply({"AX42-1": product("AX42-1", True), "EX44-1": product("EX44-1", False)})
    assert sorted(c.channel_id for c in changes) == [1, 2]
    assert not s.remove(1, "EX44-1")
    assert s.remove(1, "AX42-1")
    assert s.watched(1) == [] and s.watched(2) == ["AX42-1", "EX44-1"]
    assert "AX42-1" in s.last  # still watched by channel 2


def test_persists_across_restart(tmp_path):
    path = tmp_path / "state.json"
    s = Store(path)
    s.add(1, "AX42-1", False)
    s.add(1, "EX44-1", False)
    assert s.remove(1, "EX44-1")
    s = Store(path)
    assert s.watched(1) == ["AX42-1"]
    assert "EX44-1" not in s.last
    [c] = s.apply({"AX42-1": product("AX42-1", True)})
    assert c.available


def test_migrates_old_server_wide_format(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"focus": {"AX42-1": 1434826486585491570}, "last": {"AX42-1": True}}))
    s = Store(path)
    assert s.watched(1434826486585491570) == ["AX42-1"]
    assert s.apply({"AX42-1": product("AX42-1", True)}) == []
