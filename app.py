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

def render_welcome_page():
    st.title("🪂 Welcome to the SkyHigh Voyagers Project")
    st.markdown("""
    ### Elevate Your Cross-Country Flying
    Welcome pilots! This platform is designed to help our paragliding community to enhance their cross country flying experience through a friendly, safe, and supporttive enviromenet promoting team and group flying.
    """)

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🎯 Our Mission")
        st.info("""
        Our mission is to support pilot skill progression, foster friendly competition, and build a vibrant XC community. By providing accessible task downloads, real-time tracklog validation, and fair performance scoring, we make task flying simple and fun for everyone.
        """)

        st.markdown("### 🛠️ How to Set Up & Fly a Task")
        st.markdown("""
        1. **Browse Tasks:** Visit the **Task Gallery** to explore task routes and waypoint coordinates.
        2. **Download File:** Click to download the task files directly to your device or scan the QR code for quick access.
        3. **Configure Your Instrument:** Import the downloaded task into your flight computer or navigation app (e.g., *XCTrack*, *Oudie*, or *SkyFlyHy*).
        4. **Find flying buddies:** Coordinate with fellow pilots to fly together on the same day for maximum scoring potential.
        5. **Fly the Route:** Take off, cross the SSS (Start Gate) pass through all sequential turnpoints, and reach Goal.
        6. **Submit Tracklog:** Head over to **Pilot Upload**, select your task, upload your tracklog file, and record your score on the leaderboard.
        """)

    with col2:
        st.markdown("### 📊 How the Scoring System Works")
        st.markdown("""
        We use a custom scoring algorithm to foster skill progression and reward pilots for both distance and speed, while also encouraging group flying.
        All tasks are speedruns with a maxium possible score based on the task's nominal distance and difficulty.
        You can fly any task at in anyday you wantwith your own pace.
        To maximize your score, aim to fly with at least 4 more pilots and reach the goal as quickly as possible while staying safe and within your skill level.
        Your results will be compared against all other pilots who flew the same task in the whole season.
        As score will be adjusted based on how many unique pilots participated that day, please upload your tracklog even if you had a slow flight or did not reach the goal. Every flight counts toward the community and your own skill development!

        So gather your friends, plan your flight, and retrive toghter!


        Details of the scoring system are as follows:
        Each tasks has a maximum score based on its nominal distance and difficulty (e.g., 600 points for easy tasks, 1000 points for difficult tasks).
        The maximum score is split evenly between distance and speed components, with a multiplier applied based on the number of unique pilots flying the task on the same day.
        In days with fewer than 5 pilots, the multiplier reduces the total score proportionally to encourage group flying and community engagement. For example, if only 3 pilots fly the task on a given day, each pilot's total score is multiplied by 0.6 (3/5). If 5 or more pilots fly the task, the multiplier is 1.0, allowing pilots to earn the full potential score.

        Flights are validated automatically against official task turnpoints. Scores consist of three core components:

        * **Distance Score (50% max):**
          Earned proportionally based on how far along the task route you fly compared to total task length. So if you fly half the task distance, you earn only half of the maximum distance score.

        * **Speed Score (50% max):**
          Awarded to only pilots completing the task and reach the goal. The time will be calculated from the time you toughed start of speed section (SSS) to when you touched the end of speed section (ESS). The fastest pilot in whole seasonreceives maximum speed points ("50%" of the maximum score). Speed scores for the following pilots are calculated with a minor time-decay penalty (4 pts/min).

        * **Overall Score:**
          Socres from different tasks are combined to create an overall leaderboard. Your best score for each task is used to calculate your total score, encouraging pilots to improve their performance on tasks they have already flown.
        """)

    st.markdown("---")
    st.success("Ready to fly? Head over to **Task Gallery** to pick your task, or **Pilot Upload** to evaluate a completed flight!")

