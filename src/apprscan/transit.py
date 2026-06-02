"""Offline train-commute model centred on Mäntsälä.

A small, fully self-contained rail network: station coordinates and line
topology are embedded as module constants, so this works on Streamlit Cloud
with zero file or network IO. Segment travel times are *synthesised* from
geometry (great-circle distance / line speed + per-stop dwell) rather than read
from a timetable, then calibrated against a few known journeys (see
``tests/test_transit.py``).

The public surface is deliberately small so a real schedule-based backend
(e.g. Digitransit / OpenTripPlanner) could later replace the internals without
touching callers:

* :func:`rail_minutes_from` -- train-only minutes from an origin to every station
* :func:`commute_minutes`   -- door-to-door estimate (rail + last-mile access)
* :func:`reachable_stations`-- isochrone disks for a time budget
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .distance import haversine_km

DEFAULT_ORIGIN = "Mäntsälä"

# Last-mile access speeds (km/h) from the alighting station to the destination.
ACCESS_SPEEDS_KMH: Dict[str, float] = {
    "walk": 4.5,
    "bike": 15.0,
    "bus": 22.0,
}

# Dwell time added per intermediate stop (minutes). Accounts for braking,
# stopping and re-accelerating; folded into each edge.
DWELL_MIN = 0.7


@dataclass(frozen=True)
class Line:
    """An ordered run of stations sharing an effective line speed (km/h)."""

    name: str
    speed_kmh: float
    stations: Tuple[str, ...]


# Station coordinates (WGS84). Only the stops relevant to a Mäntsälä commute.
STATION_COORDS: Dict[str, Tuple[float, float]] = {
    "Helsinki": (60.1718, 24.9414),
    "Pasila": (60.1987, 24.9331),
    "Tikkurila": (60.2925, 25.0439),
    "Savio": (60.3822, 25.1021),
    "Kerava": (60.4036, 25.1040),
    "Järvenpää": (60.4733, 25.0903),
    "Hyvinkää": (60.6310, 24.8590),
    "Riihimäki": (60.7186, 24.7740),
    "Haarajoki": (60.5363, 25.1198),
    "Mäntsälä": (60.6113, 25.3186),
    "Henna": (60.7284, 25.5270),
    "Lahti": (60.9759, 25.6610),
    "Kouvola": (60.8664, 26.7045),
}

# Effective line speeds are calibrated, not nominal track speeds: the dense
# Helsinki–Kerava section is slow despite high track limits, while the Kerava–
# Lahti direct line (oikorata) is genuinely fast.
RAIL_LINES: Tuple[Line, ...] = (
    Line("Päärata (Helsinki–Kerava)", 72.0, ("Helsinki", "Pasila", "Tikkurila", "Savio", "Kerava")),
    Line("Päärata (Kerava–Riihimäki)", 90.0, ("Kerava", "Järvenpää", "Hyvinkää", "Riihimäki")),
    Line("Oikorata (Kerava–Lahti)", 120.0, ("Kerava", "Haarajoki", "Mäntsälä", "Henna", "Lahti")),
    Line("Lahti–Riihimäki", 95.0, ("Lahti", "Riihimäki")),
    Line("Lahti–Kouvola", 110.0, ("Lahti", "Kouvola")),
)


def _segment_minutes(a: str, b: str, speed_kmh: float) -> float:
    """Travel minutes between adjacent stations, including arrival dwell."""
    lat1, lon1 = STATION_COORDS[a]
    lat2, lon2 = STATION_COORDS[b]
    km = haversine_km(lat1, lon1, lat2, lon2)
    return km / speed_kmh * 60.0 + DWELL_MIN


def build_graph(
    lines: Tuple[Line, ...] = RAIL_LINES,
) -> Dict[str, List[Tuple[str, float]]]:
    """Undirected adjacency list {station: [(neighbour, minutes), ...]}.

    Stations shared between lines (e.g. Kerava, Lahti) merge into one node, so
    Dijkstra can route via whichever line is fastest.
    """
    adj: Dict[str, List[Tuple[str, float]]] = {name: [] for name in STATION_COORDS}
    for line in lines:
        for a, b in zip(line.stations, line.stations[1:]):
            minutes = _segment_minutes(a, b, line.speed_kmh)
            adj[a].append((b, minutes))
            adj[b].append((a, minutes))
    return adj


def rail_minutes_from(
    origin: str = DEFAULT_ORIGIN,
    lines: Tuple[Line, ...] = RAIL_LINES,
) -> Dict[str, float]:
    """Shortest train-only minutes from ``origin`` to every reachable station."""
    if origin not in STATION_COORDS:
        raise KeyError(f"Unknown origin station: {origin!r}")
    adj = build_graph(lines)
    best: Dict[str, float] = {origin: 0.0}
    heap: List[Tuple[float, str]] = [(0.0, origin)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > best.get(node, float("inf")):
            continue
        for nbr, w in adj[node]:
            nxt = cost + w
            if nxt < best.get(nbr, float("inf")):
                best[nbr] = nxt
                heapq.heappush(heap, (nxt, nbr))
    return best


def access_minutes(distance_km: float, mode: str = "walk") -> float:
    """Last-mile minutes from a station to a point ``distance_km`` away."""
    speed = ACCESS_SPEEDS_KMH.get(mode, ACCESS_SPEEDS_KMH["walk"])
    return float(distance_km) / speed * 60.0


def commute_minutes(
    nearest_station: str,
    distance_km: float,
    *,
    origin: str = DEFAULT_ORIGIN,
    mode: str = "walk",
    rail_minutes: Optional[Dict[str, float]] = None,
) -> Optional[float]:
    """Door-to-door estimate: rail time to the nearest station + last-mile.

    Returns ``None`` when the station is unknown to the network or the inputs
    are missing, so callers can leave the value blank rather than guess.
    """
    if not nearest_station or nearest_station not in STATION_COORDS:
        return None
    if distance_km is None:
        return None
    rail = rail_minutes if rail_minutes is not None else rail_minutes_from(origin)
    leg = rail.get(nearest_station)
    if leg is None:
        return None
    return leg + access_minutes(distance_km, mode)


@dataclass(frozen=True)
class ReachableStation:
    """A station inside the time budget and the disk it can still reach."""

    name: str
    lat: float
    lon: float
    rail_minutes: float
    reach_km: float


def reachable_stations(
    budget_min: float,
    *,
    origin: str = DEFAULT_ORIGIN,
    mode: str = "walk",
    lines: Tuple[Line, ...] = RAIL_LINES,
) -> List[ReachableStation]:
    """Isochrone as a union of disks: one per station reachable within budget.

    Each reachable station contributes a disk whose radius is the distance the
    remaining time budget buys at the chosen access speed. The union of these
    disks approximates the area reachable from ``origin`` within ``budget_min``.
    """
    speed = ACCESS_SPEEDS_KMH.get(mode, ACCESS_SPEEDS_KMH["walk"])
    rail = rail_minutes_from(origin, lines)
    out: List[ReachableStation] = []
    for name, minutes in rail.items():
        if minutes > budget_min:
            continue
        reach_km = max(0.0, (budget_min - minutes) / 60.0 * speed)
        lat, lon = STATION_COORDS[name]
        out.append(ReachableStation(name, lat, lon, minutes, reach_km))
    out.sort(key=lambda r: r.rail_minutes)
    return out
