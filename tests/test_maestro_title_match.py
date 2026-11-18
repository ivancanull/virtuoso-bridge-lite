"""ADE window titles are matched on whole lib, cell and view tokens."""

from virtuoso_bridge.virtuoso.maestro.lifecycle import _title_names


def test_matches_the_named_view_only() -> None:
    title = "ADE Assembler Editing: LIB TB maestro_non_uniform"
    assert _title_names(title, "LIB", "TB", "maestro_non_uniform")
    assert not _title_names(title, "LIB", "TB", "maestro")


def test_a_cell_name_prefix_is_not_a_match() -> None:
    title = "ADE Assembler Editing: LIB TB_non_uniform maestro"
    assert not _title_names(title, "LIB", "TB", "maestro")


def test_a_modified_marker_does_not_hide_the_view() -> None:
    assert _title_names("ADE Assembler Editing: LIB TB maestro*", "LIB", "TB", "maestro")
