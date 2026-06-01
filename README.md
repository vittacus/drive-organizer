# Drive Organizer

Classifies every file in your Google Drive using Claude, then moves each one into an organized folder structure. Uses file creation dates to figure out which semester documents belong to, so you don't have to label anything manually.

---

## Who it's for

Useful if you're a student with years of course files mixed in with everything else, or anyone whose Drive has accumulated thousands of files with no structure. The default folder layout is academic (courses organized by semester), but the classification prompt and config are easy to adapt to other structures.

---

## Screenshots

![Dashboard](screenshots/dashboard.png)

*Stats overview with category and semester breakdowns.*

![File browser and activity](screenshots/file-browser.png)

*Interactive Drive browser and recent-activity feed.*

---

## How it works

### File discovery

`organizer.py` authenticates via OAuth and fetches every non-trashed file in My Drive. Each file's `id`, `name`, `mimeType`, `createdTime`, and `modifiedTime` come back in a single paginated API call. Files already in an organized subfolder are skipped on re-runs.

### Batch classification

Files go to Claude in batches of 30. Each file gets a destination path back:

```
School/FA24/CS 101
Work & Internships
Photos & Media
Personal
Finance
```

Batching at 30 keeps API costs reasonable while still giving Claude enough context per file.

### Getting the semester right

A file named `HW3.pdf` has no temporal signal. Semester placement uses three sources, in priority order:

1. **Creation date.** `createdTime` from the Drive API, mapped to a semester label by `date_to_semester()`. Edit that function to match your academic calendar.
2. **Modified date.** If `modifiedTime` is more than 6 months after `createdTime`, the modified date is used instead. This covers files created as stubs and filled in later.
3. **Course map.** `course_semester_map` in `config.json` is the final override. If a course is listed there, its semester wins regardless of what the dates say.

### Before the file moves

Each path from Claude goes through two normalization steps. First, `course_normalizations` maps spelling variants to canonical folder names (`CS61B` to `CS 61B`, `Calculus` to `Math 1A`), so you don't end up with duplicate course folders. Then `course_semester_map` applies any semester correction if the course is in that dictionary.

### Progress tracking

After each batch, file IDs and their destination paths get saved to `progress.json`. If the run dies partway through, it picks up at the next unprocessed file on restart.

---

## Getting started

### Prerequisites

```bash
pip install google-auth-oauthlib google-api-python-client anthropic python-dotenv flask
```

Python 3.9+.

### Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and enable the **Google Drive API**
2. Create an OAuth 2.0 Client ID (Desktop app) under Credentials
3. Download the JSON file, rename it `credentials.json`, and put it in the project root

The first run opens a browser for OAuth consent. After that, `token.json` takes care of re-authentication. Both files are gitignored.

### Anthropic API key

```bash
cp .env.example .env
# ANTHROPIC_API_KEY=sk-ant-...
```

### Config

```bash
cp config.example.json config.json
```

`config.json` is gitignored. `config.example.json` is the committed template.

---

## Configuration

### config.json

```json
{
  "owner_name": "Alex",
  "owner_context": "a college student double-majoring in CS and economics",
  "default_org_semester": "FA25",
  "course_normalizations": {
    "CS61A": "CS 61A",
    "Calculus": "Math 1A",
    "Anthropology": "Anthro 2AC"
  },
  "course_semester_map": {
    "CS 61A": "FA23",
    "Math 1A": "SP24",
    "Anthro 2AC": "FA24"
  }
}
```

| Field | Purpose |
|---|---|
| `owner_name` | Your name, passed to Claude for context |
| `owner_context` | Short description of you; helps with ambiguous files |
| `default_org_semester` | Fallback semester for org or work files |
| `course_normalizations` | Maps name variants to canonical folder names |
| `course_semester_map` | Final override: course name to correct semester |

### Default folder structure

```
School/
  FA22/  SP23/  FA23/  SP24/  FA24/  SP25/  FA25/  SP26/
    (course name)/
Work & Internships/
Personal/
Finance/
Photos & Media/
(Student Org)/
  SP26/
    Finance/  Events/  Recruitment/  Operations/  Marketing/
```

To change top-level categories, edit `CATEGORY_META` in `app.py` and the classification prompt in `organizer.py`. Semester date ranges live in `date_to_semester()`.

### Course normalizations

`course_normalizations` runs first and covers spacing (`CS61B` to `CS 61B`), abbreviations (`Anthropology` to `Anthro 2AC`), department renames, and common aliases. Keys in `course_semester_map` need to match the canonical name after normalization, not the raw string Claude returns.

---

## Running

### Live run

```bash
python3 organizer.py
```

Fetches, classifies, moves. Prints a summary when done.

### Dry run

```bash
DRY_RUN=True python3 organizer.py
```

Prints every intended move without touching anything in Drive. Good for a sanity check before committing to a full run.

### Stats only

```bash
python3 organizer.py --stats
```

Reads `progress.json` and prints a breakdown of files per folder, semester distribution, and unknown count. No API calls.

### Web dashboard

```bash
python3 app.py
# http://localhost:5000
```

Shows stats, category and semester breakdowns, a run button with live log streaming, an interactive file browser (click folders to expand them), and a recent-activity feed of the last 20 moved files.

---

## Cleanup

`delete_empty_folders.py` deletes every empty folder in My Drive, running passes until none are left. Useful after a reorganization leaves behind empty source folders.

```bash
python3 delete_empty_folders.py
```

---

## Results

I ran this on a four-year Drive with around 2,500 accumulated files:

| Metric | Value |
|---|---|
| Total files found | 2,583 |
| Successfully moved | 434 |
| Skipped (unowned / permission errors) | 1,609 |
| Unknown semester | **0** |
| Empty folders deleted | 92 |
| Batches processed | 173 |
| Batches retried due to rate limits | ~8, all recovered |

The skip rate looks bad but it's expected. Files owned by shared Google accounts show up in your listing but can't be moved by a non-owner. The 434 moved files are basically everything I actually owned.

Destination breakdown:

| Folder | Files |
|---|---|
| Photos & Media | 207 |
| School | 139 |
| Work & Internships | 53 |
| Personal | 31 |
| Finance | 4 |

Zero unknown semesters was the goal. Every school file landed in the right semester using creation date, with no manual overrides needed except for a handful of courses I explicitly mapped.

---

## Limitations

**Shared files.** Files owned by an org account show up in your listing but can't be moved. They get logged as skipped.

**Generic filenames.** Files named `HW3.pdf` or `Notes` have no course signal and rely entirely on creation date for semester placement.

**No undo.** `progress.json` records where everything went, but there's no automated rollback. Reversing moves means running a custom script or restoring from a Drive snapshot.

**Academic calendar.** `date_to_semester()` assumes a specific calendar. Edit it to match your school or replace it entirely for non-academic use.

---

## Contributing

PRs welcome. Things that would make this more generally useful:

- Incremental runs (filter by `modifiedTime > lastRun` to skip already-organized files)
- Confidence scoring (route low-confidence files to `Review/` instead of moving them directly)
- Multi-account support (separate credential sets for personal and org Drives)
- Config-driven taxonomy (move the category list and prompt into `config.json`)

---

## License

MIT
