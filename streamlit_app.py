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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Tyopaikka-tutka",
    page_icon="🔍",
    layout="wide",
)

DATA_PATH = Path(__file__).parent / "out" / "companies.csv"

STATION_INFO = {
    "Lahti": {"label": "Lahti", "lat": 60.9836, "lon": 25.6577},
    "Kerava": {"label": "Kerava", "lat": 60.4050, "lon": 25.1022},
    "Savio": {"label": "Savio (Kerava Etelä)", "lat": 60.3822, "lon": 25.1021},
    "Pasila": {"label": "Helsinki Pasila", "lat": 60.1986, "lon": 24.9342},
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
def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, encoding="utf-8-sig")
    df["distance_km"] = df["distance_km"].round(2)
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

    df_raw = load_data()

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
    st.caption("⚠️ Etäisyys on arvio kadun sijainnin perusteella (ei katuosoitteen tarkkuutta).")

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

df = df[df["distance_km"] <= max_dist]
df = df[df["industry"].isin(selected_industries)]
df = df[df["registered"].between(reg_range[0], reg_range[1], inclusive="both")]

if only_with_website:
    df = df[df["best_website"].notna()]

# Train commute from the chosen origin: rail time to the company's station plus
# the last-mile leg. Computed live so the committed CSV needs no extra column.
_rail = transit.rail_minutes_from(origin_station)
df["commute_min"] = [
    transit.commute_minutes(station, dist, mode=access_mode, rail_minutes=_rail)
    for station, dist in zip(df["nearest_station"], df["distance_km"])
]
if commute_limit_on:
    df = df[df["commute_min"].notna() & (df["commute_min"] <= max_commute)]

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
col2.metric("Joilla verkkosivut", df["best_website"].notna().sum())
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
        valid_coords["commute_disp"] = valid_coords["commute_min"].map(
            lambda v: f"{v:.0f} min" if pd.notna(v) else "–"
        )
        # Company scatter layer
        scatter = pdk.Layer(
            "ScatterplotLayer",
            data=valid_coords[
                [
                    "lat",
                    "lon",
                    "name",
                    "industry",
                    "distance_km",
                    "commute_disp",
                    "best_website",
                    "color",
                ]
            ].copy(),
            get_position=["lon", "lat"],
            get_color="color",
            get_radius=80,
            pickable=True,
            opacity=0.75,
        )
        # Station marker layer
        station_data = [
            {"lat": v["lat"], "lon": v["lon"], "label": v["label"]}
            for k, v in STATION_INFO.items()
            if k in selected_keys
        ]
        station_layer = pdk.Layer(
            "ScatterplotLayer",
            data=station_data,
            get_position=["lon", "lat"],
            get_color=[255, 30, 30, 200],
            get_radius=200,
            pickable=True,
        )
        # Center map on selection
        center_lat = valid_coords["lat"].mean()
        center_lon = valid_coords["lon"].mean()
        zoom = 12 if len(selected_keys) == 1 else 9

        view = pdk.ViewState(
            latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0
        )
        chart = pdk.Deck(
            layers=[scatter, station_layer],
            initial_view_state=view,
            tooltip={
                "text": "{name}\nToimiala: {industry}\nEtäisyys: {distance_km} km\nTyömatka: {commute_disp}\n{best_website}"
            },
            map_style=CARTO_BASEMAP,
        )
        st.pydeck_chart(chart)
        st.caption("🔴 Asemat  · muut pisteet = yritykset (väri toimialan mukaan)")

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
    # Build a display-friendly frame
    llm_cols = [
        c
        for c in ["llm_description", "llm_has_shop", "llm_is_hiring"]
        if c in df.columns
    ]
    display = df[
        [
            "name",
            "industry",
            "toi_description",
            "nearest_station",
            "distance_km",
            "commute_min",
            "address",
            "best_website",
            "registered",
        ]
        + llm_cols
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
        "llm_description": "AI-kuvaus",
        "llm_has_shop": "Verkkokauppa",
        "llm_is_hiring": "Rekrytoi",
    }
    display.columns = base_cols + [rename_map[c] for c in llm_cols]
    display["Toimiala"] = display["Toimiala"].map(lambda x: INDUSTRY_LABELS.get(x, x))
    display["Perustettu"] = display["Perustettu"].astype("Int64")

    # Search box
    search = st.text_input("🔎 Hae yrityksen nimellä tai osoitteella", "")
    if search:
        mask = display["Yritys"].str.contains(search, case=False, na=False) | display[
            "Osoite"
        ].str.contains(search, case=False, na=False)
        display = display[mask]

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

