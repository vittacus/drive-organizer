# Google Drive Organizer

An AI-powered script that categorizes and reorganizes a messy Google Drive into a clean, semester-based folder structure using Claude and the Google Drive API.

---

## Problem Statement

Google Drive's default behavior is essentially a flat pile. Files accumulate over years with no structure — course assignments mixed with résumés, mixed with DiversaTech budgets, mixed with photos from a weekend trip. After four years of college, a Drive with 2,500+ files is effectively unsearchable. The real cost isn't storage — it's the minutes lost every time you try to find something specific.

Manual organization is deferred indefinitely because it's tedious, not because it's hard. The insight here is that the *decision* about where a file should go is cheap for a language model and expensive for a human. The actual file move is a one-line API call. So the right architecture is: use AI for classification, use automation for execution.

---

## User Persona

**Andrew Vitt** — UC Berkeley senior (graduating SP26), president of DiversaTech, double-concentrating in IEOR and Data Science. Accumulates files from three categories simultaneously:

- **Academic**: lecture notes, problem sets, projects, and exams across 20+ courses spanning eight semesters
- **Organizational**: DiversaTech budgets, event planning docs, recruitment materials, and partnership decks shared with 40+ members
- **Personal/Professional**: résumés, cover letters, bank statements, and photos

The persona has strong opinions about folder names (IEOR 142A, not INDENG 142A) and course-semester accuracy (CS 61B was SP25, not SP26) but no patience for doing the organization manually. Technically comfortable enough to run a Python script, but not interested in maintaining one.

---

## Solution Overview

`organizer.py` fetches every file in the user's Drive, sends them to Claude in batches of 15 for categorical classification, then moves each file to the appropriate folder — creating the folder hierarchy on the fly if it doesn't exist.

The folder taxonomy:

```
School/
  FA22/ SP23/ FA23/ SP24/ FA24/ SP25/ FA25/ SP26/
    CS 61B/  ECON 140/  LEGALST 149/ ...
DiversaTech/
  SP26/
    Finance/ Events/ Recruitment/ Operations/ Marketing/ General/
Work & Internships/
Personal/
Finance/
Photos & Media/
```

The run is resumable: processed file IDs are saved to `progress.json` after every batch, so an interrupted run picks up exactly where it left off. A `DRY_RUN` flag lets you preview every move before anything is touched.

---

## Technical Decisions and Tradeoffs

### Three-Layer Semester Pipeline

Semester assignment is the hardest part of the classification problem. A file named `HW3.pdf` carries almost no temporal signal. The solution stacks three layers, each overriding the previous:

1. **File dates (primary)** — `createdTime` from the Drive API, or `modifiedTime` if the file was modified 6+ months after creation (indicating it was reworked in a later semester). Maps to Berkeley's academic calendar: months 1–7 → Spring, months 8–12 → Fall.

2. **Claude's guess (fallback)** — Used only when the Drive API returns no date, which is rare but happens for some migrated files.

3. **`COURSE_SEMESTER_MAP` (final authority)** — A hardcoded dictionary of known course→semester facts specific to the user. `CS 61B → SP25` regardless of what the file date says. This layer wins unconditionally.

The tradeoff: this pipeline is deterministic for known courses and probabilistic for everything else. A file with `createdTime` of March 2024 will land in SP24 even if it was actually created during spring break for a fall course. The alternative — prompting Claude with full date context — was tested but produced inconsistent results and added latency to every batch.

### Batch Prompting vs. Per-File Prompting

Files are sent to Claude in batches of 15. This was a cost and latency decision: per-file prompting would be ~15× more expensive and slower. The tradeoff is that Claude has less context per file — it can't ask clarifying questions or compare files against each other. In practice, batch accuracy was high enough that the post-processing normalization layer caught most edge cases.

### Course Name Normalization

Two separate dictionaries handle naming:

- **`COURSE_NORMALIZATIONS`** — fixes variant names Claude might return (`CS61B → CS 61B`, `Anthropology → Anthro 2AC`). Applied as the first post-processing step.
- **`COURSE_SEMESTER_MAP`** — maps the canonical name to the correct semester. Applied last.

These are separate because the normalization problem (spelling) and the temporal problem (when was it taken) are logically independent. Conflating them would make both dictionaries harder to maintain.

### Config-Driven Design

