import os
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()
SCOPES = ['https://www.googleapis.com/auth/drive']

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

def fetch_all(service, query, fields):
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

def main():
    print("Authenticating...")
    service = authenticate()

    print("Fetching all folders...")
    folders = fetch_all(
        service,
        "mimeType='application/vnd.google-apps.folder' and trashed=false",
        "id, name, parents, ownedByMe"
    )
    print(f"Found {len(folders)} folders total.\n")

    print("Fetching all files...")
    files = fetch_all(
        service,
        "mimeType!='application/vnd.google-apps.folder' and trashed=false",
        "id, parents"
    )
    print(f"Found {len(files)} files total.\n")

    folder_by_id = {f['id']: f for f in folders}
    total_deleted = 0

    # Iteratively delete empty folders. Each pass may expose new empty parents.
    pass_num = 0
    while True:
        pass_num += 1
        has_children = set()
        for item in folders + files:
            for parent in item.get('parents', []):
                has_children.add(parent)

        empty = [
            f for f in folders
            if f['id'] not in has_children and f.get('ownedByMe', False)
        ]

        if not empty:
            break

        print(f"Pass {pass_num}: found {len(empty)} empty folder(s).")
        for f in empty:
            try:
                service.files().delete(fileId=f['id']).execute()
                print(f"  Deleted: {f['name']}")
                total_deleted += 1
            except Exception as e:
                print(f"  Could not delete '{f['name']}': {e}")
            folders.remove(f)

    print(f"\nDone. Deleted {total_deleted} empty folder(s) across {pass_num - 1} pass(es).")

if __name__ == '__main__':
    main()
