from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

# =========================================================
# PATHS
# =========================================================
BASE_DIR = Path(r"C:\Users\Redmi\Desktop\topicreport")

ATTACH_DIR = BASE_DIR / "later" / "student_outputs"

ANALYSIS_DIR = BASE_DIR / "later" / "analysis"
CORE_DIR = ANALYSIS_DIR / "core_outputs"
SUPPORT_DIR = ANALYSIS_DIR / "supporting_outputs"

CORE_DIR.mkdir(parents=True, exist_ok=True)
SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

SCENARIOS = ["S0", "S1", "S2"]

FINAL_SCENARIO = "S2"
SELECTED_STUDENT = "Student00004"

MAX_DISPLAY_EVENTS = 8
MIN_TIME_GAP_FOR_DISPLAY = 90


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


def day_name(x):
    mapping = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"}
    if pd.isna(x):
        return ""
    return mapping.get(int(x), str(x))


def load_schedule_with_students(scenario):
    f = ATTACH_DIR / f"schedule_{scenario}_with_students.csv"
    if not f.exists():
        raise FileNotFoundError(f"Attached schedule file not found: {f}")

    df = pd.read_csv(f)

    str_cols = [
        "opt_id", "event_id", "room_id", "teaching_type", "school",
        "student_id", "programme", "student_department"
    ]
    for c in str_cols:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    num_cols = [
        "day", "start_min", "end_min", "slot_start", "slot_end",
        "capacity", "n_students"
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    if "day_name" not in df.columns and "day" in df.columns:
        df["day_name"] = df["day"].apply(day_name)

    if "start_time" not in df.columns and "start_min" in df.columns:
        df["start_time"] = df["start_min"].apply(mins_to_hhmm)

    if "end_time" not in df.columns and "end_min" in df.columns:
        df["end_time"] = df["end_min"].apply(mins_to_hhmm)

    return df


def pick_well_spread_classes(df, max_events=8, min_gap=90):

    if df.empty:
        return df.copy()

    tmp = df.drop_duplicates(subset=["opt_id"]).copy()
    tmp = tmp.sort_values(["day", "start_min", "end_min"]).reset_index(drop=True)

    selected_idx = []
    selected_points = []

    for i, r in tmp.iterrows():
        cur_day = r["day"]
        cur_start = r["start_min"]

        ok = True
        for d, s in selected_points:
            if d == cur_day and abs(cur_start - s) < min_gap:
                ok = False
                break

        if ok:
            selected_idx.append(i)
            selected_points.append((cur_day, cur_start))

        if len(selected_idx) >= max_events:
            break

    if len(selected_idx) < min(max_events, len(tmp)):
        remain = [i for i in range(len(tmp)) if i not in selected_idx]
        need = min(max_events, len(tmp)) - len(selected_idx)
        selected_idx.extend(remain[:need])

    out = tmp.iloc[selected_idx].copy()
    out = out.sort_values(["day", "start_min", "end_min"]).copy()
    return out


def plot_bar_with_zoom(values, labels, title, xlabel, ylabel, save_path,
                       decimals=3, pad_ratio=0.15, min_pad=0.01):

    values = [float(v) for v in values]

    plt.figure(figsize=(6, 4))
    bars = plt.bar(labels, values)

    vmin = min(values)
    vmax = max(values)
    vrange = vmax - vmin

    if vrange == 0:
        pad = min_pad
    else:
        pad = max(vrange * pad_ratio, min_pad)

    lower = vmin - pad
    upper = vmax + pad

    if lower == upper:
        upper = lower + min_pad

    plt.ylim(lower, upper)

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)

    for bar, v in zip(bars, values):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            v,
            f"{v:.{decimals}f}",
            ha="center",
            va="bottom",
            fontsize=9
        )

    plt.tight_layout()
    plt.savefig(save_path, dpi=200)
    plt.close()


# =========================================================
# ANALYSE EACH SCENARIO
# =========================================================
summary_rows = []
programme_rows = []
student_summary_all = []
schedule_students_by_scenario = {}

