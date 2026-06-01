import argparse
import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import anthropic

load_dotenv()

# Set to True to preview moves without changing anything in Drive
DRY_RUN = False

SCOPES = ['https://www.googleapis.com/auth/drive']
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
PROGRESS_FILE = "progress.json"
BATCH_SIZE = 30

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

if not os.path.exists("config.json"):
    raise FileNotFoundError(
        "config.json not found — copy config.example.json, fill in your settings, and retry."
    )
with open("config.json") as f:
    _cfg = json.load(f)

COURSE_NORMALIZATIONS = _cfg.get("course_normalizations", {})
COURSE_SEMESTER_MAP   = _cfg.get("course_semester_map", {})
OWNER_NAME            = _cfg.get("owner_name", "the user")
OWNER_CONTEXT         = _cfg.get("owner_context", "a student")
DEFAULT_ORG_SEMESTER  = _cfg.get("default_org_semester", "SP26")

# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def normalize_path(path):
    parts = [p.strip() for p in path.split('/')]
    if len(parts) >= 3 and parts[0] == 'School' and parts[2] in COURSE_NORMALIZATIONS:
        parts[2] = COURSE_NORMALIZATIONS[parts[2]]
    return '/'.join(parts)


def date_to_semester(ts):
    """Map an ISO timestamp to a Berkeley semester label, or None if out of range."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        year, month = dt.year, dt.month
    except (ValueError, AttributeError):
        return None
    if year < 2022 or year > 2026:
        return None
    if year == 2022 and month < 8:
        return None  # before FA22 enrollment
    return f"{'SP' if month <= 7 else 'FA'}{str(year)[2:]}"


def pick_date(file):
    """
    Return the timestamp to use for semester detection.
    Uses modifiedTime when the file was significantly reworked after creation (6+ months),
    otherwise uses createdTime.
    """
    created  = file.get('createdTime')
    modified = file.get('modifiedTime')
    if not created or not modified:
        return created or modified
    try:
        dt_c = datetime.fromisoformat(created.replace('Z', '+00:00'))
        dt_m = datetime.fromisoformat(modified.replace('Z', '+00:00'))
        if (dt_m - dt_c).days >= 180:
            return modified
    except (ValueError, AttributeError):
        pass
    return created


def apply_date_semester(path, file):
    """Override semester in School/* paths using the file's relevant date."""
    parts = [p.strip() for p in path.split('/')]
    if len(parts) < 2 or parts[0] != 'School':
        return path
    semester = date_to_semester(pick_date(file))
    if semester:
        parts[1] = semester
    return '/'.join(parts)


def apply_semester_override(path):
    """COURSE_SEMESTER_MAP is the final authority — runs after date inference."""
    parts = [p.strip() for p in path.split('/')]
    if len(parts) >= 3 and parts[0] == 'School' and parts[2] in COURSE_SEMESTER_MAP:
        parts[1] = COURSE_SEMESTER_MAP[parts[2]]
    return '/'.join(parts)

# ---------------------------------------------------------------------------
# Google Drive helpers
# ---------------------------------------------------------------------------

def authenticate():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)


def get_root_id(service):
    return service.files().get(fileId='root', fields='id').execute()['id']


def needs_organizing(file, root_id):
    """True only when the file sits directly in My Drive root (unorganized)."""
    parents = file.get('parents', [])
    return bool(parents) and all(p == root_id for p in parents)


def get_all_files(service):
    files = []
    page_token = None
    while True:
        response = service.files().list(
            q="mimeType!='application/vnd.google-apps.folder' and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, parents, ownedByMe, createdTime, modifiedTime)",
            pageSize=200,
            pageToken=page_token
        ).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return files


def get_or_create_folder(service, name, parent_id=None):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id)").execute()
    folders = results.get('files', [])
    if folders:
        return folders[0]['id']
    body = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        body['parents'] = [parent_id]
    return service.files().create(body=body, fields='id').execute()['id']


def get_folder_id_for_path(service, path, folder_cache):
    if path in folder_cache:
        return folder_cache[path]
    parts = [p.strip() for p in path.split('/')]
    parent_id = None
    built = ""
    for part in parts:
        built = f"{built}/{part}" if built else part
        if built in folder_cache:
            parent_id = folder_cache[built]
        else:
            parent_id = get_or_create_folder(service, part, parent_id)
            folder_cache[built] = parent_id
    return parent_id


def move_file(service, file, folder_id):
    old_parents = file.get('parents', [])
    if file.get('ownedByMe', True):
        service.files().update(
            fileId=file['id'],
            addParents=folder_id,
            removeParents=','.join(old_parents) if old_parents else '',
            fields='id, parents'
        ).execute()
    else:
        if folder_id not in old_parents:
            service.files().update(
                fileId=file['id'],
                addParents=folder_id,
                fields='id, parents'
            ).execute()


def fetch_all_items(service, query, fields):
    items = []
    page_token = None
    while True:
        response = service.files().list(
            q=query, fields=f"nextPageToken, files({fields})",
            pageSize=1000, pageToken=page_token
        ).execute()
        items.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return items


def cleanup_empty_folders(service):
    print("\nCleaning up empty folders...")
    folders = fetch_all_items(
        service,
        "mimeType='application/vnd.google-apps.folder' and trashed=false",
        "id, name, parents, ownedByMe"
    )
    files = fetch_all_items(
        service,
        "mimeType!='application/vnd.google-apps.folder' and trashed=false",
        "id, parents"
    )
    total_deleted = 0
    while True:
        has_children = set()
        for item in folders + files:
            for parent in item.get('parents', []):
                has_children.add(parent)
        empty = [f for f in folders if f['id'] not in has_children and f.get('ownedByMe', False)]
        if not empty:
            break
        for f in empty:
            try:
                service.files().delete(fileId=f['id']).execute()
                print(f"  Deleted empty folder: {f['name']}")
                total_deleted += 1
            except Exception as e:
                print(f"  Could not delete '{f['name']}': {e}")
            folders.remove(f)
    print(f"Deleted {total_deleted} empty folder(s).")

# ---------------------------------------------------------------------------
# Claude categorization
# ---------------------------------------------------------------------------

def categorize_batch(client, files_batch):
    file_list = "\n".join(
        f"{i+1}. Name: '{f['name']}' | Type: '{f['mimeType']}'"
        for i, f in enumerate(files_batch)
    )
    prompt = f"""You are organizing Google Drive files for {OWNER_NAME}, {OWNER_CONTEXT}.

For each file, return a folder path. Reply with ONLY a JSON array of paths in the same order as the files.
Example: ["School/SP26/IEOR 142", "DiversaTech/{DEFAULT_ORG_SEMESTER}/Finance", "Personal"]

SEMESTER — School file semesters are overridden automatically from file creation
dates, so any reasonable guess is fine for them. For DiversaTech files, use
{DEFAULT_ORG_SEMESTER} if no semester clue is present. For other paths, no semester needed.

RULES:
- School files → School/<SEMESTER>/<Course Name> (e.g. School/FA25/GPP 115)
- BCEC → School/<SEMESTER>/BCEC (it is a school course, not a job category)
- DiversaTech files → DiversaTech/<SEMESTER>/<Subcategory>
  Subcategories: Finance, Events, Recruitment, Operations, Marketing, General
- Personal documents → Personal
- Bank/budget/receipts → Finance
- Photos/videos → Photos & Media
- Job/internship/resume → Work & Internships
- Unclear → Personal

COURSE NAME NORMALIZATION (use these exact names, no variations):
- Anthropology, 2AC, Anthropology 2AC → "Anthro 2AC"
- CS61A → "CS 61A" | CS61B → "CS 61B" (keep separate, just add the space)
- Data or Data Science (intro course) → "Data 8" | Data C104 → "DATA 104"
- Economics 140 → "ECON 140" (other ECON courses keep their number as-is)
- INDENG 142A → "IEOR 142A" (other INDENG courses keep INDENG prefix)
- Calculus or Differential Equations → "Math"

FILES:
{file_list}

Return ONLY the JSON array, nothing else."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if DRY_RUN:
        print("*** DRY RUN — no files will be moved ***\n")

    print("Authenticating with Google Drive...")
    service = authenticate()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print("Fetching all files from Drive...")
    service_root_id = get_root_id(service)
    all_files = get_all_files(service)
    print(f"Found {len(all_files)} files total.")

    progress = load_progress()
    folder_cache = {}

    # Fast-skip files that are already inside a folder (non-root parent).
    # They were either previously organized or placed there by someone else.
    unprocessed = [f for f in all_files if f['id'] not in progress]
    to_organize  = [f for f in unprocessed if needs_organizing(f, service_root_id)]
    pre_organized = [f for f in unprocessed if not needs_organizing(f, service_root_id)]
    for f in pre_organized:
        progress[f['id']] = "SKIPPED"
    if pre_organized:
        print(f"Fast-skipped {len(pre_organized)} already-organized files (non-root parent).")
    print(f"Already processed: {len(progress) - len(pre_organized)} | To organize: {len(to_organize)}\n")

    stats = {'moved': 0, 'skipped': 0, 'unknown_semester': 0, 'by_folder': {}}
    run_start = time.time()
    files_done = 0

    total = len(to_organize)
    for i in range(0, total, BATCH_SIZE):
        batch = to_organize[i:i+BATCH_SIZE]
        batch_num     = (i // BATCH_SIZE) + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        elapsed = time.time() - run_start
        if files_done > 0 and elapsed > 0:
            rate = files_done / elapsed
            eta_sec = (total - files_done) / rate
            eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60):02d}s"
        else:
            eta_str = "calculating..."
        print(f"Batch {batch_num}/{total_batches} — {files_done}/{total} files done — ETA: {eta_str}")

        paths = None
        for attempt in range(3):
            try:
                paths = categorize_batch(client, batch)
                break
            except Exception as e:
                wait = (attempt + 1) * 15
                print(f"  API error (attempt {attempt+1}): {e} — waiting {wait}s...")
                time.sleep(wait)

        if paths is None:
            print("  Skipping batch after 3 failures, progress saved.")
            save_progress(progress)
            continue

        for file, path in zip(batch, paths):
            try:
                path = normalize_path(path)
                path = apply_date_semester(path, file)
                path = apply_semester_override(path)

                top = path.split('/')[0]
                stats['by_folder'][top] = stats['by_folder'].get(top, 0) + 1
                if 'Unknown Semester' in path:
                    stats['unknown_semester'] += 1

                tag = "✓" if file.get('ownedByMe', True) else "✓ (shared)"
                prefix = "[DRY RUN] " if DRY_RUN else ""

                if not DRY_RUN:
                    folder_id = get_folder_id_for_path(service, path, folder_cache)
                    move_file(service, file, folder_id)

                progress[file['id']] = path
                stats['moved'] += 1
                files_done += 1
                print(f"  {prefix}{tag} '{file['name']}' → {path}")
            except Exception as e:
                print(f"  ✗ Skipped '{file['name']}': {e}")
                progress[file['id']] = "SKIPPED"
                stats['skipped'] += 1
                files_done += 1

        save_progress(progress)
        if not DRY_RUN:
            time.sleep(1)

    print("\n=== Summary ===")
    print(f"  Moved:            {stats['moved']}")
    print(f"  Skipped:          {stats['skipped']}")
    print(f"  Unknown Semester: {stats['unknown_semester']}")
    if stats['by_folder']:
        print("\n  By top-level folder:")
        for folder, count in sorted(stats['by_folder'].items(), key=lambda x: -x[1]):
            print(f"    {folder:<26} {count}")

    if not DRY_RUN:
        cleanup_empty_folders(service)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


def print_stats():
    if not os.path.exists(PROGRESS_FILE):
        print("No progress.json found — run the organizer first.")
        return

    mtime = os.path.getmtime(PROGRESS_FILE)
    last_run = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')

    with open(PROGRESS_FILE) as f:
        progress = json.load(f)

    by_top    = {}
    by_second = {}
    skipped   = 0
    unknown   = 0

    for path in progress.values():
        if path == "SKIPPED":
            skipped += 1
            continue
        parts = path.split('/')
        top = parts[0]
        by_top[top] = by_top.get(top, 0) + 1
        if len(parts) >= 2:
            second = '/'.join(parts[:2])
            by_second[second] = by_second.get(second, 0) + 1
        if 'Unknown Semester' in path:
            unknown += 1

    total = len(progress)
    moved = total - skipped

    print(f"Last run:         {last_run}")
    print(f"Total tracked:    {total}")
    print(f"Moved:            {moved}")
    print(f"Skipped:          {skipped}")
    print(f"Unknown Semester: {unknown}")

    print(f"\nBy top-level folder:")
    for folder, count in sorted(by_top.items(), key=lambda x: -x[1]):
        print(f"  {folder:<26} {count}")

    school_rows = {k: v for k, v in by_second.items() if k.startswith('School/')}
    if school_rows:
        print(f"\nSchool breakdown by semester:")
        for sem, count in sorted(school_rows.items(), key=lambda x: -x[1]):
            print(f"  {sem:<30} {count}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Google Drive Organizer')
    parser.add_argument('--stats', action='store_true',
                        help='Print current Drive state from last run without moving anything')
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        main()
