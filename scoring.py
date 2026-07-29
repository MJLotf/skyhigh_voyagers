import math
from datetime import time

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the great-circle distance between two points
    on the Earth in meters using the Haversine formula.
    """
    R = 6371000.0  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


    """
    Step 3: Validates IGC fixes sequentially against task turnpoints.

    Handles:
    - Distance checking against cylinder radius
    - SSS (Start of Speed Section) ENTER / EXIT rules and start time gate
    - Sequential turnpoint validation
    - ESS & Goal deadline enforcement
    """
    turnpoints = task_data.get('turnpoints', [])
    sss_info = task_data.get('sss', {})
    goal_info = task_data.get('goal', {})

    # Parse Start Gate time (SSS)
    sss_gate_time = None
    if sss_info.get('timeGates'):
        gate_str = sss_info['timeGates'][0].replace('Z', '')
        h, m, s = map(int, gate_str.split(':'))
        sss_gate_time = time(h, m, s)

    # Parse Goal deadline time
    goal_deadline = None
    if goal_info.get('deadline'):
        dl_str = goal_info['deadline'].replace('Z', '')
        h, m, s = map(int, dl_str.split(':'))
        goal_deadline = time(h, m, s)

    current_tp_idx = 0
    total_tps = len(turnpoints)
    validated_turnpoints = []

    # State flags
    was_inside_sss = False

    for fix in igc_fixes:
        if current_tp_idx >= total_tps:
            break  # All turnpoints validated!

        tp = turnpoints[current_tp_idx]
        tp_type = tp.get('type', 'TURNPOINT')
        radius = float(tp['radius'])
        tp_lat = float(tp['waypoint']['lat'])
        tp_lon = float(tp['waypoint']['lon'])

        # Distance from pilot fix to turnpoint center
        dist = haversine_distance(fix['lat'], fix['lon'], tp_lat, tp_lon)
        is_inside = dist <= radius

        # --- 1. TAKEOFF Validation ---
        if tp_type == 'TAKEOFF':
            if is_inside:
                validated_turnpoints.append({
                    'tp_index': current_tp_idx,
                    'name': tp['waypoint']['name'],
                    'type': tp_type,
                    'achieved_at': fix['time_str'],
                    'distance_m': round(dist, 1)
                })
                current_tp_idx += 1

        # --- 2. SSS (Start of Speed Section) Validation ---
        elif tp_type == 'SSS':
            direction = sss_info.get('direction', 'EXIT')
            gate_open = (sss_gate_time is None) or (fix['time'] >= sss_gate_time)

            if direction == 'EXIT':
                if is_inside:
                    was_inside_sss = True
                elif was_inside_sss and gate_open:
                    # Crossed out of the cylinder after the start gate time
                    validated_turnpoints.append({
                        'tp_index': current_tp_idx,
                        'name': tp['waypoint']['name'],
                        'type': tp_type,
                        'achieved_at': fix['time_str'],
                        'distance_m': round(dist, 1)
                    })
                    current_tp_idx += 1
            else:  # ENTER direction
                if is_inside and gate_open:
                    validated_turnpoints.append({
                        'tp_index': current_tp_idx,
                        'name': tp['waypoint']['name'],
                        'type': tp_type,
                        'achieved_at': fix['time_str'],
                        'distance_m': round(dist, 1)
                    })
                    current_tp_idx += 1

        # --- 3. TURNPOINT / ESS / GOAL Validation ---
        else:
            # Enforce goal deadline if applicable
            if goal_deadline and fix['time'] > goal_deadline:
                continue

            if is_inside:
                validated_turnpoints.append({
                    'tp_index': current_tp_idx,
                    'name': tp['waypoint']['name'],
                    'type': tp_type,
                    'achieved_at': fix['time_str'],
                    'distance_m': round(dist, 1)
                })
                current_tp_idx += 1

    return {
        'task_completed': current_tp_idx == total_tps,
        'turnpoints_completed': current_tp_idx,
        'total_turnpoints': total_tps,
        'achieved_details': validated_turnpoints
    }
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

    # Tracking for scores
    start_time = None
    end_time = None
    pilot_distance = 0.0

    # Pre-calculate distances between each turnpoint leg
    leg_distances = []
    for i in range(1, total_tps):
        lat1, lon1 = float(turnpoints[i-1]['waypoint']['lat']), float(turnpoints[i-1]['waypoint']['lon'])
        lat2, lon2 = float(turnpoints[i]['waypoint']['lat']), float(turnpoints[i]['waypoint']['lon'])
        leg_distances.append(haversine_distance(lat1, lon1, lat2, lon2))

    total_task_distance = sum(leg_distances)

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
                # Record time at Goal/ESS
                if tp_type == 'GOAL' or current_tp_idx == total_tps - 1:
                    end_time = fix['time']

        # Update metrics if a turnpoint was achieved on this fix
        if validated_now:
            validated_turnpoints.append({'tp_index': current_tp_idx, 'name': tp['waypoint']['name'], 'type': tp_type, 'achieved_at': fix['time_str']})
            if current_tp_idx > 0:
                pilot_distance += leg_distances[current_tp_idx - 1]
            current_tp_idx += 1

    # Calculate flight time in minutes
    flight_time_mins = None
    if start_time and end_time:
        t1 = start_time.hour * 60 + start_time.minute + start_time.second / 60.0
        t2 = end_time.hour * 60 + end_time.minute + end_time.second / 60.0
        flight_time_mins = t2 - t1
        # Handle IGC UTC times that cross midnight
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
