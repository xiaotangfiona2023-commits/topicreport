from pathlib import Path
import pandas as pd
# =========================================================
# PATHS
# =========================================================
BASE_DIR = Path(r"C:\Users\Redmi\Desktop\topicreport")
SCHEDULE_DIR = BASE_DIR / "later" / "outputs"
ANALYSIS_OPTIONS_FILE = Path(
    r"C:\Users\Redmi\Desktop\topicreport\MILP_Operational Research\processed_timetabling\milp_out_sem1_unified\options_sem1_unified_with_students.csv"
)

OUT_DIR = BASE_DIR / "later" / "student_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCENARIOS = ["S0", "S1", "S2"]

# =========================================================
# HELPERS
# =========================================================
def has_overlap(a_start, a_end, b_start, b_end):
    return not (a_end <= b_start or b_end <= a_start)

def mins_to_hhmm(x):
    if pd.isna(x):
        return ""
    x = int(x)
    h = x // 60
    m = x % 60
    return f"{h:02d}:{m:02d}"

# =========================================================
# LOAD ANALYSIS OPTIONS
# =========================================================
analysis_opts = pd.read_csv(ANALYSIS_OPTIONS_FILE)

for c in ["opt_id", "event_id", "student_id", "programme", "student_department"]:
    if c in analysis_opts.columns:
        analysis_opts[c] = analysis_opts[c].astype(str).str.strip()

for c in ["day", "start_min", "end_min", "slot_start", "slot_end"]:
    if c in analysis_opts.columns:
        analysis_opts[c] = pd.to_numeric(analysis_opts[c], errors="coerce")

lookup_cols = [c for c in [
    "opt_id", "event_id", "student_id", "programme", "student_department"
] if c in analysis_opts.columns]

lookup = analysis_opts[lookup_cols].drop_duplicates().copy()
print("analysis lookup shape:", lookup.shape)



# =========================================================
# MAIN LOOP
# =========================================================
all_summary_rows = []

