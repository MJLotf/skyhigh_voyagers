import json
import math
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import time
from supabase import create_client, Client
from collections import defaultdict

# Set page layout
st.set_page_config(page_title="Flight Task Evaluator", layout="wide")

# --- Database Connection ---
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# -------------------------------------------------------------------
# Helper Functions: Geodesic Calculations & Parsers
# -------------------------------------------------------------------
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the great-circle distance between two points in meters."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def parse_igc(igc_text):
    """Parses IGC file B-records into a Pandas DataFrame."""
    records = []
    pilot_name = "Unknown"
    date_str = "Unknown"

    for line in igc_text.splitlines():
        if line.startswith("HFPLTPILOT:"):
            pilot_name = line.split(":", 1)[1].strip()
        elif line.startswith("HFDTE"):
            date_str = line[5:11]

        if line.startswith("B") and len(line) >= 35:
            try:
                time_str = f"{line[1:3]}:{line[3:5]}:{line[5:7]}"

                # Parse Time object for validation logic
                h, m, s = map(int, [line[1:3], line[3:5], line[5:7]])
                parsed_time = time(h, m, s)

                lat_deg = int(line[7:9])
                lat_min = float(f"{line[9:11]}.{line[11:14]}")
                lat = lat_deg + (lat_min / 60.0)
                if line[14] == "S": lat = -lat

                lon_deg = int(line[15:18])
                lon_min = float(f"{line[18:20]}.{line[20:23]}")
                lon = lon_deg + (lon_min / 60.0)
                if line[23] == "W": lon = -lon

                records.append({
                    "time_str": time_str,
                    "time": parsed_time,
                    "lat": lat,
                    "lon": lon,
                })
            except Exception:
                continue
    return pd.DataFrame(records), pilot_name, date_str

def validate_task_flight(task_data: dict, igc_fixes: list) -> dict:
    """Validates IGC fixes sequentially against task turnpoints and calculates times/distances."""
    turnpoints = task_data.get('turnpoints', [])
    sss_info = task_data.get('sss', {})
    goal_info = task_data.get('goal', {})

    sss_gate_time = None
    if sss_info.get('timeGates'):
        gate_str = sss_info['timeGates'][0].replace('Z', '')
        h, m, s = map(int, gate_str.split(':'))
        sss_gate_time = time(h, m, s)

    goal_deadline = None
    if goal_info.get('deadline'):
        dl_str = goal_info['deadline'].replace('Z', '')
        h, m, s = map(int, dl_str.split(':'))
        goal_deadline = time(h, m, s)

    current_tp_idx = 0
    total_tps = len(turnpoints)
    validated_turnpoints = []
    was_inside_sss = False

    # Tracking for scores & times
    start_time = None
    end_time = None
    pilot_distance = 0.0

    # Pre-calculate distances between each turnpoint leg
    leg_distances = []
    for i in range(1, total_tps):
        lat1, lon1 = float(turnpoints[i-1]['waypoint']['lat']), float(turnpoints[i-1]['waypoint']['lon'])
        lat2, lon2 = float(turnpoints[i]['waypoint']['lat']), float(turnpoints[i]['waypoint']['lon'])
        leg_distances.append(haversine_distance(lat1, lon1, lat2, lon2))

    total_task_distance = sum(leg_distances) if leg_distances else 1.0

    for fix in igc_fixes:
        if current_tp_idx >= total_tps: break

        tp = turnpoints[current_tp_idx]
        tp_type = tp.get('type', 'TURNPOINT')
        radius = float(tp['radius'])
        tp_lat = float(tp['waypoint']['lat'])
        tp_lon = float(tp['waypoint']['lon'])

        dist = haversine_distance(fix['lat'], fix['lon'], tp_lat, tp_lon)
        is_inside = dist <= radius

        validated_now = False

        if tp_type == 'TAKEOFF':
            if is_inside:
                validated_now = True
        elif tp_type == 'SSS':
            direction = sss_info.get('direction', 'EXIT')
            gate_open = (sss_gate_time is None) or (fix['time'] >= sss_gate_time)

            if direction == 'EXIT':
                if is_inside: was_inside_sss = True
                elif was_inside_sss and gate_open:
                    validated_now = True
                    start_time = fix['time']
            else:
                if is_inside and gate_open:
                    validated_now = True
                    start_time = fix['time']
        else:
            if goal_deadline and fix['time'] > goal_deadline: continue
            if is_inside:
                validated_now = True
                if tp_type in ('GOAL', 'ESS') or current_tp_idx == total_tps - 1:
                    end_time = fix['time']

        if validated_now:
            validated_turnpoints.append({
                'tp_index': current_tp_idx,
                'name': tp['waypoint']['name'],
                'type': tp_type,
                'achieved_at': fix['time_str']
            })
            if current_tp_idx > 0 and (current_tp_idx - 1) < len(leg_distances):
                pilot_distance += leg_distances[current_tp_idx - 1]
            current_tp_idx += 1

    # Calculate flight time in minutes between SSS and ESS/Goal
    flight_time_mins = None
    if start_time and end_time:
        t1 = start_time.hour * 60 + start_time.minute + start_time.second / 60.0
        t2 = end_time.hour * 60 + end_time.minute + end_time.second / 60.0
        flight_time_mins = t2 - t1
        if flight_time_mins < 0:
            flight_time_mins += 24 * 60

    return {
        'task_completed': current_tp_idx == total_tps,
        'turnpoints_completed': current_tp_idx,
        'total_turnpoints': total_tps,
        'achieved_details': validated_turnpoints,
        'pilot_distance': pilot_distance,
        'total_task_distance': total_task_distance,
        'flight_time_mins': flight_time_mins
    }

