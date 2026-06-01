import json
import os
import subprocess
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, stream_with_context
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = Flask(__name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(BASE_DIR, 'progress.json')
ORGANIZER     = os.path.join(BASE_DIR, 'organizer.py')
TOKEN_FILE    = os.path.join(BASE_DIR, 'token.json')

SCOPES = ['https://www.googleapis.com/auth/drive']

CATEGORY_META = {
    'School':             {'icon': '📚', 'color': '#5B6AF0'},
    'DiversaTech':        {'icon': '🔗', 'color': '#8B5CF6'},
    'Photos & Media':     {'icon': '📷', 'color': '#F59E0B'},
    'Work & Internships': {'icon': '💼', 'color': '#10B981'},
    'Personal':           {'icon': '📄', 'color': '#6B7280'},
    'Finance':            {'icon': '💳', 'color': '#EF4444'},
}


def get_drive_service():
    if not os.path.exists(TOKEN_FILE):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as f:
                f.write(creds.to_json())
        else:
            return None
    return build('drive', 'v3', credentials=creds)


def load_stats():
    if not os.path.exists(PROGRESS_FILE):
        return None

    mtime    = os.path.getmtime(PROGRESS_FILE)
    last_run = datetime.fromtimestamp(mtime).strftime('%b %-d, %Y · %-I:%M %p')

    with open(PROGRESS_FILE) as f:
        data = json.load(f)

    by_top, by_second = {}, {}
    skipped = unknown = 0

    for path in data.values():
        if path == 'SKIPPED':
            skipped += 1
            continue
        parts = path.split('/')
        by_top[parts[0]] = by_top.get(parts[0], 0) + 1
        if len(parts) >= 2:
            k = '/'.join(parts[:2])
            by_second[k] = by_second.get(k, 0) + 1
        if 'Unknown Semester' in path:
            unknown += 1

    total   = len(data)
    moved   = total - skipped
    folders = sorted(by_top.items(), key=lambda x: -x[1])
    max_val = max((v for _, v in folders), default=1)

    return {
        'last_run': last_run,
        'total':    total,
        'moved':    moved,
        'skipped':  skipped,
        'unknown':  unknown,
        'folders': [
            {
                'name':  name,
                'count': count,
                'pct':   round(count / max_val * 100),
                **CATEGORY_META.get(name, {'icon': '📁', 'color': '#6B7280'}),
            }
            for name, count in folders
        ],
        'semesters': sorted(
            [{'label': k.replace('School/', ''), 'count': v}
             for k, v in by_second.items() if k.startswith('School/')],
            key=lambda x: -x['count'],
        ),
    }


@app.route('/')
def index():
    return render_template('index.html', stats=load_stats())


@app.route('/api/stats')
def api_stats():
    return jsonify(load_stats())


@app.route('/api/browse')
def api_browse():
    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Not authenticated — run organizer.py first to create token.json'}), 401

    try:
        root_id = service.files().get(fileId='root', fields='id').execute()['id']
        result  = service.files().list(
            q=f"'{root_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields='files(id,name)',
            orderBy='name',
            pageSize=50,
        ).execute()

        # Sort known categories first (by count desc), then unknown alphabetically
        known_order = list(CATEGORY_META.keys())
        folders = []
        for f in result.get('files', []):
            meta = CATEGORY_META.get(f['name'], {'icon': '📁', 'color': '#6B7280'})
            folders.append({'id': f['id'], 'name': f['name'], **meta})

        folders.sort(key=lambda x: (
            known_order.index(x['name']) if x['name'] in known_order else len(known_order),
            x['name'],
        ))
        return jsonify(folders)
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/browse/<folder_id>')
def api_browse_folder(folder_id):
    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        result = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields='files(id,name,mimeType,webViewLink)',
            orderBy='folder,name',
            pageSize=200,
        ).execute()

        items = []
        for f in result.get('files', []):
            items.append({
                'id':          f['id'],
                'name':        f['name'],
                'isFolder':    f['mimeType'] == 'application/vnd.google-apps.folder',
                'mimeType':    f['mimeType'],
                'webViewLink': f.get('webViewLink', ''),
            })
        return jsonify(items)
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/activity')
def api_activity():
    if not os.path.exists(PROGRESS_FILE):
        return jsonify([])

    with open(PROGRESS_FILE) as f:
        data = json.load(f)

    moved  = [(fid, path) for fid, path in data.items() if path != 'SKIPPED']
    recent = moved[-20:][::-1]

    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401

    activity = []
    for file_id, path in recent:
        try:
            info = service.files().get(
                fileId=file_id,
                fields='id,name,modifiedTime,mimeType,webViewLink',
            ).execute()
            activity.append({
                'name':         info['name'],
                'path':         path,
                'mimeType':     info.get('mimeType', ''),
                'modifiedTime': info.get('modifiedTime', ''),
                'webViewLink':  info.get('webViewLink', ''),
            })
        except HttpError:
            continue  # file deleted or inaccessible

    return jsonify(activity)


@app.route('/run')
def run():
    def generate():
        proc = subprocess.Popen(
            ['python3.11', '-u', ORGANIZER],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=BASE_DIR,
        )
        for line in iter(proc.stdout.readline, ''):
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        proc.wait()
        yield f"data: {json.dumps({'done': True, 'code': proc.returncode})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)
