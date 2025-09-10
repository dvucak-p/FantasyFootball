import os
import re
import json
import math
from espn_api.football import League
from pathlib import Path
from datetime import datetime

# Get current year
current_year = datetime.now().year

# --- CONFIG ---
LEAGUE_ID = 487404  # <-- your league ID
YEAR = 2025
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

    if league.current_week + 1 < 15:
        max_week_num = league.current_week + 1
    else:
        max_week_num = 14

    for week in range(1, max_week_num):
        try:
            box_scores = league.box_scores(week)
        except KeyError:
            print(f"Skipping week {week} (no roster data yet)")
            continue

        scores_this_week = []
        for box in box_scores:
            if box.home_score is not None:
                scores_this_week.append(box.home_score)
            if box.away_score is not None:
                scores_this_week.append(box.away_score)

        if not scores_this_week:
            continue

        scores_this_week.sort()
        mid = len(scores_this_week) // 2
        if len(scores_this_week) % 2 == 0:
            median_score = (scores_this_week[mid - 1] + scores_this_week[mid]) / 2
        else:
            median_score = scores_this_week[mid]

        for box in box_scores:
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
    # overall_record = f"{team.wins}-{team.losses}-{team.ties}"
    wl_record = f"{team.wins}-{team.losses}-{team.ties}"
    games_played = team.wins + team.losses + team.ties
    # win_pct = round(((team.wins + 0.5 * team.ties) / games_played) * 100, 2) if games_played > 0 else 0.0
    median_record = median_records[team.team_id]
    median_str = f"{median_record['wins']}-{median_record['losses']}-0"
    gb = first_place_wins - team.wins if team.wins != first_place_wins else "-"
    remaining_acquisition_budget = 100 - team.acquisition_budget_spent

    # Split and convert to integers
    parts1 = list(map(int, wl_record.split("-")))
    parts2 = list(map(int, median_str.split("-")))

    # Add element-wise
    result_parts = [a + b for a, b in zip(parts1, parts2)]

    # Join back into a string
    overall_record = "-".join(map(str, result_parts))

    # Split both strings into lists of integers
    parts1 = list(map(int, wl_record.split("-")))
    parts2 = list(map(int, median_str.split("-")))

    # Add element-wise
    combined = [a + b for a, b in zip(parts1, parts2)]

    # Convert back to record string
    record = "-".join(map(str, combined))

    # Calculate win percentage
    wins, losses, ties = combined
    total_games = wins + losses + ties
    win_pct = round(((wins + 0.5 * ties) / total_games) * 100, 2) if total_games > 0 else 0.0

    teams_data.append({
        "Rank": team.standing,
        "Team": team.team_name,        
        "Overall Record": overall_record,
        "Win %": round(win_pct, 2),
        "Matchup Record": wl_record,
        "Median Score Record": median_str,
        "GB": gb,
        "PF": math.ceil(team.points_for * 100) / 100,
        "PA": math.ceil(team.points_against * 100) / 100,
        "Acquisition Budget": remaining_acquisition_budget,
        "Team Logo": team.logo_url
    })


# --- helpers ---
def normalize_name(name):
    # """Lowercase, strip, and remove non-alphanumeric chars for reliable matching."""
    if not name:
        return ""
    return re.sub(r'[^a-z0-9]', '', name.lower().strip())

def record_to_list(s):
    # """Turn 'W-L-T' into [W, L, T]. If input is missing/malformed, pad with zeros."""
    if not s:
        return [0, 0, 0]
    nums = re.findall(r'\d+', str(s))
    nums = [int(n) for n in nums]
    if len(nums) < 3:
        nums += [0] * (3 - len(nums))
    return nums[:3]

def list_to_record(lst):
    return f"{lst[0]}-{lst[1]}-{lst[2]}"

def to_float(v):
    try:
        return float(v)
    except Exception:
        return 0.0

# --- load week1 results (file path as you use it) ---
with open("week_1_2025_results.json", "r") as f:
    week1_results = json.load(f)

# build lookup keyed by normalized team name
week1_lookup = { normalize_name(item.get("Team","")): item for item in week1_results }

# prepare sets for debug
teams_keys = { normalize_name(t.get("Team","")) for t in teams_data }
matched = []
unmatched = []
updated = []

