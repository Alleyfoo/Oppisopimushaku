"""Public-facing dashboard — Tyopaikka-tutka.

Browse employers near Finnish railway stations.
Deploy to Streamlit Community Cloud (streamlit.io/cloud) — reads
out/companies.csv which is committed to the repo.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

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
    df["registered"] = pd.to_numeric(df["registered"].astype(str).str[:4], errors="coerce")
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
    station_options = {k: v["label"] for k, v in STATION_INFO.items() if k in df_raw["nearest_station"].unique()}
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
        max_value=2.0,
        value=1.5,
        step=0.1,
    )
    st.caption("⚠️ Etäisyys on arvio postinumeroalueen perusteella.")

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
    min_year, max_year = int(df_raw["registered"].min()), int(df_raw["registered"].max())
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

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------
st.title("Tyopaikka-tutka 🔍")
st.subheader("Työnantajat asemasi lähialueella")

if df.empty:
    st.warning("Ei yrityksiä valituilla hakuehdoilla. Laajenna hakuasi.")
    st.stop()

# Metric cards
col1, col2, col3, col4 = st.columns(4)
col1.metric("Yrityksiä yhteensä", len(df))
col2.metric("Joilla verkkosivut", df["best_website"].notna().sum())
col3.metric("Eri toimialoja", df["industry"].nunique())
col4.metric("Alueita", df["nearest_station"].nunique())

st.divider()

# ---- Map ----------------------------------------------------------------
tab_map, tab_table, tab_stats = st.tabs(["🗺️ Kartta", "📋 Yritykset", "📊 Tilastot"])

with tab_map:
    valid_coords = df.dropna(subset=["lat", "lon"])
    if valid_coords.empty:
        st.info("Ei koordinaatteja saatavilla valituille yrityksille.")
    else:
        # Company scatter layer
        scatter = pdk.Layer(
            "ScatterplotLayer",
            data=valid_coords[["lat", "lon", "name", "industry", "distance_km", "best_website", "color"]].copy(),
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

        view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)
        chart = pdk.Deck(
            layers=[scatter, station_layer],
            initial_view_state=view,
            tooltip={
                "text": "{name}\nToimiala: {industry}\nEtäisyys: {distance_km} km\n{best_website}"
            },
            map_style="mapbox://styles/mapbox/light-v10",
        )
        st.pydeck_chart(chart)
        st.caption("🔴 Asemat  · muut pisteet = yritykset (väri toimialan mukaan)")

# ---- Table --------------------------------------------------------------
with tab_table:
    # Build a display-friendly frame
    display = df[[
        "name", "industry", "toi_description", "nearest_station",
        "distance_km", "address", "best_website", "registered"
    ]].copy()
    display.columns = [
        "Yritys", "Toimiala", "TOI-kuvaus", "Asema",
        "Etäisyys (km)", "Osoite", "Verkkosivut", "Perustettu"
    ]
    display["Toimiala"] = display["Toimiala"].map(lambda x: INDUSTRY_LABELS.get(x, x))
    display["Perustettu"] = display["Perustettu"].astype("Int64")

    # Search box
    search = st.text_input("🔎 Hae yrityksen nimellä tai osoitteella", "")
    if search:
        mask = (
            display["Yritys"].str.contains(search, case=False, na=False)
            | display["Osoite"].str.contains(search, case=False, na=False)
        )
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
