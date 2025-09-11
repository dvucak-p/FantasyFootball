import os
import re
import json
from espn_api.football import League
from pathlib import Path
from datetime import datetime

# --- CONFIG ---
LEAGUE_ID = 487404
YEAR = 2025
OUTPUT_FILE = Path("LeagueData.json")
WEEK1_FILE = "week_1_2025_results.json"

# Auth
SWID, ESPN_S2 = os.getenv("SWID"), os.getenv("ESPN_S2")
if not SWID or not ESPN_S2:
    raise ValueError("Missing SWID or ESPN_S2 environment variables")

# --- Helpers ---
def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().strip())

def record_to_list(s: str) -> list:
    nums = [int(n) for n in re.findall(r"\d+", str(s))]
    return (nums + [0, 0, 0])[:3]

def list_to_record(lst: list) -> str:
    return "-".join(map(str, lst))

def to_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0

def find_wk_value(wk: dict, candidates: list, default=None):
    """Find a value in wk by trying exact keys then substring matches."""
    if not isinstance(wk, dict):
        return default
    # exact names first
    for k in candidates:
        if k in wk and wk[k] not in (None, ""):
            return wk[k]
    # fallback: case-insensitive substring match on keys
    low_candidates = [c.lower().replace("_", "").replace(" ", "") for c in candidates]
    for key in wk:
        small = key.lower().replace("_", "").replace(" ", "")
        for cand in low_candidates:
            if cand in small:
                return wk[key]
    return default

# --- Median W/L Record ---
def get_median_records(l: League) -> dict:
    median_records = {t.team_id: {"wins": 0, "losses": 0} for t in l.teams}
    max_week = min(getattr(l, "current_week", 0) + 1, 14)

    # iterate weeks starting at 1 (was accidentally starting at 2)
    for week in range(1, max_week):
        try:
            box_scores = l.box_scores(week)
        except Exception:
            continue

        # only consider non-null scores
        scores = [s for b in box_scores for s in (b.home_score, b.away_score) if s is not None]
        if not scores:
            continue

        scores.sort()
        mid = len(scores) // 2
        median = (scores[mid - 1] + scores[mid]) / 2 if len(scores) % 2 == 0 else scores[mid]

        for b in box_scores:
            for team, score in ((b.home_team, b.home_score), (b.away_team, b.away_score)):
                if team is None or score is None:
                    continue
                key = "wins" if score >= median else "losses"
                median_records[team.team_id][key] += 1

    return median_records