for scenario in SCENARIOS:
    print(f"\n=== Analysing {scenario} ===")

    schedule_students = load_schedule_with_students(scenario)
    schedule_students_by_scenario[scenario] = schedule_students.copy()

    valid = schedule_students.copy()
    if "student_id" in valid.columns:
        valid = valid[valid["student_id"].ne("")].copy()
    else:
        valid["student_id"] = ""
        valid = valid.iloc[0:0].copy()

    # -----------------------------------------------------
    # Student-level clash + lunch
    # -----------------------------------------------------
    student_rows = []

    lunch_start = 12 * 60
    lunch_end = 14 * 60

    for sid, grp in valid.groupby("student_id"):
        grp = grp.dropna(subset=["day", "start_min", "end_min"]).copy()
        grp = grp.drop_duplicates(subset=["opt_id"]).copy()
        grp = grp.sort_values(["day", "start_min", "end_min"])

        clash_count = 0

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

        student_rows.append({
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

    student_summary_df = pd.DataFrame(student_rows)
    student_summary_all.append(student_summary_df)

    # -----------------------------------------------------
    # Programme coverage
    # -----------------------------------------------------
    if not valid.empty and "programme" in valid.columns:
        prog_df = (
            valid[["programme", "event_id"]]
            .drop_duplicates()
            .groupby("programme")["event_id"]
            .nunique()
            .reset_index(name="scheduled_event_count")
        )
    else:
        prog_df = pd.DataFrame(columns=["programme", "scheduled_event_count"])

    prog_df["scenario"] = scenario
    programme_rows.append(prog_df)

    # Room utilisation
    if not schedule_students.empty:
        schedule_unique = schedule_students.drop_duplicates(subset=["opt_id"]).copy()
    else:
        schedule_unique = schedule_students.copy()

    if not schedule_unique.empty:
        room_level = (
            schedule_unique.groupby("room_id")
            .agg(n_events=("event_id", "count"))
            .reset_index()
        )
        avg_events_per_room = room_level["n_events"].mean() if not room_level.empty else 0
    else:
        avg_events_per_room = 0

    tmp_room = schedule_unique.copy()
    if "start_min" in tmp_room.columns and "end_min" in tmp_room.columns and not tmp_room.empty:
        tmp_room["duration_min"] = tmp_room["end_min"] - tmp_room["start_min"]
        room_minutes = (
            tmp_room.groupby("room_id")["duration_min"]
            .sum()
            .reset_index(name="used_minutes")
        )
        avg_used_minutes_per_room = room_minutes["used_minutes"].mean() if not room_minutes.empty else 0
    else:
        avg_used_minutes_per_room = 0

    if "n_students" in schedule_unique.columns and "capacity" in schedule_unique.columns and not schedule_unique.empty:
        occ = schedule_unique.copy()
        occ["occupancy_ratio"] = occ["n_students"] / occ["capacity"]
        occ["occupancy_ratio"] = occ["occupancy_ratio"].replace([float("inf"), -float("inf")], pd.NA)
        occ["occupancy_ratio"] = occ["occupancy_ratio"].clip(lower=0)
        avg_occupancy_ratio = occ["occupancy_ratio"].dropna().mean()
        if pd.isna(avg_occupancy_ratio):
            avg_occupancy_ratio = 0
    else:
        avg_occupancy_ratio = 0

    # -----------------------------------------------------
    # Scenario summary
    # -----------------------------------------------------
    n_students = student_summary_df["student_id"].nunique() if not student_summary_df.empty else 0
    n_students_with_clash = int(student_summary_df["has_clash"].sum()) if not student_summary_df.empty else 0
    clash_rate = n_students_with_clash / n_students if n_students > 0 else 0

    avg_clash_count = student_summary_df["clash_count"].mean() if not student_summary_df.empty else 0

    n_majority_lunch = int(student_summary_df["has_majority_lunch"].sum()) if not student_summary_df.empty else 0
    majority_lunch_rate = n_majority_lunch / n_students if n_students > 0 else 0

    summary_rows.append({
        "scenario": scenario,
        "scheduled_rows": len(schedule_unique),
        "scheduled_unique_events": schedule_unique["event_id"].nunique() if not schedule_unique.empty else 0,
        "students_in_analysis": n_students,
        "students_with_clash": n_students_with_clash,
        "clash_rate": clash_rate,
        "avg_clash_count": avg_clash_count,
        "students_with_majority_lunch": n_majority_lunch,
        "majority_lunch_rate": majority_lunch_rate,
        "n_programmes": prog_df["programme"].nunique() if not prog_df.empty else 0,
        "avg_events_per_room": avg_events_per_room,
        "avg_used_minutes_per_room": avg_used_minutes_per_room,
        "avg_occupancy_ratio": avg_occupancy_ratio
    })


# =========================================================
# SAVE TABLES
# =========================================================
summary_df = pd.DataFrame(summary_rows)
programme_df = pd.concat(programme_rows, ignore_index=True) if programme_rows else pd.DataFrame()
student_summary_full = pd.concat(student_summary_all, ignore_index=True) if student_summary_all else pd.DataFrame()

summary_df.to_csv(CORE_DIR / "student_summary_by_scenario.csv", index=False)

programme_df.to_csv(SUPPORT_DIR / "programme_coverage_by_scenario.csv", index=False)
student_summary_full.to_csv(SUPPORT_DIR / "student_level_summary_all_scenarios.csv", index=False)

print("\nSaved summary tables.")
print(summary_df)


# =========================================================
# VISUALISATIONS - SCENARIO COMPARISON
# =========================================================
# 1. scheduled events (core)
plot_bar_with_zoom(
    values=summary_df["scheduled_unique_events"].tolist(),
    labels=summary_df["scenario"].tolist(),
    title="Scheduled Unique Events by Scenario",
    xlabel="Scenario",
    ylabel="Scheduled Unique Events",
    save_path=CORE_DIR / "scheduled_events_by_scenario.png",
    decimals=0,
    pad_ratio=0.10,
    min_pad=50
)

# 2. clash rate (core)
plot_bar_with_zoom(
    values=summary_df["clash_rate"].tolist(),
    labels=summary_df["scenario"].tolist(),
    title="Student Clash Rate by Scenario",
    xlabel="Scenario",
    ylabel="Clash Rate",
    save_path=CORE_DIR / "student_clash_rate_by_scenario.png",
    decimals=3,
    pad_ratio=0.20,
    min_pad=0.003
)

# 3. majority lunch rate (core)
plot_bar_with_zoom(
    values=summary_df["majority_lunch_rate"].tolist(),
    labels=summary_df["scenario"].tolist(),
    title="Majority Lunch Rate by Scenario",
    xlabel="Scenario",
    ylabel="Rate",
    save_path=CORE_DIR / "majority_lunch_rate_by_scenario.png",
    decimals=3,
    pad_ratio=0.20,
    min_pad=0.01
)

# 4. average clash count (supporting)
plot_bar_with_zoom(
    values=summary_df["avg_clash_count"].tolist(),
    labels=summary_df["scenario"].tolist(),
    title="Average Clash Count per Student",
    xlabel="Scenario",
    ylabel="Average Clash Count",
    save_path=SUPPORT_DIR / "avg_clash_count_by_scenario.png",
    decimals=2,
    pad_ratio=0.20,
    min_pad=0.05
)

# 5. average events per room (core)
plot_bar_with_zoom(
    values=summary_df["avg_events_per_room"].tolist(),
    labels=summary_df["scenario"].tolist(),
    title="Average Events per Room by Scenario",
    xlabel="Scenario",
    ylabel="Average Events per Room",
    save_path=CORE_DIR / "avg_events_per_room_by_scenario.png",
    decimals=2,
    pad_ratio=0.20,
    min_pad=0.2
)

# 6. average room occupancy ratio (core)
plot_bar_with_zoom(
    values=summary_df["avg_occupancy_ratio"].tolist(),
    labels=summary_df["scenario"].tolist(),
    title="Average Room Occupancy Ratio by Scenario",
    xlabel="Scenario",
    ylabel="Average Occupancy Ratio",
    save_path=CORE_DIR / "avg_room_occupancy_ratio_by_scenario.png",
    decimals=3,
    pad_ratio=0.20,
    min_pad=0.005
)

# 7. top 10 programme coverage (supporting)
if not programme_df.empty:
    top_programmes = (
        programme_df.groupby("programme")["scheduled_event_count"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .index.tolist()
    )

    plot_prog = programme_df[programme_df["programme"].isin(top_programmes)].copy()

    if not plot_prog.empty:
        pivot_prog = plot_prog.pivot(
            index="programme",
            columns="scenario",
            values="scheduled_event_count"
        ).fillna(0)

        pivot_prog.plot(kind="bar", figsize=(10, 5))
        plt.title("Top 10 Programme Coverage by Scenario")
        plt.xlabel("Programme")
        plt.ylabel("Scheduled Event Count")
        plt.tight_layout()
        plt.savefig(SUPPORT_DIR / "programme_coverage_top10_by_scenario.png", dpi=200)
        plt.close()


# =========================================================
# FINAL STUDENT TIMETABLE - ONLY FINAL SCENARIO
# =========================================================
print("\nSelected student:", SELECTED_STUDENT)
print("Final scenario for display:", FINAL_SCENARIO)

final_sched = schedule_students_by_scenario[FINAL_SCENARIO].copy()
one_student = final_sched[final_sched["student_id"] == SELECTED_STUDENT].copy()
one_student = one_student.drop_duplicates(subset=["opt_id"]).copy()
one_student = one_student.sort_values(["day", "start_min", "end_min"]).copy()

if one_student.empty:
    print(f"Warning: {SELECTED_STUDENT} not found in {FINAL_SCENARIO}.")
else:
    full_out = SUPPORT_DIR / f"selected_student_timetable_{FINAL_SCENARIO}.csv"
    one_student.to_csv(full_out, index=False)

    display_student = pick_well_spread_classes(
        one_student,
        max_events=MAX_DISPLAY_EVENTS,
        min_gap=MIN_TIME_GAP_FOR_DISPLAY
    )
    display_out = SUPPORT_DIR / f"selected_student_timetable_display_subset_{FINAL_SCENARIO}.csv"
    display_student.to_csv(display_out, index=False)

    plt.figure(figsize=(10, 5))

    for _, r in display_student.iterrows():
        y = r["day"]
        x1 = r["start_min"] / 60
        x2 = r["end_min"] / 60
        plt.plot([x1, x2], [y, y], linewidth=9)
        plt.text(
            (x1 + x2) / 2,
            y + 0.12,
            str(r["event_id"]),
            fontsize=7,
            ha="center"
        )

    plt.title(f"{FINAL_SCENARIO} Timetable for {SELECTED_STUDENT}")
    plt.yticks([1, 2, 3, 4, 5], ["Mon", "Tue", "Wed", "Thu", "Fri"])
    plt.xlim(8.5, 18.5)
    plt.xlabel("Time (hour)")
    plt.tight_layout()
    plt.savefig(SUPPORT_DIR / f"selected_student_timetable_{FINAL_SCENARIO}.png", dpi=200)
    plt.close()

    daily = (
        one_student.groupby("day")["event_id"]
        .nunique()
        .reset_index(name="n_events")
    )
    daily["day_name"] = daily["day"].apply(day_name)

    plt.figure(figsize=(7, 4))
    plt.bar(daily["day_name"], daily["n_events"])
    plt.title(f"Daily Load for {SELECTED_STUDENT} ({FINAL_SCENARIO})")
    plt.xlabel("Day")
    plt.ylabel("Number of Scheduled Events")
    plt.tight_layout()
    plt.savefig(SUPPORT_DIR / f"selected_student_daily_load_{FINAL_SCENARIO}.png", dpi=200)
    plt.close()

print("\nAll outputs saved to:")
print("Core outputs:", CORE_DIR)
print("Supporting outputs:", SUPPORT_DIR)
print("Done.")