# --- Merge week1 into teams_data in-place ---
for team in teams_data:
    team_name_raw = team.get("Team", "")
    key = normalize_name(team_name_raw)
    wk = week1_lookup.get(key)

    if not wk:
        unmatched.append(team_name_raw)
        continue

    # Update records: Overall, Matchup, Median Score
    for field in ("Overall Record", "Matchup Record", "Median Score Record"):
        existing = team.get(field, "0-0-0")
        wkrec = wk.get(field, "0-0-0")
        combined = [a + b for a, b in zip(record_to_list(existing), record_to_list(wkrec))]
        team[field] = list_to_record(combined)

    # Update PF / PA (ensure numeric)
    team["PF"] = round(to_float(team.get("PF", 0)) + to_float(wk.get("PF", 0)), 2)
    team["PA"] = round(to_float(team.get("PA", 0)) + to_float(wk.get("PA", 0)), 2)

    # store Wins/Losses/Ties for later use
    wins, losses, ties = record_to_list(team["Overall Record"])
    team["_wins_tmp"] = wins
    team["_losses_tmp"] = losses
    team["_ties_tmp"] = ties

    # recalc win percentage (keeps your format — change rounding if you want)
    total_games = wins + losses + ties
    team["Win %"] = round((wins + 0.5 * ties) / total_games if total_games > 0 else 0.0, 2)

    matched.append(team_name_raw)
    updated.append(team_name_raw)

# week1 teams that were not found in teams_data
week1_only = [t["Team"] for k, t in week1_lookup.items() if k not in teams_keys]

# --- Recompute leader (wins → PF → fewest losses fallback) ---
# ensure every team has tmp wins/losses (teams missing week1 may not have these tmp keys yet)
for team in teams_data:
    if "_wins_tmp" not in team:
        w, l, ti = record_to_list(team.get("Overall Record", "0-0-0"))
        team["_wins_tmp"], team["_losses_tmp"], team["_ties_tmp"] = w, l, ti
    # ensure PF numeric
    team["PF"] = to_float(team.get("PF", 0))

leader = max(
    teams_data,
    key=lambda x: (x["_wins_tmp"], x["PF"], -x["_losses_tmp"])
)
leader_wins = leader["_wins_tmp"]
leader_losses = leader["_losses_tmp"]

# --- Update GB in-place ---
for team in teams_data:
    if team is leader:
        team["GB"] = 0
    else:
        gb = ((leader_wins - team["_wins_tmp"]) + (team["_losses_tmp"] - leader_losses)) / 2
        team["GB"] = round(gb, 1)

# optional: remove temporary helper keys so teams_data shape stays the same as before
for team in teams_data:
    team.pop("_wins_tmp", None)
    team.pop("_losses_tmp", None)
    team.pop("_ties_tmp", None)







    # --- Parse wins/losses from "Overall Record" for each team ---
    for team in teams_data:
        wins, losses, ties = map(int, team["Overall Record"].split("-"))
        team["Wins"] = wins
        team["Losses"] = losses
        team["Ties"] = ties

    # --- Find the leader (wins → PF → fewer losses) ---
    leader = max(
        teams_data,
        key=lambda x: (x["Wins"], x["PF"], -x["Losses"])
    )
    leader_wins = leader["Wins"]
    leader_losses = leader["Losses"]

    # --- Update the GB value in the existing array ---
    for team in teams_data:
        if team == leader:
            team["GB"] = 0
        else:
            gb = ((leader_wins - team["Wins"]) + (team["Losses"] - leader_losses)) / 2
            team["GB"] = round(gb, 1)            


# --- Re-rank teams based on updated records --
def record_to_list(s):
    nums = re.findall(r'\d+', str(s))
    nums = [int(n) for n in nums]
    if len(nums) < 3:
        nums += [0] * (3 - len(nums))
    return nums[:3]

# sort teams by Wins (desc), then PF (desc)
teams_sorted = sorted(
    teams_data,
    key=lambda x: (record_to_list(x["Overall Record"])[0], x["PF"]),
    reverse=True
)

# assign ranks back into the original teams_data dicts
for i, team in enumerate(teams_sorted, start=1):
    # find the matching dict in teams_data
    for orig_team in teams_data:
        if orig_team["Team"].strip() == team["Team"].strip():
            orig_team["Rank"] = i
            break


# --- Write to JSON file ---
with open(OUTPUT_FILE, "w") as f:
    json.dump(teams_data, f, indent=2)

print(f"Data written to {OUTPUT_FILE}")
