"""Public-facing dashboard — Tyopaikka-tutka.

Browse employers near Finnish railway stations.
Deploy to Streamlit Community Cloud (streamlit.io/cloud) — reads
out/companies.csv which is committed to the repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

# Make the src-layout `apprscan` package importable on Streamlit Cloud, where
# only requirements.txt is installed (the package itself is not pip-installed).
_SRC = Path(__file__).parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from apprscan import transit

# Carto positron basemap: renders without a Mapbox token, so the map works on
# Streamlit Cloud and locally without any secret configured.
CARTO_BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

# Finnish labels for the last-mile access modes exposed by the commute model.
ACCESS_MODE_LABELS = {
    "walk": "🚶 Kävely",
    "bike": "🚲 Pyörä",
    "bus": "🚌 Bussi / liityntä",
}

# ---- Lead scoring -------------------------------------------------------
# Score 0-8 per service axis: TOI industry fit + company age (old = likely
# modernisation need) + has a website (digitally reachable).
_WEBSHOP = {
    "4754": 6, "4763": 6, "4764": 6, "4761": 6, "4762": 6, "4752": 6, "4741": 6,
    "4753": 5, "4759": 5, "4771": 5, "4772": 5, "4775": 5, "4776": 5, "4774": 5,
    "4779": 5, "4781": 5, "4782": 5, "4789": 5, "4791": 5,
    "474": 5, "475": 5, "476": 5, "477": 5, "478": 5, "479": 5,
    "47": 4, "472": 3, "471": 3, "473": 2, "46": 3, "45": 2,
    "10": 2, "11": 2, "13": 2, "14": 2, "20": 2, "22": 2, "23": 2, "24": 2,
    "25": 2, "26": 2, "27": 2, "28": 2, "29": 2, "31": 2, "32": 2,
    "33": 1, "49": 1, "52": 1,
}
_PIM = {
    "4684": 5, "4641": 5, "4642": 5, "4664": 5, "4663": 5, "4665": 4, "4649": 4,
    "4646": 4, "464": 3, "463": 3, "46": 2, "47": 2,
    "28": 3, "29": 3, "25": 3, "26": 3, "27": 3, "20": 2, "22": 2,
}
_DATA = {
    "52": 4, "49": 4, "64": 3, "65": 3, "33": 3, "71": 3, "86": 3,
    "28": 2, "25": 2, "26": 2, "46": 2, "85": 1, "35": 2,
}

LEAD_AXES = {"Verkkokauppa": "s_webshop", "PIM": "s_pim", "Data": "s_data"}
LEAD_SCORE_MAX = 8


def _pscore(toi, smap):
    code = str(toi).split(".")[0].strip() if pd.notna(toi) else ""
    return max((v for k, v in smap.items() if code.startswith(k)), default=0)


def add_lead_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Add lead scores (s_webshop/s_pim/s_data, 0-8) for sales prioritisation."""
    out = frame.copy()
    out["s_webshop"] = out["toi_code"].apply(lambda t: _pscore(t, _WEBSHOP))
    out["s_pim"] = out["toi_code"].apply(lambda t: _pscore(t, _PIM))
    out["s_data"] = out["toi_code"].apply(lambda t: _pscore(t, _DATA))
    legacy = (
        pd.to_datetime(out["registered"], errors="coerce").dt.year.fillna(2020) <= 2010
    ).astype(int)
    web = out["best_website"] if "best_website" in out.columns else out.get("website")
    has_web = web.notna().astype(int) if web is not None else 0
    for col in ("s_webshop", "s_pim", "s_data"):
        out[col] = out[col] + legacy + has_web
    return out

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Tyopaikka-tutka",
    page_icon="🔍",
    layout="wide",
)

DATA_PATH = Path(__file__).parent / "out" / "companies.csv"

# Coordinates come from apprscan.transit (single source of truth — the real
# railway stations), so map markers, distance, and the rail model all agree.
STATION_INFO = {
    key: {"label": label, "lat": transit.STATION_COORDS[key][0], "lon": transit.STATION_COORDS[key][1]}
    for key, label in [
        ("Lahti", "Lahti"),
        ("Kerava", "Kerava"),
        ("Savio", "Savio (Kerava Etelä)"),
        ("Pasila", "Helsinki Pasila"),
        ("Tikkurila", "Tikkurila (Vantaa)"),
    ]
}

