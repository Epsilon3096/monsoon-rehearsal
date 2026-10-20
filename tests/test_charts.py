"""Schematic presentation controls, with no hydraulic-engine execution."""
from copy import deepcopy
from math import inf, nan, nextafter

import pytest

from monsoon.charts import TEAL, network_figure, node_spill_rows


@pytest.fixture
def case():
    return {"nodes": [
        {"id": "A", "kind": "junction", "label": "Upstream", "x": 0, "y": 1},
        {"id": "S", "kind": "storage", "label": "Detention", "x": 4, "y": 1},
        {"id": "O", "kind": "outfall", "label": "Receiving water", "x": 8, "y": 1}],
        "links": [{"id": "IN", "from_node": "A", "to_node": "S", "job_id": "J1"},
                  {"id": "OUT", "from_node": "S", "to_node": "O"}]}


def node_trace(fig):
    return next(trace for trace in fig.data if trace.mode == "markers+text")


def test_absolute_boundary_is_strict_and_missing_is_not_zero(case):
    rows = node_spill_rows(case, {"A": nextafter(.05, inf), "S": .05})
    assert [row["status"] for row in rows] == ["above_tolerance", "within_tolerance", "missing"]
    assert rows[0]["value_m3"] > rows[1]["value_m3"]
    assert rows[2]["value_m3"] is None
    assert rows[2]["value_label"] == "Unavailable"
    assert rows[2]["missing_reason"] == "not supplied"
    assert rows[0]["status_label"] == "Spill > 0.05 m³"


def test_change_uses_signed_values_and_one_sided_non_worsening_tolerance(case):
    rows = node_spill_rows(case, {"A": -.7, "S": .05, "O": .051}, "change")
    assert [row["status"] for row in rows] == ["within_tolerance", "within_tolerance", "above_tolerance"]
    assert rows[0]["value_m3"] == -.7
    assert rows[0]["value_label"] == "Δ -0.7 m³"
    assert rows[1]["value_label"] == "Δ +0.05 m³"
    assert rows[0]["status_label"] == "No increase > 0.05 m³"
    assert rows[2]["status_label"] == "Increase > 0.05 m³"


def test_unavailable_and_invalid_results_are_never_drawn_as_zero(case):
    for unavailable in (None, nan, inf, -inf, True, "0.0", -.1):
        rows = node_spill_rows(case, {"A": unavailable})
        assert rows[0]["value_m3"] is None
        assert rows[0]["status"] == "missing"
    zero = node_spill_rows(case, {"A": 0})[0]
    assert zero["value_m3"] == 0
    assert zero["value_label"] == "0 m³"
    assert zero["status"] == "within_tolerance"


def test_chart_encodes_status_without_color_and_keeps_storage_identity(case):
    fig = network_figure(case, spills={"A": .1, "S": .05})
    nodes = node_trace(fig)
    assert tuple(nodes.marker.symbol) == ("triangle-up", "circle", "x")
    assert nodes.marker.size[1] > nodes.marker.size[0]
    assert nodes.marker.line.width[1] > nodes.marker.line.width[0]
    assert "S (storage)" in nodes.text[1]
    assert "Unavailable" in nodes.text[2]
    assert "Spill > 0.05 m³" in nodes.hovertext[0]
    assert "Reason: not supplied" in nodes.hovertext[2]
    assert "Absolute node spill (m³)" in fig.layout.title.text
    assert [trace.name for trace in fig.data if trace.name] == [
        "Spill > 0.05 m³", "Spill ≤ 0.05 m³", "Value unavailable"]


def test_change_chart_title_legend_and_values_match_the_given_mode(case):
    fig = network_figure(case, spills={"A": -.1, "S": .07}, display_mode="change", epsilon_m3=.07)
    nodes = node_trace(fig)
    assert tuple(nodes.marker.symbol) == ("circle", "circle", "x")
    assert "Δ -0.1 m³" in nodes.hovertext[0]
    assert "Change vs. no additional work (Δ m³)" in fig.layout.title.text
    assert [trace.name for trace in fig.data if trace.name] == [
        "Increase > 0.07 m³", "No increase > 0.07 m³", "Value unavailable"]


def test_legacy_calls_restore_links_and_do_not_mutate_inputs(case):
    values, completed = {"A": .2, "S": 0}, ["J1"]
    original = deepcopy((case, values, completed))
    assert all(symbol == "x" for symbol in node_trace(network_figure(case)).marker.symbol)
    assert network_figure(case, completed).data[0].line.color == TEAL
    fig = network_figure(case, completed, values)
    assert fig.data[0].line.color == TEAL
    assert fig.data[0].line.width == 5
    assert fig.data[1].line.width == 3
    assert "Absolute node spill (m³)" in fig.layout.title.text
    assert (case, values, completed) == original
    assert fig.to_plotly_json()["data"]


@pytest.mark.parametrize("mode,tolerance", [("delta", .05), ("absolute", -.01),
                                          ("change", nan), ("absolute", inf),
                                          ("absolute", True)])
def test_invalid_display_contract_is_rejected(case, mode, tolerance):
    with pytest.raises(ValueError):
        network_figure(case, display_mode=mode, epsilon_m3=tolerance)
