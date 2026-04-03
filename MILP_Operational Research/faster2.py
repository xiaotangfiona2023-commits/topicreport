import os
from pathlib import Path
import pandas as pd


# =========================================================
# PATHS
# =========================================================
BASE_DIR = Path(r"D:\UOE\topics\topicreport\MILP_Operational Research")
PROCESSED_DIR = BASE_DIR / "processed_timetabling"

# Original auxiliary files
EVENT_ROOM_XLSX = Path(r"D:\UOE\topics\topicreport\Project_data preparation\data\2024-5 Event Module Room.xlsx")
STUDENT_XLSX = Path(r"D:\UOE\topics\topicreport\Project_data preparation\data\2024-5 Student Programme Module Event.xlsx")

# Preprocessed CSV files
EVENTS_FILE = PROCESSED_DIR / "events_master_schedulable.csv"
ROOM_OPTS_FILE = PROCESSED_DIR / "event_room_options.csv"
ALLOWED_TIMES_FILE = PROCESSED_DIR / "allowed_start_times_S0.csv"   # Used as a unified candidate time pool

# Output directory
OUT_DIR = PROCESSED_DIR / "milp_out_sem1_unified"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_MILP = OUT_DIR / "options_sem1_unified_for_milp.csv"
OUT_ANALYSIS = OUT_DIR / "options_sem1_unified_with_students.csv"


# =========================================================
# HELPERS
# =========================================================
def find_col(df, candidates, required=True):
    """Finds a column name in a dataframe based on a list of candidate strings."""
    lower_map = {str(c).lower().strip(): c for c in df.columns}

    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]

    for c in df.columns:
        cl = str(c).lower().strip()
        for cand in candidates:
            if cand.lower() in cl:
                return c

    if required:
        raise KeyError(
            f"Cannot find any of these columns: {candidates}\n"
            f"Actual columns: {list(df.columns)}"
        )
    return None


def normalize_day_value(x):
    """Maps various weekday string/numeric representations to 1-5."""
    if pd.isna(x):
        return None
    s = str(x).strip().lower()
    mapping = {
        "1": 1, "mon": 1, "monday": 1,
        "2": 2, "tue": 2, "tues": 2, "tuesday": 2,
        "3": 3, "wed": 3, "wednesday": 3,
        "4": 4, "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
        "5": 5, "fri": 5, "friday": 5,
    }
    return mapping.get(s, None)


def normalize_semester_value(x):
    """Maps semester strings/numbers to integers 1 or 2."""
    if pd.isna(x):
        return None
    s = str(x).strip().lower()
    mapping = {
        "1": 1, "semester 1": 1, "sem 1": 1, "s1": 1,
        "2": 2, "semester 2": 2, "sem 2": 2, "s2": 2,
    }
    return mapping.get(s, None)


def normalize_teaching_type(event_type, whole_class):
    """Categorizes teaching activities based on event type and class size indicator."""
    et = "" if pd.isna(event_type) else str(event_type).strip()
    wc = "" if pd.isna(whole_class) else str(whole_class).strip().lower()

    if wc in ["yes", "true", "1"]:
        return "Whole-Class"

    et_low = et.lower()

    if "tutorial" in et_low:
        return "Tutorial"
    if "subgroup" in et_low or "small group" in et_low or "group" in et_low:
        return "Subgroup"
    if "lecture" in et_low or "whole class" in et_low or "plenary" in et_low:
        return "Whole-Class"
    if "practical" in et_low:
        return "Practical"
    if "laboratory" in et_low or "lab" in et_low:
        return "Laboratory"
    if et.strip() == "":
        return "Unknown"

    return et


# =========================================================
# TOP-N TIME FILTER
# =========================================================
def restrict_top_times(times, event_col, baseline_col=None, start_col="start_min", top_n=3):
    """Filters the top N time slots for each event based on proximity to a baseline."""
    out = times.copy()

    out[start_col] = pd.to_numeric(out[start_col], errors="coerce")

    if baseline_col is not None and baseline_col in out.columns:
        out[baseline_col] = pd.to_numeric(out[baseline_col], errors="coerce")
        out["time_distance"] = (out[start_col] - out[baseline_col]).abs()
    else:
        out["time_distance"] = 0

    out = out.sort_values(by=[event_col, "day", "time_distance", start_col]).copy()
    out = out.groupby(event_col, group_keys=False).head(top_n).copy()

    return out


