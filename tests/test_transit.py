"""Calibration and behaviour tests for the offline rail-commute model.

The minute ranges below are the model's contract: they keep the synthesised
travel times anchored to real Mäntsälä journeys so calibration can't silently
drift when speeds or dwell are tweaked.
"""

import math

import pytest

from apprscan import transit


def test_graph_is_connected_and_undirected():
    adj = transit.build_graph()
    # Every embedded station appears as a node.
    assert set(adj) == set(transit.STATION_COORDS)
    # Edges are symmetric.
    for node, edges in adj.items():
        for nbr, w in edges:
            assert any(back == node and math.isclose(bw, w) for back, bw in adj[nbr])


def test_rail_minutes_reaches_every_station():
    rail = transit.rail_minutes_from("Mäntsälä")
    assert set(rail) == set(transit.STATION_COORDS)
    assert rail["Mäntsälä"] == 0.0


def test_mantsala_to_helsinki_realistic():
    rail = transit.rail_minutes_from("Mäntsälä")
    # Real Z-train commute is ~45-50 min; allow a calibrated band.
    assert 38.0 <= rail["Helsinki"] <= 52.0


def test_mantsala_to_lahti_realistic():
    rail = transit.rail_minutes_from("Mäntsälä")
    # Mäntsälä -> Lahti on the direct line is ~25 min.
    assert 20.0 <= rail["Lahti"] <= 32.0


def test_lahti_closer_than_helsinki_from_mantsala():
    rail = transit.rail_minutes_from("Mäntsälä")
    assert rail["Lahti"] < rail["Helsinki"]


def test_dashboard_stations_are_known_and_reachable():
    # The stations present in out/companies.csv must all resolve in the model,
    # otherwise dashboard commute times would silently be blank.
    rail = transit.rail_minutes_from("Mäntsälä")
    for station in ("Kerava", "Lahti", "Pasila", "Savio"):
        assert station in transit.STATION_COORDS
        assert rail[station] < 45.0


def test_savio_just_past_kerava():
    rail = transit.rail_minutes_from("Mäntsälä")
    # Savio sits one stop south of Kerava, so slightly farther by train.
    assert rail["Kerava"] < rail["Savio"] < rail["Kerava"] + 6.0


def test_unknown_origin_raises():
    with pytest.raises(KeyError):
        transit.rail_minutes_from("Atlantis")


def test_access_minutes_modes_ordered():
    # Walking takes longer than biking, which takes longer than the bus.
    walk = transit.access_minutes(3.0, "walk")
    bike = transit.access_minutes(3.0, "bike")
    bus = transit.access_minutes(3.0, "bus")
    assert walk > bike > bus
    assert math.isclose(walk, 3.0 / 4.5 * 60.0)


def test_commute_adds_rail_and_access():
    rail = transit.rail_minutes_from("Mäntsälä")
    total = transit.commute_minutes("Lahti", 1.5, mode="walk", rail_minutes=rail)
    assert total is not None
    assert math.isclose(total, rail["Lahti"] + transit.access_minutes(1.5, "walk"))


def test_commute_overhead_is_added():
    rail = transit.rail_minutes_from("Mäntsälä")
    base = transit.commute_minutes("Lahti", 1.0, mode="bus", rail_minutes=rail)
    with_oh = transit.commute_minutes("Lahti", 1.0, mode="bus", rail_minutes=rail, overhead_min=12)
    assert math.isclose(with_oh - base, 12.0)


def test_commute_unknown_station_returns_none():
    assert transit.commute_minutes("Nowhere", 1.0) is None


def test_commute_missing_distance_returns_none():
    assert transit.commute_minutes("Lahti", None) is None


def test_reachable_excludes_stations_beyond_budget():
    reach = transit.reachable_stations(30.0, origin="Mäntsälä")
    names = {r.name for r in reach}
    assert "Mäntsälä" in names
    assert "Lahti" in names  # ~25 min by rail
    assert "Helsinki" not in names  # ~45 min, beyond a 30 min budget


def test_reachable_radius_shrinks_with_rail_time():
    reach = {r.name: r for r in transit.reachable_stations(60.0, origin="Mäntsälä", mode="bike")}
    # The origin keeps the whole leftover budget; a farther station gets less.
    assert reach["Mäntsälä"].reach_km > reach["Lahti"].reach_km
    # Origin reach matches the full budget at the chosen access speed.
    assert math.isclose(reach["Mäntsälä"].reach_km, 60.0 / 60.0 * transit.ACCESS_SPEEDS_KMH["bike"])
