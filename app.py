import json
import os
import subprocess
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, stream_with_context

app = Flask(__name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(BASE_DIR, 'progress.json')
ORGANIZER     = os.path.join(BASE_DIR, 'organizer.py')

CATEGORY_META = {
    'School':             {'icon': '📚', 'color': '#5B6AF0'},
    'DiversaTech':        {'icon': '🔗', 'color': '#8B5CF6'},
    'Photos & Media':     {'icon': '📷', 'color': '#F59E0B'},
    'Work & Internships': {'icon': '💼', 'color': '#10B981'},
    'Personal':           {'icon': '📄', 'color': '#6B7280'},
    'Finance':            {'icon': '💳', 'color': '#EF4444'},
}


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