def render_task_gallery_page():
    st.title("🗺️ Task Gallery")
    st.markdown("Browse available cross-country tasks, preview route turnpoints, and download task files for your flight computer.")

    # Fetch tasks from Supabase
    response = supabase.table("tasks").select("*").execute()
    tasks_data = response.data

    if not tasks_data:
        st.info("No tasks available in the gallery yet. Check back soon!")
        return

    # Select box to pick task
    task_options = {f"Task #{t['id']} - {t['description']} (Max: {t['max_score']} pts)": t for t in tasks_data}
    selected_label = st.selectbox("Select a Task to Preview:", options=list(task_options.keys()))
    task = task_options[selected_label]

    task_json = task.get('xctrack_json_data', {})
    turnpoints = task_json.get('turnpoints', [])

    # Pre-calculate route length
    leg_distances = []
    for i in range(1, len(turnpoints)):
        lat1, lon1 = float(turnpoints[i-1]['waypoint']['lat']), float(turnpoints[i-1]['waypoint']['lon'])
        lat2, lon2 = float(turnpoints[i]['waypoint']['lat']), float(turnpoints[i]['waypoint']['lon'])
        leg_distances.append(haversine_distance(lat1, lon1, lat2, lon2))
    total_dist_km = sum(leg_distances) / 1000.0 if leg_distances else 0.0

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader(task['description'])
        st.markdown(f"**Designer:** {task.get('designer', 'N/A')}")
        st.markdown(f"**Max Task Score:** {task.get('max_score', 1000)} pts")
        st.markdown(f"**Nominal Distance:** {round(total_dist_km, 2)} km")
        st.markdown(f"**Turnpoints:** {len(turnpoints)}")

        # Download Task File Button
        json_str = json.dumps(task_json, indent=2)
        st.download_button(
            label="📥 Download Task File (.json)",
            data=json_str,
            file_name=f"task_{task['id']}_{task['description'].replace(' ', '_')}.json",
            mime="application/json",
            type="primary"
        )

        st.markdown("---")
        st.markdown("### Turnpoint Sequence")
        tp_list = []
        for idx, tp in enumerate(turnpoints, 1):
            tp_list.append({
                "#": idx,
                "Name": tp['waypoint'].get('name', 'N/A'),
                "Type": tp.get('type', 'TURNPOINT'),
                "Radius": f"{tp.get('radius', 0)} m"
            })
        st.dataframe(pd.DataFrame(tp_list), hide_index=True, use_container_width=True)

    with col2:
        st.subheader("Task Route Map")
        if turnpoints:
            start_lat = float(turnpoints[0]['waypoint']['lat'])
            start_lon = float(turnpoints[0]['waypoint']['lon'])
            m = folium.Map(location=[start_lat, start_lon], zoom_start=11)

            route_coords = []
            for idx, tp in enumerate(turnpoints):
                lat = float(tp['waypoint']['lat'])
                lon = float(tp['waypoint']['lon'])
                radius = float(tp['radius'])
                tp_type = tp.get('type', 'TURNPOINT')
                name = tp['waypoint'].get('name', f'TP{idx+1}')

                route_coords.append([lat, lon])

                # Color coding cylinders by turnpoint type
                color = "blue"
                if tp_type == "TAKEOFF":
                    color = "green"
                elif tp_type == "SSS":
                    color = "purple"
                elif tp_type in ("ESS", "GOAL"):
                    color = "red"

                folium.Circle(
                    location=[lat, lon],
                    radius=radius,
                    color=color,
                    fill=True,
                    fill_opacity=0.2,
                    popup=f"<b>{name}</b><br>Type: {tp_type}<br>Radius: {radius}m"
                ).add_to(m)

                folium.Marker(
                    location=[lat, lon],
                    popup=f"{idx+1}. {name} ({tp_type})",
                    icon=folium.Icon(color=color if color in ['red', 'blue', 'green', 'purple'] else 'blue', icon="info-sign")
                ).add_to(m)

            # Draw task path
            if len(route_coords) > 1:
                folium.PolyLine(route_coords, color="orange", weight=3, opacity=0.8, dash_array='5, 10').add_to(m)

            st_folium(m, width=800, height=550, key=f"task_gallery_map_{task['id']}")
        else:
            st.warning("No geographic waypoints found for this task.")

