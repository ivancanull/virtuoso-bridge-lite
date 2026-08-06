from __future__ import annotations

import pytest

from virtuoso_bridge.virtuoso import schematic as schematic_api
from virtuoso_bridge.virtuoso.schematic.ops import (
    schematic_create_net_stub,
    schematic_create_net_expression,
    schematic_label_instance_term,
    schematic_rename_net,
    schematic_rename_port,
    schematic_set_netset_property,
)


def test_schematic_rename_builders_are_public() -> None:
    assert schematic_api.schematic_rename_net is schematic_rename_net
    assert schematic_api.schematic_rename_port is schematic_rename_port
    assert "schematic_rename_net" in schematic_api.__all__
    assert "schematic_rename_port" in schematic_api.__all__


def test_schematic_rename_net_renames_only_the_net() -> None:
    skill = schematic_rename_net("NX", "CASCODE_NODE")

    assert 'rbOldNet = dbFindNetByName(cv "NX")' in skill
    assert 'dbFindNetByName(cv "CASCODE_NODE")' in skill
    assert 'dbRenameNet(rbOldNet "CASCODE_NODE")' in skill
    assert "dbFindTermByName" not in skill
    assert "~>name =" not in skill


def test_schematic_rename_port_renames_terminal_and_same_named_net() -> None:
    skill = schematic_rename_port("VOUT", "IOUT")

    assert 'rbOldTerm = dbFindTermByName(cv "VOUT")' in skill
    assert 'dbFindTermByName(cv "IOUT")' in skill
    assert "rbOldNet = rbOldTerm~>net" in skill
    assert 'rbOldNet~>name == "VOUT"' in skill
    assert 'dbFindNetByName(cv "IOUT")' in skill
    assert 'dbRenameNet(rbOldNet "IOUT")' in skill
    assert 'rbOldTerm~>name = "IOUT"' in skill


def test_schematic_rename_port_can_leave_attached_net_unchanged() -> None:
    skill = schematic_rename_port("VOUT", "IOUT", rename_attached_net=False)

    assert 'rbOldTerm = dbFindTermByName(cv "VOUT")' in skill
    assert 'rbOldTerm~>name = "IOUT"' in skill
    assert "dbFindNetByName" not in skill
    assert "dbRenameNet" not in skill


def test_schematic_rename_helpers_escape_names_and_cellview_expression() -> None:
    net_skill = schematic_rename_net('A"OLD', "B\\NEW", cv_expr="targetCv")
    port_skill = schematic_rename_port('P"OLD', "P\\NEW", cv_expr="targetCv")

    assert 'dbFindNetByName(targetCv "A\\"OLD")' in net_skill
    assert 'dbRenameNet(rbOldNet "B\\\\NEW")' in net_skill
    assert 'dbFindTermByName(targetCv "P\\"OLD")' in port_skill
    assert 'rbOldTerm~>name = "P\\\\NEW"' in port_skill


