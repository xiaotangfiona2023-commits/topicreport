import os
import argparse
import pandas as pd
import pulp


# =========================================================
# DEFAULT PATHS
# =========================================================
DEFAULT_DATA_DIR = r"C:\Users\Redmi\Desktop\topicreport\MILP_Operational Research\processed_timetabling\milp_out_sem1_unified"
DEFAULT_OPTIONS_FILE = "options_sem1_unified_for_milp.csv"


# =========================================================
# LOAD OPTIONS
# =========================================================
def load_existing_options(data_dir, filename):
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Options file not found: {path}")

    df = pd.read_csv(path).copy()

    required_cols = ["opt_id", "event_id", "day", "start_min", "end_min", "room_id"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns in options file: {missing}")

    # numeric
    df["start_min"] = pd.to_numeric(df["start_min"], errors="coerce")
    df["end_min"] = pd.to_numeric(df["end_min"], errors="coerce")
    df["day"] = pd.to_numeric(df["day"], errors="coerce")

    if "capacity" in df.columns:
        df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce")
    if "n_students" in df.columns:
        df["n_students"] = pd.to_numeric(df["n_students"], errors="coerce")
    if "capacity_gap" in df.columns:
        df["capacity_gap"] = pd.to_numeric(df["capacity_gap"], errors="coerce")

    # basic cleaning
    df = df.dropna(subset=["opt_id", "event_id", "day", "start_min", "end_min", "room_id"]).copy()

    df["event_id"] = df["event_id"].astype(str).str.strip()
    df["room_id"] = df["room_id"].astype(str).str.strip()
    df["opt_id"] = df["opt_id"].astype(str).str.strip()
    df["day"] = df["day"].astype(int)

    # derive slots
    df["slot_start"] = (df["start_min"] // 60).astype(int)
    df["slot_end"] = ((df["end_min"] + 59) // 60).astype(int)
    df = df[df["slot_end"] > df["slot_start"]].copy()

    # optional columns
    if "teaching_type" not in df.columns:
        df["teaching_type"] = "UNKNOWN"
    else:
        df["teaching_type"] = df["teaching_type"].astype(str).str.strip()

    if "school" not in df.columns:
        df["school"] = "UNKNOWN"
    else:
        df["school"] = df["school"].astype(str).str.strip()

    # baseline / preferred time
    baseline_candidates = [
        "baseline_slot_start", "baseline_start", "baseline_start_min",
        "preferred_start", "preferred_start_min"
    ]
    found_baseline = None
    for c in baseline_candidates:
        if c in df.columns:
            found_baseline = c
            break

    if found_baseline is not None:
        df[found_baseline] = pd.to_numeric(df[found_baseline], errors="coerce")
        if found_baseline == "baseline_slot_start":
            df["baseline_slot_start"] = df[found_baseline]
        else:
            df["baseline_slot_start"] = (df[found_baseline] // 60).astype("Int64")
    else:
        df["baseline_slot_start"] = pd.NA

    # if capacity_gap missing, calculate it
    if "capacity_gap" not in df.columns:
        if "capacity" in df.columns and "n_students" in df.columns:
            df["capacity_gap"] = df["capacity"] - df["n_students"]
        else:
            df["capacity_gap"] = pd.NA

    # very important: drop duplicated opt_id if any
    df = df.drop_duplicates(subset=["opt_id"]).copy()

    return df


# =========================================================
# SCENARIO FILTER
# =========================================================
def apply_scenario_filter(options, scenario):
    out = options.copy()

    if scenario == "S0":
        out = out[
            (out["slot_start"] >= 9) &
            (out["slot_end"] <= 18)
        ].copy()

    elif scenario == "S1":
        out = out[
            (out["slot_start"] >= 9) &
            (out["slot_end"] <= 17)
        ].copy()

    elif scenario == "S2":
        out = out[
            (
                (out["day"].isin([1, 2, 3, 4])) &
                (out["slot_start"] >= 9) &
                (out["slot_end"] <= 18)
            )
            |
            (
                (out["day"] == 5) &
                (out["slot_start"] >= 9) &
                (out["slot_end"] <= 12)
            )
        ].copy()
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    return out


# =========================================================
# POLICY FILTER
# =========================================================
def filter_policy(options):
    out = options.copy()

    # Arts-type schools should not take Practical / Laboratory
    arts_schools = [
        "Edinburgh College of Art",
        "School of History, Classics and Archaeology",
        "Moray House School of Education and Sport",
        "School of Literatures, Languages and Cultures",
    ]

    out = out[
        ~(
            (out["school"].isin(arts_schools)) &
            (out["teaching_type"].isin(["Practical", "Laboratory"]))
        )
    ].copy()

    return out


# =========================================================
# REDUCE OPTIONS PER EVENT
# =========================================================
def cap_options_per_event(options, keep_n=4):
    # prioritize: closer to baseline, smaller capacity gap, earlier start
    out = options.copy()

    if "capacity_gap" not in out.columns:
        out["capacity_gap"] = pd.NA

    if "baseline_slot_start" in out.columns:
        out["tmp_time_dist"] = (out["slot_start"] - out["baseline_slot_start"]).abs()
    else:
        out["tmp_time_dist"] = 0

    out["tmp_cap_gap_abs"] = pd.to_numeric(out["capacity_gap"], errors="coerce").abs()
    out["tmp_cap_gap_abs"] = out["tmp_cap_gap_abs"].fillna(999999)

    out = (
        out.sort_values(
            ["event_id", "tmp_time_dist", "tmp_cap_gap_abs", "day", "slot_start", "room_id"]
        )
        .groupby("event_id", group_keys=False)
        .head(keep_n)
        .copy()
    )

    out = out.drop(columns=["tmp_time_dist", "tmp_cap_gap_abs"], errors="ignore")
    return out


# =========================================================
# BUILD ROOM-SLOT ROWS
# =========================================================
def build_room_slot_rows(options):
    rows = []
    for _, r in options.iterrows():
        for s in range(int(r["slot_start"]), int(r["slot_end"])):
            rows.append({
                "opt_id": r["opt_id"],
                "room_id": r["room_id"],
                "day": r["day"],
                "slot": s
            })
    return pd.DataFrame(rows)


# =========================================================
# PREPARE OPTION FEATURES
# =========================================================
def add_objective_features(options):
    out = options.copy()

    out["duration_slots"] = out["slot_end"] - out["slot_start"]

    out["is_early"] = (out["slot_start"] < 10).astype(int)
    out["is_late"] = (out["slot_start"] >= 17).astype(int)

    out["is_lunch_overlap"] = (
        (out["slot_start"] < 14) & (out["slot_end"] > 12)
    ).astype(int)

    out["is_tutorial_morning"] = (
        (out["teaching_type"] == "Tutorial") &
        (out["slot_start"] < 12)
    ).astype(int)

    out["is_wholeclass_late"] = (
        (out["teaching_type"] == "Whole-Class") &
        (out["slot_start"] >= 15)
    ).astype(int)

    out["is_subgroup_like"] = out["teaching_type"].astype(str).str.contains(
        "Tutorial|Subgroup|Workshop|Seminar|Practical|Laboratory",
        case=False,
        na=False
    ).astype(int)

    out["is_whole_class"] = (out["teaching_type"] == "Whole-Class").astype(int)

    # Wednesday afternoon Whole-Class should be discouraged
    out["is_wed_pm_wholeclass"] = (
        (out["day"] == 3) &
        (out["slot_start"] >= 13) &
        (out["teaching_type"] == "Whole-Class")
    ).astype(int)

    # room waste
    if "capacity" in out.columns and "n_students" in out.columns:
        out["room_waste"] = (out["capacity"] - out["n_students"]).clip(lower=0)
        out["room_waste"] = out["room_waste"].fillna(0)
    else:
        out["room_waste"] = 0

    # room fill ratio
    if "capacity" in out.columns and "n_students" in out.columns:
        out["room_fill_ratio"] = out["n_students"] / out["capacity"]
        out["room_fill_ratio"] = out["room_fill_ratio"].replace([float("inf"), -float("inf")], pd.NA)
        out["room_fill_ratio"] = out["room_fill_ratio"].fillna(0)
    else:
        out["room_fill_ratio"] = 0

    # baseline closeness
    if "baseline_slot_start" in out.columns:
        out["time_distance"] = (out["slot_start"] - out["baseline_slot_start"]).abs()
        out["time_distance"] = out["time_distance"].fillna(0)
    else:
        out["time_distance"] = 0

    return out


# =========================================================
# SOLVE MILP
# =========================================================
def solve_milp(
    options,
    time_limit=60,
    weight_schedule=100,
    weight_wholeclass=5,
    weight_tutorial=3,
    penalty_lunch=0.5,
    penalty_tutorial_morning=0.3,
    penalty_wholeclass_late=0.6,
    penalty_early=0.2,
    penalty_late=0.2,
    penalty_room_waste=0.01,
    penalty_time_distance=0.2,
    reward_subgroup=0.2,
    penalty_wholeclass_extra=0.2,
    penalty_wed_pm_wholeclass=1.5,
    max_lunch_overlap=None,
    min_room_fill=0.30
):
    model = pulp.LpProblem("Timetable", pulp.LpMaximize)

    options = add_objective_features(options).reset_index(drop=True)
    opt_df = options.set_index("opt_id", drop=False)

    # Variables
    x = {o: pulp.LpVariable(f"x_{o}", cat="Binary") for o in options["opt_id"]}
    y = {e: pulp.LpVariable(f"y_{e}", cat="Binary") for e in options["event_id"].unique()}

    # =========================
    # EVENT ASSIGNMENT
    # =========================
    event_map = options.groupby("event_id")["opt_id"].apply(list).to_dict()
    for e, opt_list in event_map.items():
        model += pulp.lpSum(x[o] for o in opt_list) == y[e], f"assign_{e}"

    # =========================
    # ROOM NO CLASH
    # =========================
    room_slot_df = build_room_slot_rows(options)

    room_conflict_count = 0
    if not room_slot_df.empty:
        room_slot_map = (
            room_slot_df.groupby(["room_id", "day", "slot"])["opt_id"]
            .apply(list)
            .to_dict()
        )

        for (room, day, slot), opt_list in room_slot_map.items():
            if len(opt_list) >= 2:
                model += pulp.lpSum(x[o] for o in opt_list) <= 1, f"room_no_clash_{room}_{day}_{slot}"
                room_conflict_count += 1

    print("room conflict constraints:", room_conflict_count)

    # =========================
    # LUNCH OVERLAP LIMIT (SEMI-HARD)
    # =========================
    if max_lunch_overlap is not None:
        model += (
            pulp.lpSum(opt_df.loc[o, "is_lunch_overlap"] * x[o] for o in x)
            <= max_lunch_overlap
        ), "lunch_overlap_limit"

    # =========================
    # MIN ROOM FILL (HARD)
    # =========================
    min_room_fill_count = 0
    if "capacity" in options.columns and "n_students" in options.columns:
        for o in x:
            cap = opt_df.loc[o, "capacity"]
            stu = opt_df.loc[o, "n_students"]

            if pd.notna(cap) and pd.notna(stu) and cap > 0:
                if stu < min_room_fill * cap:
                    model += x[o] == 0, f"min_room_fill_{o}"
                    min_room_fill_count += 1

    print("min room fill exclusions:", min_room_fill_count)

    # =========================
    # OBJECTIVE
    # =========================
    type_map = options.groupby("event_id")["teaching_type"].first().to_dict()

    event_weight = {
        e: weight_wholeclass if type_map.get(e) == "Whole-Class"
        else weight_tutorial if type_map.get(e) == "Tutorial"
        else 1
        for e in y
    }

    obj = weight_schedule * pulp.lpSum(y[e] for e in y)
    obj += pulp.lpSum(event_weight[e] * y[e] for e in y)

    obj -= penalty_lunch * pulp.lpSum(opt_df.loc[o, "is_lunch_overlap"] * x[o] for o in x)
    obj -= penalty_tutorial_morning * pulp.lpSum(opt_df.loc[o, "is_tutorial_morning"] * x[o] for o in x)
    obj -= penalty_wholeclass_late * pulp.lpSum(opt_df.loc[o, "is_wholeclass_late"] * x[o] for o in x)
    obj -= penalty_early * pulp.lpSum(opt_df.loc[o, "is_early"] * x[o] for o in x)
    obj -= penalty_late * pulp.lpSum(opt_df.loc[o, "is_late"] * x[o] for o in x)
    obj -= penalty_room_waste * pulp.lpSum(opt_df.loc[o, "room_waste"] * x[o] for o in x)
    obj -= penalty_time_distance * pulp.lpSum(opt_df.loc[o, "time_distance"] * x[o] for o in x)

    obj += reward_subgroup * pulp.lpSum(opt_df.loc[o, "is_subgroup_like"] * x[o] for o in x)
    obj -= penalty_wholeclass_extra * pulp.lpSum(opt_df.loc[o, "is_whole_class"] * x[o] for o in x)

    # discourage Whole-Class on Wednesday afternoon
    obj -= penalty_wed_pm_wholeclass * pulp.lpSum(
        opt_df.loc[o, "is_wed_pm_wholeclass"] * x[o] for o in x
    )

    model += obj, "policy_objective"

    solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=time_limit)
    model.solve(solver)

    selected = [
        o for o in options["opt_id"]
        if pulp.value(x[o]) is not None and pulp.value(x[o]) > 0.5
    ]

    result = options[options["opt_id"].isin(selected)].copy()
    return result, model


# =========================================================
# MAIN
# =========================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="S1", choices=["S0", "S1", "S2"])
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--options-file", default=DEFAULT_OPTIONS_FILE)
    parser.add_argument("--keep-per-event", type=int, default=4)
    parser.add_argument("--time-limit", type=int, default=60)

    # objective weights
    parser.add_argument("--weight-schedule", type=float, default=100)
    parser.add_argument("--weight-wholeclass", type=float, default=5)
    parser.add_argument("--weight-tutorial", type=float, default=3)
    parser.add_argument("--penalty-lunch", type=float, default=0.5)
    parser.add_argument("--penalty-tutorial-morning", type=float, default=0.3)
    parser.add_argument("--penalty-wholeclass-late", type=float, default=0.6)
    parser.add_argument("--penalty-early", type=float, default=0.2)
    parser.add_argument("--penalty-late", type=float, default=0.2)
    parser.add_argument("--penalty-room-waste", type=float, default=0.01)
    parser.add_argument("--penalty-time-distance", type=float, default=0.2)
    parser.add_argument("--reward-subgroup", type=float, default=0.2)
    parser.add_argument("--penalty-wholeclass-extra", type=float, default=0.2)
    parser.add_argument("--penalty-wed-pm-wholeclass", type=float, default=1.5)

    # new hard / semi-hard controls
    parser.add_argument("--max-lunch-overlap", type=int, default=None)
    parser.add_argument("--min-room-fill", type=float, default=0.30)

    args = parser.parse_args()

    # Load
    options = load_existing_options(args.data_dir, args.options_file)
    print("raw options:", len(options))

    # Filters
    options = apply_scenario_filter(options, args.scenario)
    print("after scenario filter:", len(options))

    options = filter_policy(options)
    print("after policy filter:", len(options))

    options = cap_options_per_event(options, keep_n=args.keep_per_event)
    print("after per-event cap:", len(options))

    # Solve
    result, model = solve_milp(
        options=options,
        time_limit=args.time_limit,
        weight_schedule=args.weight_schedule,
        weight_wholeclass=args.weight_wholeclass,
        weight_tutorial=args.weight_tutorial,
        penalty_lunch=args.penalty_lunch,
        penalty_tutorial_morning=args.penalty_tutorial_morning,
        penalty_wholeclass_late=args.penalty_wholeclass_late,
        penalty_early=args.penalty_early,
        penalty_late=args.penalty_late,
        penalty_room_waste=args.penalty_room_waste,
        penalty_time_distance=args.penalty_time_distance,
        reward_subgroup=args.reward_subgroup,
        penalty_wholeclass_extra=args.penalty_wholeclass_extra,
        penalty_wed_pm_wholeclass=args.penalty_wed_pm_wholeclass,
        max_lunch_overlap=args.max_lunch_overlap,
        min_room_fill=args.min_room_fill
    )

    print("DONE, scheduled:", len(result))
    print("n_constraints:", len(model.constraints))

    # Save outputs
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "outputs", args.scenario)
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, f"schedule_{args.scenario}.csv")
    result.to_csv(output_path, index=False)
    print("Saved schedule to:", output_path)


if __name__ == "__main__":
    main()