# ---- Leads -------------------------------------------------------------
# Lead scoring — runs on the already-filtered df
# Specialty retail (games, sports, hobbies, books, electronics, fashion, optics) → highest
# General retail (grocery, hypermarket, food specialists) → lower; petrol/kiosk → lowest
_WEBSHOP = {
    "4754": 6,
    "4763": 6,
    "4764": 6,
    "4761": 6,
    "4762": 6,
    "4752": 6,
    "4741": 6,  # ICT,games/toys,sports,books,music,hardware,optics
    "4753": 5,
    "4759": 5,
    "4771": 5,
    "4772": 5,
    "4775": 5,
    "4776": 5,
    "4774": 5,  # carpets,other home,clothing,footwear,cosmetics,flowers/pets,eyewear
    "4779": 5,
    "4781": 5,
    "4782": 5,
    "4789": 5,
    "4791": 5,  # 2nd hand, market stalls, specialty
    "474": 5,
    "475": 5,
    "476": 5,
    "477": 5,
    "478": 5,
    "479": 5,  # other specialty retail subcategories
    "47": 4,  # general catch-all retail
    "472": 3,
    "471": 3,  # food/grocery specialist and hypermarket
    "473": 2,  # petrol stations
    "46": 3,
    "45": 2,
    "10": 2,
    "11": 2,
    "13": 2,
    "14": 2,
    "20": 2,
    "22": 2,
    "23": 2,
    "24": 2,
    "25": 2,
    "26": 2,
    "27": 2,
    "28": 2,
    "29": 2,
    "31": 2,
    "32": 2,
    "33": 1,
    "49": 1,
    "52": 1,
}
_PIM = {
    "4684": 5,
    "4641": 5,
    "4642": 5,
    "4664": 5,
    "4663": 5,
    "4665": 4,
    "4649": 4,
    "4646": 4,
    "464": 3,
    "463": 3,
    "46": 2,
    "47": 2,
    "28": 3,
    "29": 3,
    "25": 3,
    "26": 3,
    "27": 3,
    "20": 2,
    "22": 2,
}
_DATA = {
    "52": 4,
    "49": 4,
    "64": 3,
    "65": 3,
    "33": 3,
    "71": 3,
    "86": 3,
    "28": 2,
    "25": 2,
    "26": 2,
    "46": 2,
    "85": 1,
    "35": 2,
}


def _pscore(toi, smap):
    code = str(toi).split(".")[0].strip() if pd.notna(toi) else ""
    return max((v for k, v in smap.items() if code.startswith(k)), default=0)


with tab_leads:
    st.subheader("🎯 Liidipisteytys — keiden kannattaa ensin soittaa?")
    st.caption(
        "Pisteet perustuvat TOI-toimialakoodiin, yrityksen ikään (vanha = päivitystarve) "
        "ja verkkosivujen olemassaoloon (digitaalisesti valmis). "
        "Valitse kategoria joka kiinnostaa sinua eniten."
    )

    scored = df.copy()
    scored["s_webshop"] = scored["toi_code"].apply(lambda t: _pscore(t, _WEBSHOP))
    scored["s_pim"] = scored["toi_code"].apply(lambda t: _pscore(t, _PIM))
    scored["s_data"] = scored["toi_code"].apply(lambda t: _pscore(t, _DATA))
    legacy = (
        pd.to_datetime(scored["registered"], errors="coerce").dt.year.fillna(2020)
        <= 2010
    ).astype(int)
    has_web = scored["best_website"].notna().astype(int)
    for col in ["s_webshop", "s_pim", "s_data"]:
        scored[col] += legacy + has_web

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
            "distance_km",
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
