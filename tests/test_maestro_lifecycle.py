from types import SimpleNamespace

import pytest

from virtuoso_bridge.virtuoso.maestro import lifecycle


class _Client:
    def __init__(self) -> None:
        self.skills: list[str] = []

    def execute_skill(self, skill: str, *, timeout: int | None = None) -> SimpleNamespace:
        self.skills.append(skill)
        return SimpleNamespace(output='"fnxSession9"', errors=[])


def test_open_session_uses_named_view() -> None:
    client = _Client()

    result = lifecycle.open_session(client, "fixture_lib", "fixture_tb", view="maestro_rf")

    assert result == "fnxSession9"
    assert 'maeOpenSetup("fixture_lib" "fixture_tb" "maestro_rf")' in client.skills[0]


def test_open_gui_session_uses_named_view(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    monkeypatch.setattr(lifecycle, "_close_background_sessions", lambda _client: [])
    monkeypatch.setattr(lifecycle, "_get_session_windows", lambda _client: [])
    monkeypatch.setattr(
        lifecycle,
        "_find_session_for_cell",
        lambda _client, lib, cell, view: "fnxSession9"
        if (lib, cell, view) == ("fixture_lib", "fixture_tb", "maestro_rf")
        else None,
    )

    result = lifecycle.open_gui_session(client, "fixture_lib", "fixture_tb", view="maestro_rf", timeout=120)

    assert result == "fnxSession9"
    assert client.skills == ['deOpenCellView("fixture_lib" "fixture_tb" "maestro_rf" "maestro" nil "a")']


def test_open_gui_session_rejects_empty_view() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        lifecycle.open_gui_session(_Client(), "fixture_lib", "fixture_tb", view="")


def test_window_target_match_does_not_confuse_view_name_prefixes() -> None:
    window = {"title": "Assembler Editing: fixture_lib fixture_tb maestro_rf*"}

    assert lifecycle._window_matches_target(window, "fixture_lib", "fixture_tb", "maestro_rf")
    assert not lifecycle._window_matches_target(window, "fixture_lib", "fixture_tb", "maestro")


def test_purge_targets_named_view() -> None:
    client = _Client()

    lifecycle._purge_maestro_cellviews(client, view="maestro_rf", timeout=120)

    assert 'cv~>viewName == "maestro_rf"' in client.skills[0]