# -------------------------------------------------------------------
# Page Renderers
# -------------------------------------------------------------------

def render_pilot_page():
    st.title("🪂 Pilot Flight Submission")
    st.markdown("Select a task, upload your IGC file, preview your flight, and submit your score.")

    # Fetch tasks from DB
    response = supabase.table("tasks").select("*").execute()
    tasks_data = response.data

    if not tasks_data:
        st.warning("No tasks available. An admin needs to create tasks first.")
        return

    # Pilot inputs form
    with st.form("pilot_inputs_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            pilot_name = st.text_input("Pilot Name")
        with col2:
            safa_number = st.number_input("SAFA Number (ID)", min_value=1, step=1)
        with col3:
            glider_class = st.selectbox("Glider Class", options=['A', 'B', 'C', 'D', 'CCC'])

        # Task Selection
        task_options = {f"{t['description']} (Max Score: {t['max_score']})": t for t in tasks_data}
        selected_task_label = st.selectbox("Select Task", options=list(task_options.keys()))
        selected_task = task_options[selected_task_label]

        igc_file = st.file_uploader("Upload Tracklog File (.igc)", type=["igc"])

        preview_button = st.form_submit_button("Preview & Evaluate")

    # 1. When Preview button is pressed, parse and save results into session_state
    if preview_button:
        if not pilot_name:
            st.error("Please enter your name.")
        elif not igc_file:
            st.error("Please upload an IGC file.")
        else:
            task_json = selected_task['xctrack_json_data']
            igc_content = igc_file.read().decode("utf-8", errors="ignore")
            igc_df, parsed_name, flight_date = parse_igc(igc_content)

            if igc_df.empty:
                st.error("Invalid IGC file or no valid fixes found.")
            else:
                validation_results = validate_task_flight(task_json, igc_df.to_dict('records'))
                max_score = float(selected_task['max_score'])

                # Calculate Base Distance Score
                dist_ratio = validation_results['pilot_distance'] / max(validation_results['total_task_distance'], 1)
                dist_ratio = min(dist_ratio, 1.0)
                base_distance_score = (max_score * 0.5) * dist_ratio

                st.session_state["eval_data"] = {
                    "pilot_name": pilot_name,
                    "safa_number": safa_number,
                    "glider_class": glider_class,
                    "selected_task": selected_task,
                    "igc_df": igc_df,
                    "flight_date": flight_date,
                    "validation_results": validation_results,
                    "base_distance_score": base_distance_score,
                    "estimated_score": base_distance_score
                }

    # 2. Render evaluation results whenever session_state has eval_data
    if "eval_data" in st.session_state:
        data = st.session_state["eval_data"]
        validation_results = data["validation_results"]
        estimated_score = data["estimated_score"]
        selected_task = data["selected_task"]
        igc_df = data["igc_df"]
        task_json = selected_task['xctrack_json_data']

        st.markdown("---")
        st.subheader("📋 Evaluation Preview")
        st.write(f"**Turnpoints Reached:** {validation_results['turnpoints_completed']} / {validation_results['total_turnpoints']}")
        st.write(f"**Estimated Distance Score:** {round(estimated_score, 2)}")

        if validation_results['achieved_details']:
            st.dataframe(pd.DataFrame(validation_results['achieved_details']))

        # Render Map
        turnpoints = task_json.get('turnpoints', [])
        if turnpoints and not igc_df.empty:
            start_lat = float(turnpoints[0]['waypoint']['lat'])
            start_lon = float(turnpoints[0]['waypoint']['lon'])
            m = folium.Map(location=[start_lat, start_lon], zoom_start=11)

            for tp in turnpoints:
                folium.Circle(
                    location=[float(tp['waypoint']['lat']), float(tp['waypoint']['lon'])],
                    radius=float(tp['radius']),
                    color="blue", fill=True
                ).add_to(m)

            track_coords = igc_df[["lat", "lon"]].values.tolist()
            folium.PolyLine(track_coords, color="orange", weight=3, opacity=0.8).add_to(m)

            st_folium(m, width=1200, height=500, key="preview_flight_map")

        # 3. Submit Flight to Supabase
        if st.button("Submit Flight to Database", type="primary"):
            # Upsert Pilot
            pilot_data = {
                "safa_number": data["safa_number"],
                "name": data["pilot_name"],
                "glider_class": data["glider_class"]
            }
            supabase.table("pilots").upsert(pilot_data).execute()

            flight_time = data["validation_results"].get('flight_time_mins')

            # Insert current flight
            flight_data = {
                "pilot_id": data["safa_number"],
                "task_id": selected_task['id'],
                "flight_date": data["flight_date"],
                "base_distance_score": round(data["base_distance_score"], 2),
                "speed_score": 0,
                "distance_score": round(data["base_distance_score"], 2),
                "total_score": round(data["base_distance_score"], 2),
                "flight_time_minutes": flight_time,
                "participants": 1
            }
            supabase.table("flights").insert(flight_data).execute()

            # --- Master Recalculation Engine ---
            flights_res = supabase.table("flights").select("*").eq("task_id", selected_task['id']).execute()
            all_task_flights = flights_res.data

            if all_task_flights:
                completed_flights = [f for f in all_task_flights if f.get("flight_time_minutes") is not None]
                fastest_time = min(f["flight_time_minutes"] for f in completed_flights) if completed_flights else None

                max_score = float(selected_task["max_score"])

                daily_pilots = defaultdict(set)
                for f in all_task_flights:
                    if f.get("flight_date"):
                        daily_pilots[f["flight_date"]].add(f["pilot_id"])

                for f in all_task_flights:
                    f_date = f.get("flight_date")
                    unique_count = len(daily_pilots[f_date]) if f_date else 1
                    day_multiplier = min(1.0, unique_count / 5.0)

                    base_dist = float(f.get("base_distance_score") or f.get("distance_score") or 0)
                    base_speed = 0.0

                    if f.get("flight_time_minutes") is not None and fastest_time is not None:
                        p_time = f["flight_time_minutes"]
                        base_speed = max(0, (max_score * 0.5) - 4 * (p_time - fastest_time))

                    final_dist = base_dist * day_multiplier
                    final_speed = base_speed * day_multiplier
                    final_total = final_dist + final_speed

                    supabase.table("flights").update({
                        "speed_score": round(final_speed, 2),
                        "distance_score": round(final_dist, 2),
                        "total_score": round(final_total, 2),
                        "participants": unique_count
                    }).eq("id", f["id"]).execute()

            st.success(f"Flight submitted! Scores for Task {selected_task['id']} updated based on global speed and daily team sizes.")
            del st.session_state["eval_data"]

def render_admin_page():
    st.title("🛠️ Admin Control Panel")

    password = st.text_input("Enter Admin Password", type="password")
    if password != st.secrets["ADMIN_PASSWORD"]:
        if password: st.error("Incorrect password.")
        return

    st.success("Authenticated.")

    tab1, tab2 = st.tabs(["Add Task", "Manage Tasks"])

    with tab1:
        st.subheader("Add New Task")
        with st.form("add_task_form"):
            desc = st.text_input("Description")
            designer = st.text_input("Designer")
            max_score = st.number_input("Max Score", min_value=0, max_value=1000)
            task_file = st.file_uploader("Task JSON File", type=["json"])

            if st.form_submit_button("Save Task"):
                if task_file and desc:
                    task_json = json.load(task_file)
                    task_data = {
                        "description": desc,
                        "designer": designer,
                        "max_score": max_score,
                        "xctrack_json_data": task_json
                    }
                    supabase.table("tasks").insert(task_data).execute()
                    st.success("Task added!")
                else:
                    st.error("Please provide both a description and a JSON file.")

    with tab2:
        st.subheader("Existing Tasks")
        response = supabase.table("tasks").select("id, description, designer, max_score").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            st.dataframe(df)

            del_id = st.number_input("Task ID to Delete", min_value=1, step=1)
            if st.button("Delete Task", type="primary"):
                supabase.table("tasks").delete().eq("id", del_id).execute()
                st.success("Task deleted. Refresh to update table.")

def render_leaderboard_page():
    st.title("🏆 Leadership Board")

    flights_res = supabase.table("flights").select("*, pilots(name), tasks(description)").execute()

    if not flights_res.data:
        st.info("No flights recorded yet.")
        return

    flat_data = []
    for f in flights_res.data:
        flat_data.append({
            "Pilot": f["pilots"]["name"],
            "Task": f["tasks"]["description"],
            "Score": float(f["total_score"])
        })

    df = pd.DataFrame(flat_data)

    leaderboard = df.pivot_table(index="Pilot", columns="Task", values="Score", aggfunc="max", fill_value=0)
    leaderboard["Total Score"] = leaderboard.sum(axis=1)
    leaderboard = leaderboard.sort_values(by="Total Score", ascending=False)

    st.dataframe(leaderboard.style.format("{:.1f}"), use_container_width=True)

# -------------------------------------------------------------------
# Navigation Routing
# -------------------------------------------------------------------
page = st.sidebar.radio("Navigation", ["Pilot Upload", "Leaderboard", "Admin"])

if page == "Pilot Upload":
    render_pilot_page()
elif page == "Leaderboard":
    render_leaderboard_page()
elif page == "Admin":
    render_admin_page()