@pytest.mark.parametrize(
    ("old_name", "new_name", "message"),
    [
        ("", "NEW", "must be non-empty"),
        ("OLD", "", "must be non-empty"),
        ("SAME", "SAME", "must differ"),
    ],
)
def test_schematic_rename_helpers_reject_invalid_names(
    old_name: str,
    new_name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        schematic_rename_net(old_name, new_name)
    with pytest.raises(ValueError, match=message):
        schematic_rename_port(old_name, new_name)


def test_schematic_create_net_expression_attaches_expression_to_net_wire() -> None:
    skill = schematic_create_net_expression(
        "VDD",
        "[@vdd:%:vdd!]",
        1.25,
        -0.5,
        justification="centerLeft",
        rotation="R90",
        font_style="stick",
        height=0.0625,
    )

    assert 'x~>net && x~>net~>name == "VDD"' in skill
    assert 'unless(rbWire error("wire for net not found"))' in skill
    assert (
        'schCreateNetExpression(cv "[@vdd:%:vdd!]" rbWire '
        '\'(1.250 -0.500) "centerLeft" "R90" "stick" 0.0625)'
    ) in skill


def test_schematic_create_net_expression_accepts_custom_cellview_expr() -> None:
    skill = schematic_create_net_expression(
        "VSS",
        "[@vss:%:gnd!]",
        0,
        0,
        cv_expr="targetCv",
    )

    assert "targetCv~>shapes" in skill
    assert 'schCreateNetExpression(targetCv "[@vss:%:gnd!]" rbWire' in skill


def test_schematic_set_netset_property_writes_inherited_override() -> None:
    skill = schematic_set_netset_property("XI0", "vdd", "VDD")

    assert 'x~>name == "XI0"' in skill
    assert 'unless(rbInst error("instance not found"))' in skill
    assert 'dbReplaceProp(rbInst "vdd" "netSet" "VDD")' in skill


def test_schematic_set_netset_property_escapes_string_literals() -> None:
    skill = schematic_set_netset_property('XI"0', "bulk\\net", 'VDD"TOP')

    assert 'x~>name == "XI\\"0"' in skill
    assert 'dbReplaceProp(rbInst "bulk\\\\net" "netSet" "VDD\\"TOP")' in skill


def test_schematic_create_net_stub_draws_short_wire_and_label() -> None:
    skill = schematic_create_net_stub("IN", 0, 0, direction="right", length=0.5)

    assert 'schCreateWire(cv "route" "full" \'((0.000 0.000) (0.500 0.000)) 0 0 0 nil nil)' in skill
    assert 'schCreateWireLabel(cv nil \'(0.250 0.000) "IN" "centerCenter" "R0" "stick" 0.0625 nil)' in skill


def test_schematic_create_net_stub_auto_rotates_vertical_labels() -> None:
    skill = schematic_create_net_stub("VDD", 1, 2, direction="up", length=0.75)

    assert "'((1.000 2.000) (1.000 2.750))" in skill
    assert '\'(1.000 2.375) "VDD" "centerCenter" "R90"' in skill


def test_schematic_create_net_stub_escapes_label_text_and_overrides_rotation() -> None:
    skill = schematic_create_net_stub('A"NET\\1', 0, 0, direction="up", rotation="R0")

    assert '"A\\"NET\\\\1"' in skill
    assert '\'(0.000 0.250) "A\\"NET\\\\1" "centerCenter" "R0"' in skill


def test_schematic_create_net_stub_rejects_non_positive_length() -> None:
    with pytest.raises(ValueError, match="length must be positive"):
        schematic_create_net_stub("IN", 0, 0, length=0)


def test_schematic_create_net_stub_rejects_unknown_direction() -> None:
    with pytest.raises(ValueError, match="direction must be one of"):
        schematic_create_net_stub("IN", 0, 0, direction="diagonal")


def test_schematic_label_instance_term_keeps_unbound_label_by_default() -> None:
    skill = schematic_label_instance_term("M0", "D", "OUT")

    assert 'schCreateWire(cv "route" "full" list(rbCtr rbStubEnd) 0 0 0 nil nil)' in skill
    assert 'schCreateWireLabel(cv nil rbMid "OUT"' in skill
    assert "rbWireObj" not in skill


def test_schematic_label_instance_term_preserves_legacy_wire_cv_by_default() -> None:
    skill = schematic_label_instance_term("M0", "D", "OUT", cv_expr="targetCv")

    assert 'targetCv~>instances' in skill
    assert 'schCreateWire(cv "route" "full" list(rbCtr rbStubEnd) 0 0 0 nil nil)' in skill
    assert 'schCreateWireLabel(targetCv nil rbMid "OUT"' in skill
    assert 'schCreateWire(targetCv "route" "full"' not in skill


def test_schematic_label_instance_term_can_bind_label_to_created_wire() -> None:
    skill = schematic_label_instance_term("M0", "D", "OUT", bind_label_to_wire=True)

    assert 'rbWire = when(rbCtr && rbStubEnd schCreateWire(cv "route" "full" list(rbCtr rbStubEnd) 0 0 0 nil nil))' in skill
    assert "rbWireObj = if(listp(rbWire) car(rbWire) rbWire)" in skill
    assert "when(rbWireObj && rbMid" in skill
    assert 'schCreateWireLabel(cv rbWireObj rbMid "OUT"' in skill


def test_schematic_label_instance_term_bind_uses_custom_cellview_expr() -> None:
    skill = schematic_label_instance_term(
        "M0",
        "D",
        "OUT",
        cv_expr="targetCv",
        bind_label_to_wire=True,
    )

    assert 'targetCv~>instances' in skill
    assert 'rbWire = when(rbCtr && rbStubEnd schCreateWire(targetCv "route" "full"' in skill
    assert 'schCreateWireLabel(targetCv rbWireObj rbMid "OUT"' in skill
    assert 'schCreateWire(cv "route" "full"' not in skill
    assert 'schCreateWireLabel(cv ' not in skill