All personal data — course history, owner name, organizational context — lives in `config.json`, which is gitignored. The committed repo contains only `config.example.json`. Anyone can clone the repo, fill in their own courses, and run it without modifying source code. The tradeoff is a setup step that requires users to understand the JSON schema.

### Handling Unowned Files

The Drive API returns all files visible to a user, including those shared with them. Owned files are moved by changing their parent folder. Unowned files can only have a folder *added* as an additional parent (Drive's version of a shortcut). In practice, this mostly fails with `"Increasing the number of parents is not allowed"` — a Drive API restriction on files shared from organizational accounts (e.g., DiversaTech shared docs). These files are logged as skipped but don't block the rest of the run.

---

## Key Metrics from the Run

Across a full pass of a 4-year Drive:

| Metric | Value |
|---|---|
| Total files found | 2,583 |
| Successfully categorized and moved | ~480 |
| Skipped (unowned/permission errors) | ~2,095 |
| Batches processed | 173 |
| API retry events (rate limits) | ~8 batch failures, all recovered |
| Empty folders deleted (post-run cleanup) | TBD |

**Skipped rate is high by design.** The majority of files in the Drive are shared DiversaTech documents owned by the org account — they show up in the file listing but can't be moved by a non-owner. The ~480 successfully moved files represent essentially the entire owned-file corpus.

**Top destination folders** (from initial pass):
- `Photos & Media` — 204 files
- `Work & Internships` — 72 files  
- `School/SP26/COLWRIT N132` — 24 files
- `School/SP26/INDENG 120` — 18 files
- `Personal` — 33 files

---

## Limitations

**Shared files can't be moved.** Files owned by an organizational Google account (e.g., the DiversaTech Drive) show up in your personal Drive listing but are immovable. The script logs these and moves on. This accounts for roughly 80% of the "skipped" count.

**Filename ambiguity.** Files with generic names (`HW3.pdf`, `Midterm.docx`, `Notes`) carry no course signal. These rely entirely on the creation date for semester placement and Claude for course assignment. Some end up in `Unknown Semester/Unknown Course`.

**Course name spacing.** A mismatch between how Claude formats a course (`HS 345`) and how the `COURSE_SEMESTER_MAP` key is spelled (`HS345`) silently bypasses the override. The normalization layer catches most of these, but edge cases require manual dictionary additions.

**No undo.** Once files are moved, there's no automated rollback. The `progress.json` file tracks where each file was sent, which gives you a map, but reversing the moves requires either a manual re-run with inverted logic or restoring from a Drive snapshot.

**Single-user, single-Drive.** The script runs against whichever Drive is authenticated. It has no concept of shared drives or multi-account setups.

---

## Future Roadmap

**Better handling of shared files.** If the user is an admin on the shared Drive, the same API calls work — just authenticated as the org account. A multi-account mode that prompts for separate credentials per Drive would cover the DiversaTech file gap.

**Incremental runs.** Currently the script re-fetches all 2,500+ files on every run. A `modifiedTime > lastRunTimestamp` filter in the API query would make re-runs near-instant, enabling a daily scheduled job.

**Confidence scores and quarantine.** Claude could return a confidence estimate alongside each path. Low-confidence files would be routed to a `Review/` folder instead of being moved immediately — a human-in-the-loop checkpoint before the move.

**Folder watching via webhook.** The Drive API supports push notifications when files change. A small server could receive these events and classify new files in real time as they're added to Drive, keeping the structure clean without ever needing a bulk re-run.

**Richer config schema.** The current `config.json` covers courses and semesters. A fuller schema would let users define custom top-level categories, subcategory rules, and exclusion patterns (e.g., "never move files in this folder ID") without touching the source code.

---

## Setup

```bash
git clone <repo>
cd driver

cp config.example.json config.json
# Edit config.json with your name, courses, and semester history

pip install google-auth-oauthlib google-api-python-client anthropic python-dotenv

cp .env.example .env
# Add your Anthropic API key to .env

# Place your Google credentials.json in this directory
# (Download from Google Cloud Console → APIs & Services → Credentials)

python3 organizer.py        # live run
DRY_RUN=True python3 organizer.py  # preview only (or set DRY_RUN = True in the file)
```

On first run, a browser window will open for Google OAuth. After that, `token.json` handles re-authentication automatically.