INDUSTRY_LABELS = {
    "it": "💻 IT & ohjelmistot",
    "construction": "🏗️ Rakentaminen",
    "wholesale": "📦 Tukkukauppa",
    "marketing": "📣 Markkinointi & konsultointi",
    "health": "🏥 Terveys",
    "manufacturing": "🏭 Teollisuus & valmistus",
    "logistics": "🚚 Kuljetus & logistiikka",
    "finance": "💰 Rahoitus",
    "retail": "🛒 Vähittäiskauppa",
    "hospitality": "🍽️ Ravintola & majoitus",
    "education": "🎓 Koulutus",
    "engineering": "⚙️ Tekniikka & suunnittelu",
    "staffing": "👥 Henkilöstöpalvelut",
    "real_estate": "🏢 Kiinteistöala",
    "other": "📋 Muut",
}

INDUSTRY_COLORS = {
    "it": [0, 120, 215],
    "construction": [255, 140, 0],
    "wholesale": [0, 180, 100],
    "marketing": [180, 0, 180],
    "health": [220, 50, 50],
    "manufacturing": [80, 80, 80],
    "logistics": [200, 160, 0],
    "finance": [0, 160, 200],
    "retail": [255, 80, 120],
    "hospitality": [255, 120, 0],
    "education": [100, 60, 200],
    "engineering": [0, 140, 140],
    "staffing": [160, 80, 0],
    "real_estate": [120, 120, 40],
    "other": [160, 160, 160],
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data(_mtime: float) -> pd.DataFrame:
    # _mtime is part of the cache key, so editing out/companies.csv invalidates
    # the cache and the app reloads the fresh data instead of stale columns.
    df = pd.read_csv(DATA_PATH, encoding="utf-8-sig")
    df["distance_km"] = df["distance_km"].round(2)
    # Effective distance shown/used everywhere: walking road distance when
    # available (more honest), falling back to straight-line.
    if "road_distance_km" in df.columns:
        df["dist_km"] = (
            pd.to_numeric(df["road_distance_km"], errors="coerce").round(2).fillna(df["distance_km"])
        )
    else:
        df["dist_km"] = df["distance_km"]
    df["registered"] = pd.to_numeric(
        df["registered"].astype(str).str[:4], errors="coerce"
    )
    # Merge PRH website + DDG-discovered website into one column
    if "found_website" in df.columns:
        df["best_website"] = df["website"].combine_first(df["found_website"])
    else:
        df["best_website"] = df["website"]
    df["color"] = df["industry"].map(lambda x: INDUSTRY_COLORS.get(x, [160, 160, 160]))
    return df


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🔍 Tyopaikka-tutka")
    st.caption("Etsi työnantajia asemasi läheltä")
    st.divider()

    df_raw = load_data(DATA_PATH.stat().st_mtime if DATA_PATH.exists() else 0.0)

    # Station selector
    st.subheader("📍 Asema / kaupunki")
    station_options = {
        k: v["label"]
        for k, v in STATION_INFO.items()
        if k in df_raw["nearest_station"].unique()
    }
    selected_keys = st.multiselect(
        "Valitse asemat",
        options=list(station_options.keys()),
        default=list(station_options.keys()),
        format_func=lambda k: station_options[k],
    )

    # Distance slider
    st.subheader("📏 Etäisyys asemalta")
    max_dist = st.slider(
        "Enintään (km)",
        min_value=0.5,
        max_value=5.0,
        value=4.0,
        step=0.5,
    )
    st.caption("⚠️ Etäisyys on kävelymatka kadulta asemalle (arvio; ei katuosoitteen tarkkuutta).")

    # Train commute from a home station
    st.subheader("🚆 Työmatka junalla")
    origin_station = st.selectbox(
        "Mistä matkustat",
        options=sorted(transit.STATION_COORDS.keys()),
        index=sorted(transit.STATION_COORDS.keys()).index(transit.DEFAULT_ORIGIN),
        help="Junamatkan lähtöasema. Työmatka = juna lähtöasemalta + viime kilometri asemalta yritykselle.",
    )
    _access_keys = list(ACCESS_MODE_LABELS.keys())
    access_mode = st.selectbox(
        "Viime kilometri",
        options=_access_keys,
        index=_access_keys.index("bus"),
        format_func=lambda k: ACCESS_MODE_LABELS[k],
        help="Oletus: bussi/liityntä — kävely on epärealistinen useamman kilometrin matkalla.",
    )
    overhead_min = st.slider(
        "Odotus + liityntä (min)",
        min_value=0,
        max_value=30,
        value=10,
        step=1,
        help="Junan keskimääräinen odotusaika + matka laiturille. Lisätään työmatka-aikaan, "
        "jotta arvio ei ole nopeampi kuin todellinen matka.",
    )
    commute_limit_on = st.toggle("Rajaa työmatkan keston mukaan", value=False)
    max_commute = st.slider(
        "Enintään (min)",
        min_value=15,
        max_value=120,
        value=60,
        step=5,
        disabled=not commute_limit_on,
    )

    # Industry filter
    st.subheader("🏭 Toimiala")
    available_industries = sorted(df_raw["industry"].dropna().unique())
    industry_options = {k: INDUSTRY_LABELS.get(k, k) for k in available_industries}
    selected_industries = st.multiselect(
        "Valitse toimialat",
        options=list(industry_options.keys()),
        default=list(industry_options.keys()),
        format_func=lambda k: industry_options[k],
    )

    # Website toggle
    only_with_website = st.toggle("Vain yritykset joilla on verkkosivut", value=False)
    only_live = st.toggle(
        "Vain toimivat sivut",
        value=False,
        help="Näytä vain yritykset joiden verkkosivu vastaa ja näyttää oikealta "
        "(ei kuollut tai parkkeerattu) — karkea merkki siitä että yritys on aktiivinen.",
    )
    only_hiring = st.toggle(
        "Vain rekrytoivat (AI)",
        value=False,
        help="Näytä vain yritykset joiden sivulla AI-analyysi havaitsi "
        "rekrytointisignaalin (vain analysoiduille yrityksille).",
    )

    # Registration year
    min_year, max_year = int(df_raw["registered"].min()), int(
        df_raw["registered"].max()
    )
    reg_range = st.slider(
        "Rekisteröintivuosi",
        min_value=min_year,
        max_value=max_year,
        value=(min_year, max_year),
    )

    st.divider()
    st.caption("Lähde: PRH avoin yritysrekisteri · Päivitetty huhtikuu 2026")


# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
df = df_raw.copy()

if selected_keys:
    df = df[df["nearest_station"].isin(selected_keys)]
else:
    df = df.iloc[:0]  # empty if nothing selected

df = df[df["dist_km"] <= max_dist]
df = df[df["industry"].isin(selected_industries)]
df = df[df["registered"].between(reg_range[0], reg_range[1], inclusive="both")]

if only_with_website:
    df = df[df["best_website"].notna()]
if only_live and "website_status" in df.columns:
    df = df[df["website_status"] == "live"]
if only_hiring and "llm_is_hiring" in df.columns:
    df = df[df["llm_is_hiring"].astype(str).str.lower().isin(["true", "1", "yes"])]

# Train commute from the chosen origin: rail time + last-mile (walking road
# distance, dist_km) + a fixed wait/access overhead so the estimate isn't faster
# than the real journey.
_rail = transit.rail_minutes_from(origin_station)
df["commute_min"] = [
    transit.commute_minutes(
        station, dist, mode=access_mode, rail_minutes=_rail, overhead_min=overhead_min
    )
    for station, dist in zip(df["nearest_station"], df["dist_km"])
]
if commute_limit_on:
    df = df[df["commute_min"].notna() & (df["commute_min"] <= max_commute)]

# Lead scores (s_webshop/s_pim/s_data) for the map and the Liidit tab.
df = add_lead_scores(df)

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------
st.title("Tyopaikka-tutka 🔍")
st.subheader("Työnantajat asemasi lähialueella")

if df.empty:
    st.warning("Ei yrityksiä valituilla hakuehdoilla. Laajenna hakuasi.")
    st.stop()

# Metric cards
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Yrityksiä yhteensä", len(df))
if "website_status" in df.columns:
    _live = int((df["website_status"] == "live").sum())
    col2.metric(
        "Toimivia sivuja",
        _live,
        help="Verkkosivu vastaa ja näyttää oikealta (ei kuollut/parkkeerattu).",
    )
else:
    col2.metric("Joilla verkkosivut", int(df["best_website"].notna().sum()))
col3.metric("Eri toimialoja", df["industry"].nunique())
col4.metric("Alueita", df["nearest_station"].nunique())
_fastest = df["commute_min"].min()
col5.metric(
    "Nopein työmatka",
    f"{_fastest:.0f} min" if pd.notna(_fastest) else "–",
    help=f"Junalla asemalta {origin_station}, sis. viime kilometrin.",
)

st.divider()

# ---- Map ----------------------------------------------------------------
tab_map, tab_reach, tab_table, tab_stats, tab_leads = st.tabs(
    ["🗺️ Kartta", "🚆 Junasaavutettavuus", "📋 Yritykset", "📊 Tilastot", "🎯 Liidit"]
)

with tab_map:
    valid_coords = df.dropna(subset=["lat", "lon"]).copy()
    if valid_coords.empty:
        st.info("Ei koordinaatteja saatavilla valituille yrityksille.")
    else:
        # The map is filled from lead scoring: points are coloured and sized by
        # their lead score for the chosen axis, browsable in pages and sortable
        # by city (station). With the station filter this gives e.g. "top 100
        # leads of Kerava, next 100, ...".
        c1, c2, c3 = st.columns(3)
        axis_label = c1.selectbox("Liidi-akseli", list(LEAD_AXES.keys()))
        axis_col = LEAD_AXES[axis_label]
        sort_choice = c2.selectbox(
            "Järjestys", ["Liidipisteet", "Kaupunki (asema)", "Lähin asemaa"]
        )
        page_size_label = c3.selectbox(
            "Näytä kerralla", ["100", "250", "500", "1000", "Kaikki"], index=0
        )

        if sort_choice == "Kaupunki (asema)":
            valid_coords = valid_coords.sort_values(
                ["nearest_station", axis_col], ascending=[True, False], na_position="last"
            )
        elif sort_choice == "Lähin asemaa":
            valid_coords = valid_coords.sort_values("dist_km", na_position="last")
        else:
            valid_coords = valid_coords.sort_values(
                [axis_col, "commute_min"], ascending=[False, True], na_position="last"
            )

        total = len(valid_coords)
        page_size = total if page_size_label == "Kaikki" else int(page_size_label)
        n_pages = max(1, (total + page_size - 1) // page_size)
        page = 1
        if n_pages > 1:
            page = st.number_input("Sivu", min_value=1, max_value=n_pages, value=1, step=1)
        lo = (int(page) - 1) * page_size
        hi = min(lo + page_size, total)
        page_df = valid_coords.iloc[lo:hi].copy()
        st.caption(
            f"Näytetään {lo + 1}–{hi} / {total} yritystä · väri & koko = liidipisteet ({axis_label})"
        )

        # Many companies geocode to the same street point, so a page of 100 can
        # collapse to a handful of visible dots. Spread each point
        # deterministically (~±180 m) around its street so every lead shows.
        _h = pd.util.hash_pandas_object(
            page_df["business_id"].astype(str), index=False
        ).to_numpy()
        page_df["lat"] = page_df["lat"].astype(float) + ((_h % 1000) / 1000.0 - 0.5) * 0.0032
        page_df["lon"] = page_df["lon"].astype(float) + (((_h // 1000) % 1000) / 1000.0 - 0.5) * 0.0064

        page_df["commute_disp"] = page_df["commute_min"].map(
            lambda v: f"{v:.0f} min" if pd.notna(v) else "–"
        )
        page_df["lead_score"] = page_df[axis_col]

        def _lead_color(s):
            t = max(0.0, min(1.0, (float(s) if pd.notna(s) else 0) / LEAD_SCORE_MAX))
            return [int(70 + 170 * t), int(170 - 110 * t), 70, 200]

        page_df["color"] = page_df["lead_score"].map(_lead_color)
        page_df["radius"] = page_df["lead_score"].map(
            lambda s: 50 + (float(s) if pd.notna(s) else 0) * 20
        )

        # What the LLM wrote about the site (+ hiring/shop flags), for the tooltip.
        def _ai_note(row):
            sells, desc = row.get("llm_sells"), row.get("llm_description")
            text = sells if (isinstance(sells, str) and sells.strip()) else desc
            if not (isinstance(text, str) and text.strip()):
                return ""
            flags = []
            if str(row.get("llm_is_hiring")).lower() in ("true", "1", "yes"):
                flags.append("📢 rekrytoi")
            if str(row.get("llm_has_shop")).lower() in ("true", "1", "yes"):
                flags.append("🛒 verkkokauppa")
            prefix = (" · ".join(flags) + " · ") if flags else ""
            return (prefix + text.strip())[:170]

        if "llm_description" in page_df.columns:
            page_df["ai_note"] = page_df.apply(_ai_note, axis=1)
        else:
            page_df["ai_note"] = ""

        scatter = pdk.Layer(
            "ScatterplotLayer",
            data=page_df[
                ["lat", "lon", "name", "nearest_station", "lead_score", "industry",
                 "commute_disp", "ai_note", "best_website", "color", "radius"]
            ].copy(),
            get_position=["lon", "lat"],
            get_fill_color="color",
            get_radius="radius",
            pickable=True,
            opacity=0.8,
        )
        # Station markers carry the same tooltip keys so hovering them shows the
        # station name rather than a literal "{name}".
        station_data = [
            {
                "lat": v["lat"], "lon": v["lon"], "name": f"🚉 {v['label']}",
                "nearest_station": k, "lead_score": "", "industry": "Asema",
                "commute_disp": "", "ai_note": "", "best_website": "",
            }
            for k, v in STATION_INFO.items()
            if k in selected_keys
        ]
        station_layer = pdk.Layer(
            "ScatterplotLayer",
            data=station_data,
            get_position=["lon", "lat"],
            get_fill_color=[255, 30, 30, 220],
            get_radius=220,
            pickable=True,
        )
        # Auto-fit the view to the points actually shown.
        try:
            view = pdk.data_utils.compute_view(
                page_df[["lon", "lat"]].astype(float).values.tolist()
            )
            view.pitch = 0
        except Exception:
            view = pdk.ViewState(
                latitude=page_df["lat"].astype(float).mean(),
                longitude=page_df["lon"].astype(float).mean(),
                zoom=10,
                pitch=0,
            )
        chart = pdk.Deck(
            layers=[scatter, station_layer],
            initial_view_state=view,
            tooltip={
                "text": "{name}\nKaupunki: {nearest_station}\nLiidipisteet: {lead_score}\nToimiala: {industry}\nTyömatka: {commute_disp}\n{ai_note}\n{best_website}"
            },
            map_style=CARTO_BASEMAP,
        )
        st.pydeck_chart(chart)
        st.caption(
            "🔴 Asemat · pisteet = yritykset (hajautettu ~±180 m kadun ympärille näkyvyyden vuoksi) "
            "· vihreä→punainen = matalat→korkeat liidipisteet"
        )

# ---- Train reach (isochrone) -------------------------------------------
with tab_reach:
    st.subheader(f"🚆 Kuinka kauas pääset asemalta {origin_station}")
    st.caption(
        f"Aikabudjetin sisällä juna­matkalla saavutettavat asemat ({ACCESS_MODE_LABELS[access_mode]} "
        "viime kilometrillä). Varjostettu alue on karkea arvio saavutettavuudesta — "
        "offline-malli ilman aikatauluja."
    )
    reach_budget = st.slider(
        "Aikabudjetti (min)", min_value=15, max_value=120, value=60, step=5, key="reach_budget"
    )
    reach = transit.reachable_stations(
        float(reach_budget), origin=origin_station, mode=access_mode
    )
    if not reach:
        st.info("Ei saavutettavia asemia tällä budjetilla.")
    else:
        o_lat, o_lon = transit.STATION_COORDS[origin_station]
        max_rail = max((r.rail_minutes for r in reach), default=1.0) or 1.0
        disk_rows = []
        for r in reach:
            t = min(1.0, r.rail_minutes / max_rail)
            disk_rows.append(
                {
                    "name": r.name,
                    "lat": r.lat,
                    "lon": r.lon,
                    "rail_minutes": round(r.rail_minutes, 1),
                    "reach_km": round(r.reach_km, 2),
                    "radius_m": r.reach_km * 1000.0,
                    "color": [int(255 * t), int(180 * (1 - t)) + 40, 60, 70],
                }
            )
        disk_df = pd.DataFrame(disk_rows)

        # Companies shaded by whether they fall inside the budget.
        comp = df.dropna(subset=["lat", "lon"]).copy()
        comp["in_reach"] = comp["commute_min"].notna() & (comp["commute_min"] <= reach_budget)
        comp["pt_color"] = comp["in_reach"].map(
            lambda ok: [0, 170, 90, 170] if ok else [150, 150, 150, 70]
        )

        disk_layer = pdk.Layer(
            "ScatterplotLayer",
            data=disk_df,
            get_position=["lon", "lat"],
            get_radius="radius_m",
            get_fill_color="color",
            stroked=True,
            get_line_color=[80, 80, 80, 120],
            line_width_min_pixels=1,
            pickable=True,
        )
        company_layer = pdk.Layer(
            "ScatterplotLayer",
            data=comp[["lat", "lon", "name", "pt_color"]],
            get_position=["lon", "lat"],
            get_fill_color="pt_color",
            get_radius=70,
            pickable=True,
        )
        origin_layer = pdk.Layer(
            "ScatterplotLayer",
            data=pd.DataFrame([{"name": origin_station, "lat": o_lat, "lon": o_lon}]),
            get_position=["lon", "lat"],
            get_fill_color=[0, 90, 255, 230],
            get_radius=600,
            pickable=True,
        )
        reach_view = pdk.ViewState(latitude=o_lat, longitude=o_lon, zoom=8, pitch=0)
        st.pydeck_chart(
            pdk.Deck(
                layers=[disk_layer, company_layer, origin_layer],
                initial_view_state=reach_view,
                tooltip={"text": "{name}"},
                map_style=CARTO_BASEMAP,
            )
        )
        in_reach_n = int(comp["in_reach"].sum())
        st.caption(
            f"🔵 Lähtöasema {origin_station} · 🟢 {in_reach_n} yritystä budjetin sisällä "
            f"({reach_budget} min) · {len(reach)} asemaa saavutettavissa junalla."
        )
        st.dataframe(
            disk_df[["name", "rail_minutes", "reach_km"]].rename(
                columns={"name": "Asema", "rail_minutes": "Junamatka (min)", "reach_km": "Viime km"}
            ),
            width="stretch",
            hide_index=True,
        )

# ---- Table --------------------------------------------------------------
with tab_table:
    # Name/address search runs over ALL companies (ignores the sidebar filters)
    # so a company is always findable; with no search the table reflects the
    # current filters as usual.
    search = st.text_input(
        "🔎 Hae yrityksen nimellä tai osoitteella (hakee kaikista yrityksistä)", ""
    )
    if search:
        base = df_raw.copy()
        mask = base["name"].astype(str).str.contains(search, case=False, na=False) | base[
            "address"
        ].astype(str).str.contains(search, case=False, na=False)
        source = base[mask].copy()
        # Always add commute_min (df_raw lacks it), even for an empty result set,
        # so the column selection below never KeyErrors. Last mile uses road
        # distance when available.
        source["commute_min"] = [
            transit.commute_minutes(
                s, d, mode=access_mode, rail_minutes=_rail, overhead_min=overhead_min
            )
            for s, d in zip(source["nearest_station"], source["dist_km"])
        ]
        if source.empty:
            st.warning("Ei hakutuloksia.")
        else:
            outside = int((~source["business_id"].isin(df["business_id"])).sum())
            if outside:
                st.info(
                    f"Haku kattaa kaikki yritykset — {outside}/{len(source)} osumaa on "
                    "nykyisten suodattimien ulkopuolella."
                )
    else:
        source = df

    extra_cols = [
        c
        for c in ["website_status", "llm_description", "llm_has_shop", "llm_is_hiring"]
        if c in source.columns
    ]
    display = source[
        [
            "name",
            "industry",
            "toi_description",
            "nearest_station",
            "dist_km",
            "commute_min",
            "address",
            "best_website",
            "registered",
        ]
        + extra_cols
    ].copy()
    display["commute_min"] = display["commute_min"].round(0).astype("Int64")
    base_cols = [
        "Yritys",
        "Toimiala",
        "TOI-kuvaus",
        "Asema",
        "Etäisyys (km)",
        "Työmatka (min)",
        "Osoite",
        "Verkkosivut",
        "Perustettu",
    ]
    rename_map = {
        "website_status": "Sivun tila",
        "llm_description": "AI-kuvaus",
        "llm_has_shop": "Verkkokauppa",
        "llm_is_hiring": "Rekrytoi",
    }
    display.columns = base_cols + [rename_map[c] for c in extra_cols]
    display["Toimiala"] = display["Toimiala"].map(lambda x: INDUSTRY_LABELS.get(x, x))
    display["Perustettu"] = display["Perustettu"].astype("Int64")

    st.dataframe(
        display.reset_index(drop=True),
        width="stretch",
        column_config={
            "Verkkosivut": st.column_config.LinkColumn("Verkkosivut"),
            "Etäisyys (km)": st.column_config.NumberColumn(format="%.2f km"),
        },
        height=500,
    )

    # Download
    csv_bytes = display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        "⬇️ Lataa CSV",
        data=csv_bytes,
        file_name="tyonantajat.csv",
        mime="text/csv",
    )

# ---- Leads tab (scoring helpers are defined near the top of the file) ----
with tab_leads:
    st.subheader("🎯 Liidipisteytys — keiden kannattaa ensin soittaa?")
    st.caption(
        "Pisteet perustuvat TOI-toimialakoodiin, yrityksen ikään (vanha = päivitystarve) "
        "ja verkkosivujen olemassaoloon (digitaalisesti valmis). "
        "Valitse kategoria joka kiinnostaa sinua eniten."
    )

    scored = df.copy()  # lead scores (s_webshop/s_pim/s_data) already computed above

    lead_axis = st.radio(
        "Palvelutyyppi",
        options=["Verkkokauppa / webshop", "PIM / tuotekataloogi", "Data-analyysi"],
        horizontal=True,
    )
    axis_col = {
        "Verkkokauppa / webshop": "s_webshop",
        "PIM / tuotekataloogi": "s_pim",
        "Data-analyysi": "s_data",
    }[lead_axis]

    n_leads = st.slider("Näytä top-N", 5, 30, 10)
    top = scored.sort_values([axis_col, "commute_min"], ascending=[False, True]).head(
        n_leads
    )

    lead_display = top[
        [
            "name",
            "toi_description",
            "nearest_station",
            "dist_km",
            "commute_min",
            "best_website",
            "registered",
            axis_col,
        ]
        + [
            c
            for c in ["llm_description", "llm_has_shop", "llm_is_hiring"]
            if c in top.columns
        ]
    ].copy()
    lead_display["commute_min"] = lead_display["commute_min"].round(0).astype("Int64")
    base_lead_cols = [
        "Yritys",
        "Toimiala (tarkennettu)",
        "Asema",
        "Etäisyys (km)",
        "Työmatka (min)",
        "Verkkosivut",
        "Perustettu",
        "Pisteet",
    ]
    llm_lead_rename = {
        "llm_description": "AI-kuvaus",
        "llm_has_shop": "Verkkokauppa",
        "llm_is_hiring": "Rekrytoi",
    }
    lead_display.columns = base_lead_cols + [
        llm_lead_rename[c] for c in llm_lead_rename if c in top.columns
    ]
    lead_display["Perustettu"] = pd.to_numeric(
        lead_display["Perustettu"], errors="coerce"
    ).astype("Int64")

    st.dataframe(
        lead_display.reset_index(drop=True),
        width="stretch",
        column_config={
            "Verkkosivut": st.column_config.LinkColumn("Verkkosivut"),
            "Etäisyys (km)": st.column_config.NumberColumn(format="%.2f km"),
            "Pisteet": st.column_config.ProgressColumn(
                "Pisteet", min_value=0, max_value=8
            ),
        },
        height=420,
    )

    csv_leads = lead_display.to_csv(index=False, encoding="utf-8-sig").encode(
        "utf-8-sig"
    )
    st.download_button(
        "⬇️ Lataa liidit CSV", data=csv_leads, file_name="liidit.csv", mime="text/csv"
    )

# ---- Stats --------------------------------------------------------------
with tab_stats:
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Toimialajakauma")
        industry_counts = (
            df["industry"]
            .map(lambda x: INDUSTRY_LABELS.get(x, x))
            .value_counts()
            .reset_index()
        )
        industry_counts.columns = ["Toimiala", "Yrityksiä"]
        st.bar_chart(industry_counts.set_index("Toimiala"))

    with col_b:
        st.subheader("Yrityksiä alueittain")
        area_counts = df["nearest_station"].value_counts().reset_index()
        area_counts.columns = ["Alue", "Yrityksiä"]
        area_counts["Alue"] = area_counts["Alue"].map(
            lambda k: STATION_INFO.get(k, {}).get("label", k)
        )
        st.bar_chart(area_counts.set_index("Alue"))

    st.subheader("Rekisteröintivuosi")
    reg_counts = df["registered"].value_counts().sort_index()
    st.bar_chart(reg_counts)