# --- Main flow ---
def main():
    league = League(league_id=LEAGUE_ID, year=YEAR, swid=SWID, espn_s2=ESPN_S2)
    median_records = get_median_records(league)

    # Build base teams_data from API
    teams_data = []
    for t in league.teams:
        wl_record = f"{t.wins}-{t.losses}-{t.ties}"
        med = median_records.get(t.team_id, {"wins": 0, "losses": 0})
        med_str = f"{med['wins']}-{med['losses']}-0"
        overall = [a + b for a, b in zip(record_to_list(wl_record), record_to_list(med_str))]

        teams_data.append({
            "team_id": t.team_id,
            "Rank": t.standing,
            "Team": t.team_name,
            "Overall Record": list_to_record(overall),
            "Matchup Record": wl_record,
            "Median Score Record": med_str,
            "GB": "-",  # placeholder; will be recalculated after merges
            "PF": round(to_float(t.points_for), 2),
            "PA": round(to_float(t.points_against), 2),
            "Acquisition Budget": 100 - getattr(t, "acquisition_budget_spent", 0),
            "Team Logo": getattr(t, "logo_url", None)
        })

    # --- Load week 1 static file and build robust lookup ---
    try:
        with open(WEEK1_FILE, "r") as f:
            week1_list = json.load(f)
    except Exception:
        week1_list = []

    # Build mapping from multiple possible keys (normalized team name, team_id)
    week1_lookup = {}
    week1_primary_keys = []  # keep original dicts + primary key for later detection
    if isinstance(week1_list, list):
        for wk in week1_list:
            # gather candidate name strings
            candidates = []
            for k in ("Team", "team", "team_name", "Team Name", "teamName"):
                val = wk.get(k)
                if val:
                    candidates.append(normalize_name(val))
            # add team_id if present
            if "team_id" in wk and wk["team_id"] not in (None, ""):
                candidates.append(normalize_name(str(wk["team_id"])))
            # if we found at least one key, map them to wk
            if candidates:
                primary = candidates[0]
                week1_primary_keys.append(primary)
                for c in candidates:
                    week1_lookup[c] = wk

    # Merge week1 data into teams_data (robust matching by name or team_id)
    matched_wk_keys = set()
    for team in teams_data:
        key_name = normalize_name(team.get("Team", ""))
        # try by team name then team_id
        wk = week1_lookup.get(key_name)
        if wk is None and team.get("team_id") is not None:
            wk = week1_lookup.get(normalize_name(str(team["team_id"])))

        if not wk:
            continue

        # mark matched (using primary key fallback)
        matched_wk_keys.add(key_name)

        # merge record fields robustly (try likely key names and fallback)
        def get_wk_record_field(field_label, default="0-0-0"):
            exact_names = {
                "Overall Record": ["Overall Record", "overall_record", "Overall_Record", "combined_record", "combined record", "combinedRecord", "OverallRecord"],
                "Matchup Record": ["Matchup Record", "matchup_record", "Matchup_Record", "matchup record", "MatchupRecord"],
                "Median Score Record": ["Median Score Record", "median_record", "Median_Record", "median score record", "MedianRecord"]
            }
            return find_wk_value(wk, exact_names.get(field_label, []), default)

        for field in ("Overall Record", "Matchup Record", "Median Score Record"):
            existing = team.get(field, "0-0-0")
            wkrec = get_wk_record_field(field, "0-0-0")
            combined = [a + b for a, b in zip(record_to_list(existing), record_to_list(wkrec))]
            team[field] = list_to_record(combined)

        # PF / PA merging (try common keys)
        pf_val = find_wk_value(wk, ["PF", "pf", "points_for", "pointsfor", "Points For"], 0)
        pa_val = find_wk_value(wk, ["PA", "pa", "points_against", "pointsagainst", "Points Against"], 0)
        team["PF"] = round(to_float(team.get("PF", 0)) + to_float(pf_val), 2)
        team["PA"] = round(to_float(team.get("PA", 0)) + to_float(pa_val), 2)

    # Append any week1-only teams that weren't matched to existing teams_data
    if isinstance(week1_list, list):
        for wk in week1_list:
            # deduce primary key the same way as earlier
            primary = None
            for k in ("Team", "team", "team_name", "Team Name", "teamName"):
                if wk.get(k):
                    primary = normalize_name(wk.get(k))
                    break
            if primary is None and "team_id" in wk:
                primary = normalize_name(str(wk["team_id"]))
            if primary is None:
                continue
            if primary in matched_wk_keys:
                continue  # already merged
            # Build a minimal team dict from the week1 file so it appears in the output
            wl = find_wk_value(wk, ["Overall Record", "overall_record", "combined_record"], "0-0-0")
            matchup = find_wk_value(wk, ["Matchup Record", "matchup_record", "matchup"], "0-0-0")
            median = find_wk_value(wk, ["Median Score Record", "median_record", "median"], "0-0-0")
            pf_val = find_wk_value(wk, ["PF", "pf", "points_for"], 0)
            pa_val = find_wk_value(wk, ["PA", "pa", "points_against"], 0)

            teams_data.append({
                "team_id": wk.get("team_id"),
                "Rank": None,
                "Team": (wk.get("Team") or wk.get("team") or wk.get("team_name") or "Unknown"),
                "Overall Record": wl,
                "Matchup Record": matchup,
                "Median Score Record": median,
                "GB": "-",
                "PF": round(to_float(pf_val), 2),
                "PA": round(to_float(pa_val), 2),
                "Acquisition Budget": wk.get("Acquisition Budget", 100),
                "Team Logo": wk.get("Team Logo") or wk.get("logo_url")
            })
            matched_wk_keys.add(primary)

    # --- Calculate Win % after all merges ---
    for team in teams_data:
        w, l, ti = record_to_list(team.get("Overall Record", "0-0-0"))
        total = w + l + ti
        team["Win %"] = round((w + 0.5 * ti) / total, 2) if total else 0.0

    # --- Recompute Leader & GB ---
    # ensure PF numeric
    for team in teams_data:
        team["PF"] = to_float(team.get("PF", 0))
        team["PA"] = to_float(team.get("PA", 0))

    leader = max(
        teams_data,
        key=lambda x: (record_to_list(x.get("Overall Record", "0-0-0"))[0], x.get("PF", 0), -record_to_list(x.get("Overall Record", "0-0-0"))[1])
    )
    lw, ll, _ = record_to_list(leader.get("Overall Record", "0-0-0"))

    for t in teams_data:
        w, l, _ = record_to_list(t.get("Overall Record", "0-0-0"))
        t["GB"] = 0 if t is leader else round(((lw - w) + (l - ll)) / 2, 1)

    # --- Re-Rank Teams ---
    teams_sorted = sorted(teams_data, key=lambda x: (record_to_list(x.get("Overall Record", "0-0-0"))[0], x.get("PF", 0)), reverse=True)
    for i, t in enumerate(teams_sorted, 1):
        # assign rank on matching normalized team name
        name = normalize_name(t.get("Team", ""))
        for orig in teams_data:
            if normalize_name(orig.get("Team", "")) == name:
                orig["Rank"] = i
                break

    # --- Save ---
    # remove internal team_id if you don't want it in output, otherwise keep it
    with open(OUTPUT_FILE, "w") as f:
        json.dump(teams_data, f, indent=2)

    print(f"Data written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
