This repository contains the code, notebook, and essential project files for our timetabling feasibility project. The aim of the project is to construct and evaluate policy-compliant university timetables under different teaching-hour scenarios, using data preparation, optimisation modelling, and post-analysis.

The repository includes the main workflow required to reproduce the project logic, including:

- raw-data preparation and preprocessing
- construction of optimisation inputs
- timetable generation under different scenarios
- student-level attachment and clash analysis
- post-analysis of timetable results
**Important Note on Large Files**

Some CSV files produced during this project are **not included in this GitHub repository** because they exceed GitHub’s file size limit.
GitHub does not allow standard uploads of files larger than 100 MB. Several of our generated CSV outputs are larger than this limit, especially those containing:

- processed optimisation candidate tables
- student-attached timetable outputs
- large intermediate merged datasets
These omitted files are **generated outputs rather than handwritten source code**. Their absence does **not** mean the project is incomplete. The repository still contains the full project structure, scripts, notebooks, and reproducible workflow needed to regenerate those outputs locally.
In other words:
- the **source code and workflow are included**
- the **very large generated CSV outputs are excluded**
- the **full CSV outputs can be recreated by running the Python notebook/scripts locally**

## Reproducibility Note

The complete large CSV outputs can be regenerated locally by running the included notebook and Python scripts in sequence, provided that the required input files are placed in the expected folders.

Please note that some scripts may contain local absolute paths written for the original development environment. If so, these paths should be adjusted to match the user’s local machine before execution.

## Project Structure

### 1. `Project_data preparation/`

This folder contains the **data preparation and preprocessing stage** of the project.

Main contents include:

- `Project.ipynb`  
  The main notebook used to clean, restructure, and prepare the original raw timetabling data.

- `data/`  
  Stores the original input data files used for preprocessing.

- `processed_timetabling/`  
  Stores processed outputs generated from the notebook, including cleaned and structured data tables used later in optimisation.

This stage converts the original raw data into a format suitable for timetable construction and optimisation.

### 2. `MILP_Operational Research/`

This folder contains the **optimisation-related implementation**.

Main contents include:

- `faster2.py`  
  A core script used to generate and filter candidate scheduling options for the optimisation workflow. This includes event-time-room combinations and other processed inputs required by the model.

- `data/`  
  Contains input data files needed for the optimisation stage.

- `processed_timetabling/`  
  Contains processed optimisation inputs and candidate option tables. Some outputs in this folder can become very large and are therefore not fully uploaded to GitHub.

This stage connects the cleaned data to the timetable optimisation model.

### 3. `later/`

This folder contains the **scenario execution, student-level attachment, and post-analysis stage**.

Main contents include:

- `run_s1_s2_standalone.py`  
  Runs the scenario-based optimisation or timetable generation workflow for policy settings such as S0, S1, and S2.

- `attach_students_to_schedules.py`  
  Attaches student-level information to generated schedule outputs so that clash analysis and programme-level analysis can be performed.

- `student_post_analysis.py`  
  Conducts post-analysis on student timetable outputs and generates summary results.

- `outputs/`  
  Stores scenario-level timetable outputs.

- `student_outputs/`  
  Stores student-level schedule outputs and clash-related files. Some files in this folder are too large for GitHub and therefore are not included in full.

This stage focuses on downstream evaluation of timetable quality and student impact.

## Suggested Execution Order

To reproduce the workflow and regenerate the omitted large CSV outputs, the following order is recommended:

### Step 1: Data preparation
Run the notebook in:
`Project_data preparation/Project.ipynb`

This step prepares and cleans the raw input data.

### Step 2: Build optimisation inputs
Run:
`MILP_Operational Research/faster2.py`

This step generates processed candidate option tables and optimisation-ready inputs.

### Step 3: Run timetable scenarios
Run:
`later/run_s1_s2_standalone.py`

This step applies scenario settings and generates timetable outputs.

### Step 4: Attach student information
Run:
`later/attach_students_to_schedules.py`

This step creates student-level timetable files and clash-related outputs.

### Step 5: Post-analysis
Run:
`later/student_post_analysis.py`

This step generates post-analysis results based on the student-level outputs.


## About the Omitted CSV Files

The omitted CSV files are mainly large generated outputs, such as:

- candidate option tables for optimisation
- merged student-schedule output tables
- large processed intermediate datasets

These files were excluded only because of GitHub storage restrictions, not because they are missing from the project workflow.

If required, the complete outputs can be obtained in one of the following ways:

1. regenerate them locally by running the included notebook/scripts
2. request them separately through external cloud storage if needed


This repository was prepared as part of our project submission on timetabling feasibility under policy constraints.