for scenario in SCENARIOS:
    schedule_file = SCHEDULE_DIR / scenario / f"schedule_{scenario}.csv"

    if not schedule_file.exists():
        print(f"[Skip] schedule file not found: {schedule_file}")
        continue

    print(f"\n=== Processing {scenario} ===")

    schedule_df = pd.read_csv(schedule_file)

    if "opt_id" not in schedule_df.columns or "event_id" not in schedule_df.columns:
        raise KeyError(f"{schedule_file} must contain opt_id and event_id")

    for c in ["opt_id", "event_id", "room_id", "teaching_type", "school"]:
        if c in schedule_df.columns:
            schedule_df[c] = schedule_df[c].astype(str).str.strip()

    for c in ["day", "start_min", "end_min", "slot_start", "slot_end"]:
        if c in schedule_df.columns:
            schedule_df[c] = pd.to_numeric(schedule_df[c], errors="coerce")

    # =====================================================
    # Attach students back to selected schedule
    # =====================================================
    schedule_with_students = schedule_df.merge(
        lookup,
        on=["opt_id", "event_id"],
        how="left"
    )

    schedule_with_students["student_id"] = schedule_with_students["student_id"].fillna("").astype(str).str.strip()
    schedule_with_students["programme"] = schedule_with_students["programme"].fillna("Unknown").astype(str).str.strip()

    if "student_department" in schedule_with_students.columns:
        schedule_with_students["student_department"] = (
            schedule_with_students["student_department"]
            .fillna("Unknown")
            .astype(str)
            .str.strip()
        )

    # nice time strings
    if "start_min" in schedule_with_students.columns:
        schedule_with_students["start_time"] = schedule_with_students["start_min"].apply(mins_to_hhmm)
    if "end_min" in schedule_with_students.columns:
        schedule_with_students["end_time"] = schedule_with_students["end_min"].apply(mins_to_hhmm)

    out_schedule = OUT_DIR / f"schedule_{scenario}_with_students.csv"
    schedule_with_students.to_csv(out_schedule, index=False)
    print("saved schedule with students:", out_schedule)
    print("shape:", schedule_with_students.shape)

    # =====================================================
    # Student clash detection
    # =====================================================
    valid = schedule_with_students[schedule_with_students["student_id"].ne("")].copy()

    clash_detail_rows = []
    student_summary_rows = []

    lunch_start = 12 * 60
    lunch_end = 14 * 60

    for sid, grp in valid.groupby("student_id"):
        grp = grp.dropna(subset=["day", "start_min", "end_min"]).copy()
        grp = grp.drop_duplicates(subset=["opt_id"]).copy()
        grp = grp.sort_values(["day", "start_min", "end_min"])

        clash_count = 0
        clash_pairs = []

        # check overlaps day by day
        for day, gday in grp.groupby("day"):
            gday = gday.sort_values(["start_min", "end_min"]).reset_index(drop=True)

            for i in range(len(gday)):
                r1 = gday.iloc[i]
                for j in range(i + 1, len(gday)):
                    r2 = gday.iloc[j]

                    if r2["start_min"] >= r1["end_min"]:
                        break

                    if has_overlap(r1["start_min"], r1["end_min"], r2["start_min"], r2["end_min"]):
                        clash_count += 1
                        clash_pairs.append({
                            "scenario": scenario,
                            "student_id": sid,
                            "programme": r1.get("programme", "Unknown"),
                            "day": day,
                            "event_id_1": r1["event_id"],
                            "start_1": r1["start_min"],
                            "end_1": r1["end_min"],
                            "room_1": r1.get("room_id", ""),
                            "event_id_2": r2["event_id"],
                            "start_2": r2["start_min"],
                            "end_2": r2["end_min"],
                            "room_2": r2.get("room_id", "")
                        })

        # lunch analysis
        days_considered = 0
        free_lunch_days = 0

        for day, gday in grp.groupby("day"):
            days_considered += 1
            overlap_any = False

            for _, r in gday.iterrows():
                if has_overlap(r["start_min"], r["end_min"], lunch_start, lunch_end):
                    overlap_any = True
                    break

            if not overlap_any:
                free_lunch_days += 1

        has_majority_lunch = 1 if days_considered > 0 and (free_lunch_days / days_considered) > 0.5 else 0
        has_clash = 1 if clash_count > 0 else 0

        student_summary_rows.append({
            "scenario": scenario,
            "student_id": sid,
            "programme": grp["programme"].iloc[0] if "programme" in grp.columns and len(grp) > 0 else "Unknown",
            "n_scheduled_events": grp["event_id"].nunique(),
            "clash_count": clash_count,
            "has_clash": has_clash,
            "days_considered": days_considered,
            "free_lunch_days": free_lunch_days,
            "has_majority_lunch": has_majority_lunch
        })

        clash_detail_rows.extend(clash_pairs)

    clash_df = pd.DataFrame(clash_detail_rows)
    student_summary_df = pd.DataFrame(student_summary_rows)

    out_clash = OUT_DIR / f"student_clash_details_{scenario}.csv"
    out_student_summary = OUT_DIR / f"student_summary_{scenario}.csv"

    clash_df.to_csv(out_clash, index=False)
    student_summary_df.to_csv(out_student_summary, index=False)

    print("saved clash details:", out_clash)
    print("saved student summary:", out_student_summary)

    # =====================================================
    # Scenario-level summary
    # =====================================================
    n_students = student_summary_df["student_id"].nunique() if not student_summary_df.empty else 0
    n_students_with_clash = int(student_summary_df["has_clash"].sum()) if not student_summary_df.empty else 0
    clash_rate = n_students_with_clash / n_students if n_students > 0 else 0

    n_majority_lunch = int(student_summary_df["has_majority_lunch"].sum()) if not student_summary_df.empty else 0
    majority_lunch_rate = n_majority_lunch / n_students if n_students > 0 else 0

    all_summary_rows.append({
        "scenario": scenario,
        "schedule_rows_with_students": len(schedule_with_students),
        "scheduled_unique_events": schedule_df["event_id"].nunique(),
        "students_in_analysis": n_students,
        "students_with_clash": n_students_with_clash,
        "clash_rate": clash_rate,
        "students_with_majority_lunch": n_majority_lunch,
        "majority_lunch_rate": majority_lunch_rate
    })


# =========================================================
# SAVE OVERALL SUMMARY
# =========================================================
summary_all_df = pd.DataFrame(all_summary_rows)
out_summary_all = OUT_DIR / "student_summary_all_scenarios.csv"
summary_all_df.to_csv(out_summary_all, index=False)

print("\nSaved overall summary:", out_summary_all)
print(summary_all_df)
print("\nDone.")