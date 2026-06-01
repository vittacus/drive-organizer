# Changelog

All notable changes to this project are documented here. Versions reflect meaningful product milestones, not every commit.

---

## [v4.0] — 2026-05-31

### Date-Based Semester Detection

**The problem:** Even with a hardcoded `COURSE_SEMESTER_MAP`, files for unknown or unlisted courses were still defaulting to "Unknown Semester" or getting a wrong semester from Claude's guess. Claude has no reliable way to infer when a file was created just from its name.

**What changed:**
- Added `createdTime` and `modifiedTime` to every file fetch from the Drive API
- New `date_to_semester()` function maps any timestamp to the correct Berkeley semester (months 1–7 → Spring, months 8–12 → Fall, pre-FA22 → None)
- New `pick_date()` logic: if a file's `modifiedTime` is 6+ months after `createdTime`, use the modified date — it was probably reworked in a later semester
- `COURSE_SEMESTER_MAP` still wins as the final override layer, but now it only needs to cover cases where the date heuristic would be wrong (e.g. a file created in summer but belonging to the following fall course)
- Semester instruction in the Claude prompt simplified: "any reasonable guess is fine — it will be corrected automatically"

**Result:** **0 files in Unknown Semester** on the first full run. The three-layer pipeline (date → Claude fallback → course map) handled every file deterministically.

---

## [v3.0] — 2026-05-31

### Config Refactor, DRY_RUN Mode, and Run Summary

**The problem:** The script worked but was too tightly coupled to one person's setup. The `COURSE_SEMESTER_MAP` and personal context were embedded in source code. There was no way to preview what the script would do before it started moving thousands of files, and no way to know after a run whether things went well.

**What changed:**

**Config as data, not code**
- `COURSE_SEMESTER_MAP`, `COURSE_NORMALIZATIONS`, owner name, org context, and default semester moved to `config.json`
- `config.json` is gitignored; `config.example.json` is committed as a starting template
- Anyone can clone the repo and run it for their own Drive by filling in their own course history — no code changes required

**DRY_RUN mode**
- `DRY_RUN = False` flag at the top of the file
- When `True`: prints every intended move without making any Drive API write calls, skips folder creation, and skips cleanup
- Intended as a pre-flight check before committing to a full reorganization

**Run summary**
- Printed at the end of every run: total moved, total skipped, Unknown Semester count, and a breakdown by top-level folder sorted by volume
- Makes it easy to spot if a category is unexpectedly large or small

**modifiedTime fallback**
- If a file's `modifiedTime` is 6+ months after `createdTime`, `modifiedTime` is used for semester detection instead
- Handles files that were created as stubs early on and filled in later

---

## [v2.0] — 2026-05-27

### Course Normalization, Semester Overrides, and Cleanup Scripts

**The problem:** The initial run revealed two categories of systematic error. First, Claude returned inconsistent course names — `CS61B` instead of `CS 61B`, `Anthropology` instead of `Anthro 2AC`, `Calculus` instead of `Math`. These created duplicate folders for the same course. Second, semester detection defaulted to SP26 for anything ambiguous, so files from freshman year were landing in the current semester's folder.

**What changed:**

**Course name normalization**
- `COURSE_NORMALIZATIONS` dictionary maps variant names to canonical ones — applied as the first post-processing step on every path Claude returns
- Covers spacing (CS61A → CS 61A), abbreviations (Anthropology → Anthro 2AC), and department renames (INDENG 142A → IEOR 142A)
- Prompt updated to include explicit normalization rules so Claude produces correct names in the first place (double-layer defense)

**Semester overrides**
- `COURSE_SEMESTER_MAP` hardcodes the correct semester for 18 known courses
- Applied after normalization as the final step — wins unconditionally over Claude's output
- Prompt updated to use "Unknown Semester" instead of SP26 as the default for ambiguous files

**Cleanup scripts**
- `cleanup_folders.py`: merges alias folders into canonical ones (e.g. the `Anthropology` folder that existed from the first run gets merged into `Anthro 2AC`), then deletes the now-empty originals
- `delete_empty_folders.py`: standalone script that recursively finds and deletes all empty folders in My Drive, iterating in passes until no more are found

**Security**
- Hardcoded API key moved to `.env` file loaded via `python-dotenv`
- `.env` added to `.gitignore`

---

## [v1.0] — 2026-05-27

### Initial Release

**The problem:** A Google Drive with 2,500+ files accumulated over four years of college, with no folder structure. Finding anything required search. Files from eight different semesters, a student org, internship applications, and personal documents all lived at the same level.

**What it does:**
- Authenticates with Google Drive via OAuth2 and fetches all non-trashed files
- Sends files to Claude in batches of 15 for categorical classification
- Claude returns a folder path for each file (`School/SP26/CS 61B`, `DiversaTech/SP26/Finance`, etc.)
- Creates the folder hierarchy on-the-fly if it doesn't exist, then moves each file
- Saves progress to `progress.json` after every batch — if the run is interrupted, it resumes where it left off without re-processing files
- Retries failed API calls up to 3 times with exponential backoff

**Known issues at launch:**
- API key hardcoded in source (fixed in v2.0)
- Claude's semester detection defaults to SP26 for anything ambiguous (fixed in v2.0)
- No cleanup of pre-existing messy folders (fixed in v2.0)
- No way to preview before running (fixed in v3.0)