# =========================================================
# TOP-K ROOM FILTER
# =========================================================
def restrict_top_rooms(room_opts, event_col, room_col, top_k=2):
    """Filters the top K room options for each event based on capacity fit."""
    out = room_opts.copy()

    if "capacity" in out.columns:
        out["capacity"] = pd.to_numeric(out["capacity"], errors="coerce")
    if "n_students" in out.columns:
        out["n_students"] = pd.to_numeric(out["n_students"], errors="coerce")

    if "capacity" in out.columns and "n_students" in out.columns:
        out["capacity_gap"] = (out["capacity"] - out["n_students"]).abs()
    else:
        out["capacity_gap"] = 0

    out = out.sort_values(by=[event_col, "capacity_gap", room_col]).copy()
    out = out.groupby(event_col, group_keys=False).head(top_k).copy()

    return out


# =========================================================
# BUILD OPTIONS
# Preserve as many original columns as possible
# =========================================================
def build_options(events, times, room_opts, event_col, room_col, day_col, start_col, end_col):
    """Joins events, times, and rooms to create a comprehensive list of scheduling options."""
    # Keep original columns for events
    event_keep = list(events.columns)
    if event_col not in event_keep:
        event_keep.append(event_col)

    et = events[event_keep].drop_duplicates(subset=[event_col]).merge(
        times.drop_duplicates(subset=[event_col, day_col, start_col, end_col]),
        on=event_col,
        how="inner"
    )

    # Keep original columns for rooms
    room_keep = list(room_opts.columns)
    if event_col not in room_keep:
        room_keep.append(event_col)

    er = room_opts[room_keep].drop_duplicates()

    options = et.merge(er, on=event_col, how="inner").copy()
    options = options.reset_index(drop=True)
    options["opt_id"] = [f"OPT_{i}" for i in range(len(options))]

    # Standardize key column names
    if day_col != "day":
        options = options.rename(columns={day_col: "day"})
    if start_col != "start_min":
        options = options.rename(columns={start_col: "start_min"})
    if end_col != "end_min":
        options = options.rename(columns={end_col: "end_min"})
    if room_col != "room_id":
        options = options.rename(columns={room_col: "room_id"})

    # Numeric conversion
    options["day"] = pd.to_numeric(options["day"], errors="coerce")
    options["start_min"] = pd.to_numeric(options["start_min"], errors="coerce")
    options["end_min"] = pd.to_numeric(options["end_min"], errors="coerce")

    if "capacity" in options.columns:
        options["capacity"] = pd.to_numeric(options["capacity"], errors="coerce")
    if "n_students" in options.columns:
        options["n_students"] = pd.to_numeric(options["n_students"], errors="coerce")

    # Basic data cleaning
    options = options.dropna(subset=["event_id", "day", "start_min", "end_min", "room_id"]).copy()
    options["day"] = options["day"].astype(int)

    # Hour slots
    options["slot_start"] = (options["start_min"] // 60).astype(int)
    options["slot_end"] = ((options["end_min"] + 59) // 60).astype(int)

    # Calculate capacity gap
    if "capacity" in options.columns and "n_students" in options.columns:
        options["capacity_gap"] = options["capacity"] - options["n_students"]
    else:
        options["capacity_gap"] = pd.NA

    return options


# =========================================================
# LOAD BASE TABLES
# =========================================================
print("Loading processed files...")
events = pd.read_csv(EVENTS_FILE)
room_opts = pd.read_csv(ROOM_OPTS_FILE)
times = pd.read_csv(ALLOWED_TIMES_FILE)

print("events shape:", events.shape)
print("room_opts shape:", room_opts.shape)
print("times shape:", times.shape)

print("\nevents columns:")
print(events.columns.tolist())

print("\nroom_opts columns:")
print(room_opts.columns.tolist())

print("\ntimes columns:")
print(times.columns.tolist())


# =========================================================
# DETECT KEY COLUMNS
# =========================================================
event_col_events = find_col(events, ["event_id", "event", "evt_id"])
event_col_rooms = find_col(room_opts, ["event_id", "event", "evt_id"])
event_col_times = find_col(times, ["event_id", "event", "evt_id"])

room_col = find_col(room_opts, ["room_id", "room", "room_code"])
day_col = find_col(times, ["day", "day_num", "weekday"])
start_col = find_col(times, ["start_min", "start", "slot_start", "start_hour"])
end_col = find_col(times, ["end_min", "end", "slot_end", "end_hour"], required=False)

semester_col = find_col(events, ["semester", "semester_no", "term"], required=False)
baseline_col = find_col(times, ["baseline_start", "baseline_start_min", "baseline_slot_start"], required=False)

# Standardize event_id
if event_col_events != "event_id":
    events = events.rename(columns={event_col_events: "event_id"})
if event_col_rooms != "event_id":
    room_opts = room_opts.rename(columns={event_col_rooms: "event_id"})
if event_col_times != "event_id":
    times = times.rename(columns={event_col_times: "event_id"})

event_col = "event_id"

# Standardize day column
times[day_col] = times[day_col].apply(normalize_day_value)

# Time column normalization
times[start_col] = pd.to_numeric(times[start_col], errors="coerce")
if end_col is not None:
    times[end_col] = pd.to_numeric(times[end_col], errors="coerce")

if start_col == "slot_start":
    times["start_min"] = times["slot_start"] * 60
    start_col = "start_min"

if end_col == "slot_end":
    times["end_min"] = times["slot_end"] * 60
    end_col = "end_min"

if end_col is None:
    times["end_min"] = times[start_col] + 60
    end_col = "end_min"


# =========================================================
# FILTER SEMESTER 1 ONLY
# =========================================================
print("\nFiltering Semester 1 only...")

if semester_col is None:
    raise KeyError("No semester column found in events file, cannot select Semester 1.")

events["_semester_norm"] = events[semester_col].apply(normalize_semester_value)
before_events = len(events)
events = events[events["_semester_norm"] == 1].copy()
print(f"events: {before_events} -> {len(events)}")

# Align event_id across all tables
events["event_id"] = events["event_id"].astype(str).str.strip()
room_opts["event_id"] = room_opts["event_id"].astype(str).str.strip()
times["event_id"] = times["event_id"].astype(str).str.strip()

valid_events = set(events["event_id"].unique())
times = times[times["event_id"].isin(valid_events)].copy()
room_opts = room_opts[room_opts["event_id"].isin(valid_events)].copy()

print("times after semester alignment:", times.shape)
print("room_opts after semester alignment:", room_opts.shape)


# =========================================================
# BASIC CLEANING
# =========================================================
times = times[
    times["event_id"].notna() &
    times[day_col].notna() &
    times[start_col].notna() &
    times[end_col].notna()
].copy()

room_opts["room_id"] = room_opts[room_col].astype(str).str.strip()

print("\nAfter basic cleaning:")
print("times rows:", len(times))
print("room_opts rows:", len(room_opts))


# =========================================================
# TOP-N / TOP-K
# =========================================================
TOP_N = 3
TOP_K = 2

times_top = restrict_top_times(
    times=times,
    event_col=event_col,
    baseline_col=baseline_col,
    start_col=start_col,
    top_n=TOP_N
)

room_top = restrict_top_rooms(
    room_opts=room_opts,
    event_col=event_col,
    room_col=room_col,
    top_k=TOP_K
)

print("\nAfter Top-N / Top-K:")
print("times_top rows:", len(times_top))
print("room_top rows:", len(room_top))
print("times_top unique events:", times_top["event_id"].nunique())
print("room_top unique events:", room_top["event_id"].nunique())


# =========================================================
# BUILD OPTIONS
# =========================================================
print("\nBuilding Semester 1 unified options...")
opts = build_options(
    events=events,
    times=times_top,
    room_opts=room_top,
    event_col=event_col,
    room_col=room_col,
    day_col=day_col,
    start_col=start_col,
    end_col=end_col
)

print("opts shape:", opts.shape)
print("unique events:", opts["event_id"].nunique())

print("\nopts columns:")
print(opts.columns.tolist())

show_cols = [c for c in ["event_id", "room_id", "capacity", "n_students", "capacity_gap"] if c in opts.columns]
print("\nSample capacity-related columns:")
print(opts[show_cols].head())


# =========================================================
# ADD TEACHING TYPE + SCHOOL
# =========================================================
print("\nLoading event-room metadata...")
event_room_df = pd.read_excel(EVENT_ROOM_XLSX, sheet_name="2024-5 Event Module Room")

print("event_room_df columns:")
print(event_room_df.columns.tolist())

event_id_col_er = find_col(event_room_df, ["Event ID", "event_id", "event id", "event"])
event_type_col = find_col(event_room_df, ["Event Type", "event_type", "event type"], required=False)
whole_class_col = find_col(event_room_df, ["WholeClass", "wholeclass", "whole class"], required=False)
school_col = find_col(
    event_room_df,
    ["Module Department", "school", "college", "department", "module department"],
    required=False
)

event_room_df[event_id_col_er] = event_room_df[event_id_col_er].astype(str).str.strip()

lookup_event = event_room_df[[event_id_col_er]].drop_duplicates().copy()
lookup_event = lookup_event.rename(columns={event_id_col_er: "event_id"})

if event_type_col is not None:
    lookup_event["Event Type"] = event_room_df[event_type_col]
else:
    lookup_event["Event Type"] = pd.NA

if whole_class_col is not None:
    lookup_event["WholeClass"] = event_room_df[whole_class_col]
else:
    lookup_event["WholeClass"] = pd.NA

if school_col is not None:
    lookup_event["school"] = event_room_df[school_col]
else:
    lookup_event["school"] = "Unknown"

lookup_event["teaching_type"] = [
    normalize_teaching_type(et, wc)
    for et, wc in zip(lookup_event["Event Type"], lookup_event["WholeClass"])
]

lookup_event = lookup_event[["event_id", "teaching_type", "school"]].drop_duplicates()

# Remove existing columns if present before merging
for c in ["teaching_type", "school"]:
    if c in opts.columns:
        opts = opts.drop(columns=[c])

opts = opts.merge(lookup_event, on="event_id", how="left")
opts["teaching_type"] = opts["teaching_type"].fillna("Unknown")
opts["school"] = opts["school"].fillna("Unknown")


# =========================================================
# RECOMPUTE CAPACITY GAP
# =========================================================
print("\nRecomputing capacity_gap...")

if "capacity" in opts.columns:
    opts["capacity"] = pd.to_numeric(opts["capacity"], errors="coerce")
if "n_students" in opts.columns:
    opts["n_students"] = pd.to_numeric(opts["n_students"], errors="coerce")

if "capacity" in opts.columns and "n_students" in opts.columns:
    opts["capacity_gap"] = opts["capacity"] - opts["n_students"]
else:
    print("Warning: capacity or n_students missing; capacity_gap set to NA.")
    opts["capacity_gap"] = pd.NA

show_cols = [c for c in ["event_id", "capacity", "n_students", "capacity_gap"] if c in opts.columns]
print(opts[show_cols].head())


# =========================================================
# SAVE MILP VERSION
# Do not expand students
# =========================================================
opts_for_milp = opts.drop_duplicates().copy()
opts_for_milp.to_csv(OUT_MILP, index=False)

print("\nSaved MILP-ready Semester 1 options to:")
print(OUT_MILP)
print("MILP shape:", opts_for_milp.shape)


# =========================================================
# ADD STUDENT / PROGRAMME / DEPARTMENT
# =========================================================
print("\nLoading student-event table...")
student_df = pd.read_excel(STUDENT_XLSX, sheet_name=0)

print("Student file columns:")
print(student_df.columns.tolist())

# Hardcoded column names for student data
event_id_col_stu = "Event ID"
student_id_col = "AnonID"
programme_col = "Programme"
department_col = "Department"
semester_col_stu = "Semester"

student_df[event_id_col_stu] = student_df[event_id_col_stu].astype(str).str.strip()
student_df[student_id_col] = student_df[student_id_col].astype(str).str.strip()
student_df[programme_col] = student_df[programme_col].astype(str).str.strip()
student_df[department_col] = student_df[department_col].astype(str).str.strip()
student_df[semester_col_stu] = student_df[semester_col_stu].astype(str).str.strip()

# Retain only Semester 1 records
student_df = student_df[
    student_df[semester_col_stu].str.contains("1", case=False, na=False)
].copy()

student_lookup = (
    student_df[[event_id_col_stu, student_id_col, programme_col, department_col]]
    .drop_duplicates()
    .rename(columns={
        event_id_col_stu: "event_id",
        student_id_col: "student_id",
        programme_col: "programme",
        department_col: "student_department"
    })
)

opts_for_analysis = opts.merge(student_lookup, on="event_id", how="left")
opts_for_analysis["student_id"] = opts_for_analysis["student_id"].fillna("")
opts_for_analysis["programme"] = opts_for_analysis["programme"].fillna("Unknown")
opts_for_analysis["student_department"] = opts_for_analysis["student_department"].fillna("Unknown")

opts_for_analysis.to_csv(OUT_ANALYSIS, index=False)

print("\nSaved student-analysis Semester 1 options to:")
print(OUT_ANALYSIS)
print("Analysis shape:", opts_for_analysis.shape)


# =========================================================
# SUMMARY
# =========================================================
print("\n===== SUMMARY =====")
print("MILP columns:")
print(opts_for_milp.columns.tolist())

milp_show = [c for c in [
    "opt_id", "event_id", "day", "start_min", "end_min", "room_id",
    "teaching_type", "school", "capacity", "n_students", "capacity_gap"
] if c in opts_for_milp.columns]
print("\nSample MILP rows:")
print(opts_for_milp[milp_show].head())

analysis_show = [c for c in [
    "opt_id", "event_id", "day", "start_min", "end_min", "room_id",
    "student_id", "programme", "student_department",
    "teaching_type", "school", "capacity", "n_students", "capacity_gap"
] if c in opts_for_analysis.columns]
print("\nSample analysis rows:")
print(opts_for_analysis[analysis_show].head())

print("\nDone.")