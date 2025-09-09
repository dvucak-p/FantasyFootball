import os
import json
from espn_api.football import League
from pathlib import Path
from datetime import datetime

# Get current year
current_year = datetime.now().year

# --- CONFIG ---
LEAGUE_ID = 487404  # <-- your league ID
YEAR = current_year         # <-- season year
OUTPUT_FILE = Path("LeagueData.json")

# Get credentials from environment
SWID = os.getenv("SWID")
ESPN_S2 = os.getenv("ESPN_S2")

if not SWID or not ESPN_S2:
    raise ValueError("Missing SWID or ESPN_S2 environment variables")

# Connect to league
league = League(league_id=LEAGUE_ID, year=YEAR, swid=SWID, espn_s2=ESPN_S2)

# --- Helper: Median W/L Record ---
def get_median_records(league):
    median_records = {team.team_id: {"wins": 0, "losses": 0} for team in league.teams}

    for week in range(1, league.current_week + 1):
        scores_this_week = []
        for box in league.box_scores(week):
            scores_this_week.extend([box.home_score, box.away_score or 0])
        median_score = sorted(scores_this_week)[len(scores_this_week)//2]

        for box in league.box_scores(week):
            if box.home_team:
                if box.home_score >= median_score:
                    median_records[box.home_team.team_id]["wins"] += 1
                else:
                    median_records[box.home_team.team_id]["losses"] += 1
            if box.away_team:
                if box.away_score >= median_score:
                    median_records[box.away_team.team_id]["wins"] += 1
                else:
                    median_records[box.away_team.team_id]["losses"] += 1

    return median_records

median_records = get_median_records(league)

# --- Collect Team Data ---
teams_data = []
first_place_wins = max([t.wins for t in league.teams])

for team in league.teams:
    overall_record = f"{team.wins}-{team.losses}-{team.ties}"
    wl_record = f"{team.wins}-{team.losses}"
    median_record = median_records[team.team_id]
    median_str = f"{median_record['wins']}-{median_record['losses']}"
    gb = (first_place_wins - team.wins)
    teams_data.append({
        "Rank": team.standing,
        "Team": team.team_name,
        "Overall Record": overall_record,
        "W/L Record": wl_record,
        "Median Score Record": median_str,
        "GB": gb,
        "Pts Scored": round(team.points_for, 2)
    })

# --- Write to JSON file ---
with open(OUTPUT_FILE, "w") as f:
    json.dump(teams_data, f, indent=2)

print(f"Data written to {OUTPUT_FILE}")
