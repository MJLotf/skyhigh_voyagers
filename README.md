# skyhigh_voyagers# 🪂 SkyHigh Voyagers – Flight Task Evaluator

SkyHigh Voyagers is a Streamlit-based web application for managing, validating, scoring, and ranking cross-country (XC) paragliding flights.

The platform enables pilots to:

- Register as pilots
- Browse and download official XC tasks
- Upload IGC tracklogs
- Automatically validate completed tasks
- Calculate distance and speed scores
- View live leaderboards
- Manage tasks through an admin interface

The application integrates with **Supabase** for persistent storage and **XContest** for task definitions.

---

# Features

## Pilot Registration

Pilots register once using:

- First name
- Last name
- SAFA number
- PG rating (PG2–PG5)

The application stores pilot information in Supabase and prevents flight submissions from unregistered pilots.

---

## Task Gallery

Pilots can browse available XC tasks stored in the database.

For every task the application provides:

- Task description
- Task designer
- Maximum available score
- Downloadable `.xctsk` task file
- QR code for importing directly into XCTrack/Oudie/etc.
- Static task map
- Link to the original XContest task

Task definitions are retrieved dynamically from the XContest API.

---

## Flight Upload & Validation

Pilots upload:

- IGC flight log
- SAFA number
- Glider class
- Glider model
- Selected XC task

The application then:

- Parses the IGC file
- Validates GPS fixes
- Sequentially checks each task turnpoint
- Detects:
  - Takeoff
  - SSS
  - Turnpoints
  - ESS
  - Goal
- Calculates:
  - Distance completed
  - Number of turnpoints reached
  - Flight time (SSS → Goal)
  - Estimated distance score

An interactive Folium map overlays:

- Official task route
- Pilot flight track

before submission.

---

## Automatic Task Validation

The validation engine supports:

- Circular turnpoint validation
- Sequential waypoint checking
- Start of Speed Section (SSS)
- Exit or Entry start cylinders
- Goal deadline enforcement
- Great-circle distance calculations using the Haversine formula

The validator returns:

- Task completion status
- Turnpoints achieved
- Distance completed
- Total task distance
- Flight time

---

## Scoring System

Every task has a configurable maximum score.

The score is divided into:

- **50% Distance Score**
- **50% Speed Score**

### Distance Score

Distance score is proportional to the percentage of the task completed.

Example:

- Complete 75% of the course
- Receive 75% of available distance points

---

### Speed Score

Only pilots reaching Goal receive speed points.

The fastest pilot for a task receives the full speed allocation.

Other pilots receive:

```
Speed Score = MaxSpeedScore − 4 × (Minutes Behind Fastest)
```

Speed score never becomes negative.

---

### Participation Multiplier

To encourage group flying, scores are multiplied according to the number of unique pilots flying the task on the same day.

| Pilots | Multiplier |
|---------|------------|
|1|0.20|
|2|0.40|
|3|0.60|
|4|0.80|
|5+|1.00|

Both distance and speed scores are multiplied by this factor.

---

## Leaderboards

The application provides two leaderboard modes.

### Overall Leaderboard

Shows each pilot's:

- Best score for every task
- Total combined score
- Gliders used

Only the highest score per pilot per task contributes to the overall ranking.

---

### Task Breakdown

Displays detailed statistics for a selected task:

- Pilot
- Glider class
- Glider model
- Distance covered
- Distance score
- Flight duration
- Time behind fastest pilot
- Participation multiplier
- Total score

---

## Leaderboard Filters

Leaderboards can be filtered by:

- Overall
- A Class only
- A & B Classes
- PG2 only
- PG2 & PG3
- PG4 or below

---

## Admin Panel

Password-protected administration interface.

Allows administrators to:

- Add new tasks
- Validate XContest task hashes
- Assign task metadata
- Set maximum task score
- Delete existing tasks

---

# Technology Stack

- Python
- Streamlit
- Supabase
- Pandas
- Folium
- Streamlit-Folium
- Requests
- XContest Task API

---

# Database Structure

## pilots

Stores registered pilot information.

Fields include:

- SAFA Number
- Name
- PG Level

---

## tasks

Stores XC task metadata.

Fields include:

- Description
- Designer
- Maximum Score
- XContest Task Hash

---

## flights

Stores submitted flight results.

Includes:

- Pilot
- Task
- Flight date
- Glider
- Distance score
- Speed score
- Total score
- Flight time
- Daily participant count

---

# External Services

## Supabase

Used for:

- Pilot registration
- Task storage
- Flight submissions
- Leaderboards

---

## XContest API

Used for:

- Downloading official task definitions
- Task validation
- Task QR generation
- Task map generation

---

# Installation

Clone the repository:

```bash
git clone https://github.com/yourusername/skyhigh-voyagers.git
cd skyhigh-voyagers
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.streamlit/secrets.toml` file:

```toml
SUPABASE_URL = "your_url"
SUPABASE_KEY = "your_key"
ADMIN_PASSWORD = "your_password"
```

Run the application:

```bash
streamlit run app.py
```

---

# Project Structure

```
.
├── app.py
├── requirements.txt
├── README.md
└── .streamlit/
    └── secrets.toml
```

---

# Core Algorithms

The application implements:

- Haversine great-circle distance calculations
- Sequential waypoint validation
- IGC B-record parsing
- Automatic flight scoring
- Dynamic leaderboard recalculation
- Daily participation multiplier
- Fastest-flight ranking

---

# Future Improvements

Potential enhancements include:

- User authentication
- Pilot profiles
- Live weather integration
- Flight replay animation
- Airspace violation detection
- GPS error filtering
- Seasonal competitions
- Club/team rankings
- Mobile-responsive interface
- Email notifications
- Automatic IGC upload from XCTrack

---

# License

This project is intended for the SkyHigh Voyagers paragliding community.

Please ensure all flying activities comply with local aviation regulations and operate safely within your skill level.
