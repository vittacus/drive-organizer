import os
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']

COURSE_ALIASES = {
    "Anthropology":     "Anthro 2AC",
    "2AC":              "Anthro 2AC",
    "Anthropology 2AC": "Anthro 2AC",
    "CS61A":            "CS 61A",
    "CS61B":            "CS 61B",
    "Economics 140":    "ECON 140",
    "INDENG 142A":      "IEOR 142A",
    "Calculus":         "Math",
    "Differential Equations": "Math",
    "Data":             "Data 8",
    "Data Science":     "Data 8",
    "Data C104":        "DATA 104",
}

TOP_LEVEL_ALIASES = {
    "BCEC": "Work & Internships",
}

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

def list_folders(service, parent_id=None):
    query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"
    folders = []
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, parents)",
            pageSize=200,
            pageToken=page_token
        ).execute()
        folders.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return folders

def list_children(service, folder_id):
    items = []
    page_token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, parents)",
            pageSize=200,
            pageToken=page_token
        ).execute()
        items.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    return items

def get_or_create_folder(service, name, parent_id=None):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"
    results = service.files().list(q=query, fields="files(id)").execute()
    folders = results.get('files', [])
    if folders:
        return folders[0]['id']
    body = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        body['parents'] = [parent_id]
    folder = service.files().create(body=body, fields='id').execute()
    return folder['id']

def merge_into(service, src_id, dst_id, indent=""):
    """Move all contents of src into dst, recursing into same-named subfolders."""
    children = list_children(service, src_id)
    for item in children:
        old_parents = ','.join(item.get('parents', []))
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            existing = service.files().list(
                q=f"name='{item['name']}' and mimeType='application/vnd.google-apps.folder' and '{dst_id}' in parents and trashed=false",
                fields="files(id)"
            ).execute().get('files', [])
            if existing:
                print(f"{indent}  Merging subfolder '{item['name']}'...")
                merge_into(service, item['id'], existing[0]['id'], indent + "  ")
                if not list_children(service, item['id']):
                    service.files().delete(fileId=item['id']).execute()
                    print(f"{indent}  Deleted empty subfolder '{item['name']}'")
            else:
                service.files().update(
                    fileId=item['id'],
                    addParents=dst_id,
                    removeParents=old_parents,
                    fields='id, parents'
                ).execute()
                print(f"{indent}  Moved folder '{item['name']}'")
        else:
            service.files().update(
                fileId=item['id'],
                addParents=dst_id,
                removeParents=old_parents,
                fields='id, parents'
            ).execute()
            print(f"{indent}  Moved '{item['name']}'")

def merge_alias(service, src_id, src_name, canonical_name, parent_id=None):
    print(f"  '{src_name}' → '{canonical_name}'")
    dst_id = get_or_create_folder(service, canonical_name, parent_id)
    merge_into(service, src_id, dst_id, indent="  ")
    remaining = list_children(service, src_id)
    if not remaining:
        service.files().delete(fileId=src_id).execute()
        print(f"  Deleted empty folder '{src_name}'")
    else:
        print(f"  Warning: '{src_name}' still has {len(remaining)} items, skipping delete")

def cleanup_top_level(service):
    print("=== Top-level folder aliases ===")
    top_folders = list_folders(service)
    top_by_name = {f['name']: f for f in top_folders}
    found = False
    for alias, canonical in TOP_LEVEL_ALIASES.items():
        if alias in top_by_name:
            found = True
            merge_alias(service, top_by_name[alias]['id'], alias, canonical, parent_id=None)
    if not found:
        print("  Nothing to do.")

def cleanup_course_folders(service):
    print("\n=== Course-level folder aliases (under School/) ===")
    top_folders = list_folders(service)
    top_by_name = {f['name']: f for f in top_folders}

    if 'School' not in top_by_name:
        print("  'School' folder not found, skipping.")
        return

    school_id = top_by_name['School']['id']
    semesters = list_folders(service, parent_id=school_id)

    for semester in semesters:
        courses = list_folders(service, parent_id=semester['id'])
        courses_by_name = {f['name']: f for f in courses}
        semester_had_work = False
        for alias, canonical in COURSE_ALIASES.items():
            if alias in courses_by_name:
                if not semester_had_work:
                    print(f"\n  {semester['name']}:")
                    semester_had_work = True
                merge_alias(service, courses_by_name[alias]['id'], alias, canonical, parent_id=semester['id'])

def main():
    print("Authenticating with Google Drive...")
    service = authenticate()
    cleanup_top_level(service)
    cleanup_course_folders(service)
    print("\nDone!")

if __name__ == '__main__':
    main()