def render_pilot_page():
    st.title("👨‍✈️ Pilot Flight Submission")
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
        st.subheader("📑 Evaluation Preview")
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
    st.title("🖥️ Admin Control Panel")

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

    # Fetch flights with related pilot and task details
    flights_res = supabase.table("flights").select("*, pilots(name, safa_number), tasks(id, description, max_score, xctrack_json_data)").execute()

    if not flights_res.data:
        st.info("No flights recorded yet.")
        return

    # Fetch all tasks for dropdown choices
    tasks_res = supabase.table("tasks").select("*").execute()
    tasks_data = tasks_res.data if tasks_res.data else []

    task_options = ["Overall"] + [t["description"] for t in tasks_data]
    selected_option = st.selectbox("Select View", options=task_options)

    if selected_option == "Overall":
        st.subheader("📊 Overall Leaderboard")

        pilot_task_scores = defaultdict(dict)
        pilot_info = {}

        for f in flights_res.data:
            pilot_data = f.get("pilots", {})
            task_data = f.get("tasks", {})
            if not pilot_data or not task_data:
                continue

            safa = pilot_data.get("safa_number")
            name = pilot_data.get("name")
            task_desc = task_data.get("description")
            score = float(f.get("total_score", 0))

            pilot_info[safa] = name
            current_max = pilot_task_scores[safa].get(task_desc, 0.0)
            if score > current_max:
                pilot_task_scores[safa][task_desc] = score

        table_rows = []
        all_task_names = [t["description"] for t in tasks_data]

        for safa, name in pilot_info.items():
            row = {"SAFA Number": safa, "Pilot Name": name}
            pilot_total = 0.0
            for t_name in all_task_names:
                s = pilot_task_scores[safa].get(t_name, 0.0)
                row[t_name] = s
                pilot_total += s
            row["Total Score"] = pilot_total
            table_rows.append(row)

        if table_rows:
            df_overall = pd.DataFrame(table_rows)
            df_overall = df_overall.sort_values(by="Total Score", ascending=False).reset_index(drop=True)
            st.dataframe(df_overall.style.format({col: "{:.1f}" for col in df_overall.columns if col not in ["SAFA Number", "Pilot Name"]}), use_container_width=True)
        else:
            st.info("No overall results found.")

    else:
        st.subheader(f"📌 Task Breakdown & Validation: {selected_option}")

        selected_task_obj = next((t for t in tasks_data if t["description"] == selected_option), None)
        if not selected_task_obj:
            st.warning("Selected task details not found.")
            return

        max_score = float(selected_task_obj["max_score"])
        task_json = selected_task_obj["xctrack_json_data"]

        # Calculate total task distance
        turnpoints = task_json.get('turnpoints', [])
        leg_distances = []
        for i in range(1, len(turnpoints)):
            lat1, lon1 = float(turnpoints[i-1]['waypoint']['lat']), float(turnpoints[i-1]['waypoint']['lon'])
            lat2, lon2 = float(turnpoints[i]['waypoint']['lat']), float(turnpoints[i]['waypoint']['lon'])
            leg_distances.append(haversine_distance(lat1, lon1, lat2, lon2))
        total_task_distance = sum(leg_distances) if leg_distances else 1.0

        # Filter flights for the chosen task
        task_flights = [f for f in flights_res.data if f.get("tasks", {}).get("description") == selected_option]

        if not task_flights:
            st.info("No flights recorded for this task yet.")
            return

        completed_times = [f["flight_time_minutes"] for f in task_flights if f.get("flight_time_minutes") is not None]
        fastest_time = min(completed_times) if completed_times else None

        breakdown_rows = []
        for f in task_flights:
            pilot_data = f.get("pilots", {})
            safa = pilot_data.get("safa_number")
            name = pilot_data.get("name")

            distance_score = float(f.get("distance_score", 0))
            total_score = float(f.get("total_score", 0))
            flight_time = f.get("flight_time_minutes")
            participants = f.get("participants", 1)

            day_factor = round(min(1.0, participants / 5.0), 2)

            # Derive base distance score & distance covered (km)
            base_dist = distance_score / day_factor if day_factor > 0 else distance_score
            max_dist_score = max_score * 0.5
            if max_dist_score > 0:
                dist_ratio = min(1.0, base_dist / max_dist_score)
                distance_covered_km = (dist_ratio * total_task_distance) / 1000.0
            else:
                distance_covered_km = 0.0

            # Duration and time difference vs fastest pilot
            if flight_time is not None and fastest_time is not None:
                time_diff = round(flight_time - fastest_time, 2)
                duration_str = f"{round(flight_time, 2)} mins"
                time_diff_str = f"{'+' if time_diff > 0 else ''}{time_diff} mins"
            else:
                duration_str = "N/A"
                time_diff_str = "N/A"

            breakdown_rows.append({
                "SAFA Number": safa,
                "Pilot Name": name,
                "Max Score of Task": max_score,
                "Day Factor": day_factor,
                "Distance Covered (km)": round(distance_covered_km, 2),
                "Distance Score": round(distance_score, 2),
                "Total Duration": duration_str,
                "Time Diff vs Fastest": time_diff_str,
                "Total Score": round(total_score, 2)
            })

        df_breakdown = pd.DataFrame(breakdown_rows)
        if not df_breakdown.empty:
            df_breakdown = df_breakdown.sort_values(by="Total Score", ascending=False).reset_index(drop=True)
            st.dataframe(df_breakdown, use_container_width=True)
        else:
            st.info("No score data available for this task.")

# -------------------------------------------------------------------
# Navigation Routing
# -------------------------------------------------------------------
page = st.sidebar.radio("Navigation", ["Welcome", "Task Gallery", "Pilot Upload", "Leaderboard", "Admin"])

if page == "Welcome":
    render_welcome_page()
elif page == "Task Gallery":
    render_task_gallery_page()
elif page == "Pilot Upload":
    render_pilot_page()
elif page == "Leaderboard":
    render_leaderboard_page()
elif page == "Admin":
    render_admin_page()
