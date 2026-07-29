import json
import math
import re
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

# Set page layout
st.set_page_config(page_title="Flight Task Evaluator", layout="wide")


# -------------------------------------------------------------------
# Helper Functions: Geodesic Calculations & Parsers
# -------------------------------------------------------------------
def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates great-circle distance between two points on Earth in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def parse_igc(igc_text):
    """Parses IGC file B-records into a Pandas DataFrame."""
    records = []
    pilot_name = "Unknown"
    date_str = "Unknown"

    for line in igc_text.splitlines():
        # Extract metadata
        if line.startswith("HFPLTPILOT:"):
            pilot_name = line.split(":", 1)[1].strip()
        elif line.startswith("HFDTE"):
            date_str = line[5:11]

        # Extract B-records (Fix points)
        # Format: B hhmmss DDMMmmm N/S DDDMMmmm E/W A/V pppppp gggggg
        if line.startswith("B") and len(line) >= 35:
            try:
                time_str = f"{line[1:3]}:{line[3:5]}:{line[5:7]}"

                # Latitude: DDMMmmm S/N
                lat_deg = int(line[7:9])
                lat_min = float(f"{line[9:11]}.{line[11:14]}")
                lat = lat_deg + (lat_min / 60.0)
                if line[14] == "S":
                    lat = -lat

                # Longitude: DDDMMmmm E/W
                lon_deg = int(line[15:18])
                lon_min = float(f"{line[18:20]}.{line[20:23]}")
                lon = lon_deg + (lon_min / 60.0)
                if line[23] == "W":
                    lon = -lon

                # Altitudes
                press_alt = int(line[25:30])
                gps_alt = int(line[30:35])

                records.append(
                    {
                        "time": time_str,
                        "lat": lat,
                        "lon": lon,
                        "press_alt": press_alt,
                        "gps_alt": gps_alt,
                    }
                )
            except Exception:
                continue

    df = pd.DataFrame(records)
    return df, pilot_name, date_str


def parse_task(task_json):
    """Extracts turnpoint details from the Task JSON structure."""
    turnpoints = []
    for index, tp in enumerate(task_json.get("turnpoints", [])):
        wp = tp.get("waypoint", {})
        radius = float(tp.get("radius", 0))
        tp_type = tp.get("type", "TURNPOINT")

        turnpoints.append(
            {
                "index": index + 1,
                "name": wp.get("name", f"TP{index+1}"),
                "description": wp.get("description", ""),
                "lat": float(wp.get("lat", 0.0)),
                "lon": float(wp.get("lon", 0.0)),
                "radius": radius,
                "type": tp_type,
            }
        )
    return turnpoints


def evaluate_task(igc_df, turnpoints):
    """Evaluates min distance and validation for each turnpoint."""
    results = []

    for tp in turnpoints:
        min_dist = float("inf")
        achieved_time = None
        reached = False

        for _, row in igc_df.iterrows():
            dist = haversine_distance(row["lat"], row["lon"], tp["lat"], tp["lon"])
            if dist < min_dist:
                min_dist = dist
                if dist <= tp["radius"] and not reached:
                    reached = True
                    achieved_time = row["time"]

        results.append(
            {
                "TP #": tp["index"],
                "Name": tp["name"],
                "Type": tp["type"],
                "Radius (m)": int(tp["radius"]),
                "Min Dist (m)": round(min_dist, 1),
                "Status": "✅ Reached" if reached else "❌ Missed",
                "Achieved Time": achieved_time if achieved_time else "N/A",
            }
        )

    return pd.DataFrame(results)


# -------------------------------------------------------------------
# Streamlit Web Interface
# -------------------------------------------------------------------
st.title("🪂 Flight Task & Tracklog Evaluator")
st.markdown(
    "Upload your **Task JSON** and **IGC Tracklog** file to validate turnpoint achievements and view the flight path."
)

col1, col2 = st.columns(2)

with col1:
    task_file = st.file_uploader("Upload Task File (.json)", type=["json"])

with col2:
    igc_file = st.file_uploader("Upload Tracklog File (.igc)", type=["igc"])

if task_file and igc_file:
    # 1. Parse Task File
    task_data = json.load(task_file)
    turnpoints = parse_task(task_data)

    # 2. Parse IGC File
    igc_content = igc_file.read().decode("utf-8", errors="ignore")
    igc_df, pilot_name, flight_date = parse_igc(igc_content)

    if igc_df.empty:
        st.error(
            "Could not parse valid B-records from the provided IGC file. Please check the file format."
        )
    else:
        # Display Pilot Info
        st.subheader("📋 Flight Metadata")
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("Pilot", pilot_name)
        m_col2.metric("Date", flight_date)
        m_col3.metric("Track Points", len(igc_df))
        m_col4.metric("Max Altitude (GPS)", f"{igc_df['gps_alt'].max()} m")

        st.markdown("---")

        # 3. Evaluate Turnpoints
        st.subheader("🎯 Turnpoint Verification Summary")
        eval_df = evaluate_task(igc_df, turnpoints)
        st.dataframe(eval_df, use_container_width=True)

        st.markdown("---")

        # 4. Map Display
        st.subheader("🗺️ Flight Track & Task Map")

        # Center map on the first turnpoint
        start_lat = turnpoints[0]["lat"] if turnpoints else igc_df["lat"].iloc[0]
        start_lon = turnpoints[0]["lon"] if turnpoints else igc_df["lon"].iloc[0]

        m = folium.Map(location=[start_lat, start_lon], zoom_start=11)

        # Plot Turnpoint Cylinders and Markers
        for tp in turnpoints:
            color = (
                "green"
                if tp["type"] == "TAKEOFF"
                else (
                    "red"
                    if tp["type"] == "ESS"
                    else "blue" if tp["type"] == "SSS" else "purple"
                )
            )

            # Turnpoint Center Marker
            folium.Marker(
                location=[tp["lat"], tp["lon"]],
                popup=f"{tp['name']} ({tp['type']})<br>Radius: {tp['radius']}m",
                tooltip=f"TP{tp['index']}: {tp['name']}",
                icon=folium.Icon(color=color, icon="flag"),
            ).add_to(m)

            # Turnpoint Cylinder Boundary Circle
            folium.Circle(
                location=[tp["lat"], tp["lon"]],
                radius=tp["radius"],
                color=color,
                fill=True,
                fill_opacity=0.15,
            ).add_to(m)

        # Plot IGC Flight Path
        track_coords = igc_df[["lat", "lon"]].values.tolist()
        folium.PolyLine(
            track_coords, color="orange", weight=3, opacity=0.8, tooltip="Flight Track"
        ).add_to(m)

        # Render Map in Streamlit
        st_folium(m, width=1200, height=600)

else:
    st.info(
        "Please upload both a Task JSON file and an IGC tracklog file to begin evaluation."
    )
