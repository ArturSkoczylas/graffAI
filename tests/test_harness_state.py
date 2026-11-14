"""Testy harness/state.py – śledzenie przetworzonych Message-ID."""
import errno
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.mail_listener import state as S  # noqa: E402
from harness.src.mail_listener.state import ProcessedState  # noqa: E402


class _PoisonId:
    """Obiekt, którego porównanie zawsze wybucha – symuluje losową usterkę."""

    def __eq__(self, other):
        raise RuntimeError("porównanie się nie powiodło")

    def __hash__(self):
        return 1


# --------------------------------------------------------------------------- load
def test_load_round_trip(tmp_path):
    path = tmp_path / "state.json"
    original = ProcessedState(processed_ids=["<a@x>", "<b@x>"])
    original.save(path)
    loaded = ProcessedState.load(path)
    assert loaded == original


def test_load_missing_file_returns_empty(tmp_path):
    loaded = ProcessedState.load(tmp_path / "nope.json")
    assert loaded.processed_ids == []


def test_load_empty_file_returns_empty(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    assert ProcessedState.load(path).processed_ids == []


def test_load_truncated_json_returns_empty(tmp_path):
    path = tmp_path / "truncated.json"
    path.write_text('{"processed_ids": ["a", "b"', encoding="utf-8")
    assert ProcessedState.load(path).processed_ids == []


def test_load_wrong_top_level_shape_returns_empty(tmp_path):
    path = tmp_path / "array.json"
    path.write_text('["a", "b"]', encoding="utf-8")
    assert ProcessedState.load(path).processed_ids == []


def test_load_wrong_field_type_returns_empty(tmp_path):
    path = tmp_path / "bad_type.json"
    path.write_text('{"processed_ids": "not-a-list"}', encoding="utf-8")
    assert ProcessedState.load(path).processed_ids == []


def test_load_wrong_element_type_returns_empty(tmp_path):
    path = tmp_path / "bad_elem.json"
    path.write_text('{"processed_ids": [1, 2, 3]}', encoding="utf-8")
    assert ProcessedState.load(path).processed_ids == []


def test_load_unknown_keys_ignored_and_missing_field_defaults(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text('{"foo": "bar"}', encoding="utf-8")
    assert ProcessedState.load(path).processed_ids == []


def test_load_accepts_str_and_path(tmp_path):
    path = tmp_path / "state.json"
    ProcessedState(processed_ids=["<a@x>"]).save(path)
    assert ProcessedState.load(str(path)).processed_ids == ["<a@x>"]
    assert ProcessedState.load(path).processed_ids == ["<a@x>"]


# --------------------------------------------------------------------------- save
def test_save_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "dir" / "state.json"
    ProcessedState(processed_ids=["<a@x>"]).save(path)
    assert path.exists()


def test_save_overwrite_replaces_not_appends(tmp_path):
    path = tmp_path / "state.json"
    ProcessedState(processed_ids=["<a@x>"]).save(path)
    ProcessedState(processed_ids=["<b@x>"]).save(path)
    assert ProcessedState.load(path).processed_ids == ["<b@x>"]


def test_save_empty_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    ProcessedState().save(path)
    assert ProcessedState.load(path).processed_ids == []


def test_save_low_disk_space_propagates(tmp_path, monkeypatch):
    def _no_space(self, *a, **kw):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_text", _no_space)
    with pytest.raises(OSError):
        ProcessedState(processed_ids=["<a@x>"]).save(tmp_path / "state.json")


# --------------------------------------------------------------------------- is_processed
def test_is_processed_true():
    s = ProcessedState(processed_ids=["<a@x>"])
    assert s.is_processed("<a@x>") is True


def test_is_processed_false():
    s = ProcessedState(processed_ids=["<a@x>"])
    assert s.is_processed("<b@x>") is False


def test_is_processed_propagates_unexpected_failure():
    s = ProcessedState(processed_ids=["<a@x>"])
    with pytest.raises(RuntimeError):
        s.is_processed(_PoisonId())


# --------------------------------------------------------------------------- mark_processed
def test_mark_processed_new_id_is_then_processed():
    s = ProcessedState()
    updated = s.mark_processed("<a@x>")
    assert updated.is_processed("<a@x>") is True


def test_mark_processed_duplicate_not_added_twice():
    s = ProcessedState(processed_ids=["<a@x>"])
    updated = s.mark_processed("<a@x>")
    assert updated.processed_ids == ["<a@x>"]


def test_mark_processed_trims_to_cap(monkeypatch):
    monkeypatch.setattr(S, "MAX_PROCESSED", 3)
    s = ProcessedState()
    for i in range(5):
        s = s.mark_processed(f"<{i}@x>")
    assert s.processed_ids == ["<2@x>", "<3@x>", "<4@x>"]


def test_mark_processed_does_not_mutate_original():
    original = ProcessedState(processed_ids=["<a@x>"])
    original.mark_processed("<b@x>")
    assert original.processed_ids == ["<a@x>"]


def test_mark_processed_preserves_baseline_fields():
    # regresja: wcześniejsza implementacja budowała nowy ProcessedState(processed_ids=...)
    # od zera, co zerowało last_uid/uid_validity przy każdym mark_processed.
    s = ProcessedState(processed_ids=[], last_uid=42, uid_validity=7)
    updated = s.mark_processed("<a@x>")
    assert updated.last_uid == 42
    assert updated.uid_validity == 7


# --------------------------------------------------------------------------- baseline UID
def test_has_baseline_false_by_default():
    assert ProcessedState().has_baseline() is False


def test_has_baseline_true_after_with_baseline():
    s = ProcessedState().with_baseline(last_uid=100, uid_validity=7)
    assert s.has_baseline() is True
    assert s.last_uid == 100
    assert s.uid_validity == 7


def test_with_baseline_preserves_processed_ids():
    s = ProcessedState(processed_ids=["<a@x>"]).with_baseline(last_uid=5, uid_validity=1)
    assert s.processed_ids == ["<a@x>"]


def test_with_baseline_overwrites_previous_baseline():
    s = ProcessedState().with_baseline(last_uid=5, uid_validity=1)
    s = s.with_baseline(last_uid=99, uid_validity=2)
    assert s.last_uid == 99
    assert s.uid_validity == 2


def test_advance_uid_moves_forward():
    s = ProcessedState().with_baseline(last_uid=5, uid_validity=1)
    s = s.advance_uid(10)
    assert s.last_uid == 10


def test_advance_uid_ignores_lower_or_equal():
    s = ProcessedState().with_baseline(last_uid=10, uid_validity=1)
    s = s.advance_uid(10)
    assert s.last_uid == 10
    s = s.advance_uid(3)
    assert s.last_uid == 10


def test_advance_uid_from_none_baseline_treats_as_zero():
    s = ProcessedState()
    s = s.advance_uid(7)
    assert s.last_uid == 7
