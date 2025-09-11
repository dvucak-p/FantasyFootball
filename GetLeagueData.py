import os
import re
import json
import math
from espn_api.football import League
from pathlib import Path
from datetime import datetime

# --- CONFIG ---
LEAGUE_ID = 487404
YEAR = 2025
OUTPUT_FILE = Path("LeagueData.json")

# Get credentials from environment
SWID, ESPN_S2 = os.getenv("SWID"), os.getenv("ESPN_S2")
if not SWID or not ESPN_S2:
    raise ValueError("Missing SWID or ESPN_S2 environment variables")

# Connect to league
league = League(league_id=LEAGUE_ID, year=YEAR, swid=SWID, espn_s2=ESPN_S2)


# --- Helpers ---
def normalize_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (name or "").lower().strip())

def record_to_list(s: str) -> list[int]:
    nums = [int(n) for n in re.findall(r'\d+', str(s))]
    return (nums + [0, 0, 0])[:3]

def list_to_record(lst: list[int]) -> str:
    return "-".join(map(str, lst))

def to_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


# --- Median W/L Record ---
def get_median_records(l: League) -> dict:
    median_records = {t.team_id: {"wins": 0, "losses": 0} for t in l.teams}
    max_week = min(l.current_week + 1, 14)

    for week in range(1, max_week):
        try:
            box_scores = l.box_scores(week)
        except KeyError:
            continue

        scores = [s for b in box_scores for s in (b.home_score, b.away_score) if s is not None]
        if not scores:
            continue

        scores.sort()
        mid = len(scores) // 2
        median = (scores[mid - 1] + scores[mid]) / 2 if len(scores) % 2 == 0 else scores[mid]

        for b in box_scores:
            for team, score in [(b.home_team, b.home_score), (b.away_team, b.away_score)]:
                if team:
                    key = "wins" if score >= median else "losses"
                    median_records[team.team_id][key] += 1

    return median_records


median_records = get_median_records(league)

# --- Collect Team Data ---
first_place_wins = max(t.wins for t in league.teams)
teams_data = []

for t in league.teams:
    wl_record = f"{t.wins}-{t.losses}-{t.ties}"
    median_record = median_records[t.team_id]
    median_str = f"{median_record['wins']}-{median_record['losses']}-0"

    overall = [a + b for a, b in zip(record_to_list(wl_record), record_to_list(median_str))]

    teams_data.append({
        "Rank": t.standing,
        "Team": t.team_name,
        "Overall Record": list_to_record(overall),
        "Matchup Record": wl_record,
        "Median Score Record": median_str,
        "GB": "-" if t.wins == first_place_wins else first_place_wins - t.wins,
        "PF": round(t.points_for, 2),
        "PA": round(t.points_against, 2),
        "Acquisition Budget": 100 - t.acquisition_budget_spent,
        "Team Logo": t.logo_url
        # Win % will be calculated later
    })


# --- Merge Week 1 Results ---
with open("week_1_2025_results.json") as f:
    week1_lookup = {normalize_name(d["Team"]): d for d in json.load(f)}

for team in teams_data:
    wk = week1_lookup.get(normalize_name(team["Team"]))
    if not wk:
        continue

    for field in ("Overall Record", "Matchup Record", "Median Score Record"):
        combined = [a + b for a, b in zip(record_to_list(team[field]), record_to_list(wk.get(field, "0-0-0")))]
        team[field] = list_to_record(combined)

    team["PF"] = round(to_float(team["PF"]) + to_float(wk.get("PF", 0)), 2)
    team["PA"] = round(to_float(team["PA"]) + to_float(wk.get("PA", 0)), 2)


# --- Calculate Win % after all merges ---
for team in teams_data:
    w, l, ti = record_to_list(team["Overall Record"])
    total = w + l + ti
    team["Win %"] = round((w + 0.5 * ti) / total, 2) if total else 0.0


# --- Recompute Leader & GB ---
leader = max(
    teams_data,
    key=lambda x: (record_to_list(x["Overall Record"])[0], x["PF"], -record_to_list(x["Overall Record"])[1])
)
lw, ll, _ = record_to_list(leader["Overall Record"])

for t in teams_data:
    w, l, _ = record_to_list(t["Overall Record"])
    t["GB"] = 0 if t is leader else round(((lw - w) + (l - ll)) / 2, 1)


# --- Re-Rank Teams ---
teams_sorted = sorted(teams_data, key=lambda x: (record_to_list(x["Overall Record"])[0], x["PF"]), reverse=True)
for i, t in enumerate(teams_sorted, 1):
    next(team for team in teams_data if normalize_name(team["Team"]) == normalize_name(t["Team"]))["Rank"] = i


# --- Save ---
with open(OUTPUT_FILE, "w") as f:
    json.dump(teams_data, f, indent=2)

print(f"Data written to {OUTPUT_FILE}")
