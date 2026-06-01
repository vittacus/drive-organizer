"""
First-time setup wizard for Drive Organizer.
Called automatically by organizer.py when config.json is missing.
Can also be run standalone to regenerate config: python3 setup.py
"""
import json
import os
import sys
from datetime import datetime

# ── Terminal styling ──────────────────────────────────────────────────────────
BOLD  = '\033[1m'
DIM   = '\033[2m'
GREEN = '\033[32m'
CYAN  = '\033[36m'
RESET = '\033[0m'

# ── Category defaults per user type ──────────────────────────────────────────
DEFAULTS = {
    'student': {
        'categories': ['School', 'Work & Internships', 'Personal', 'Finance', 'Photos & Media'],
        'context':    'a student',
        'notes':      {'School': 'semester + course subfolders'},
    },
    'professional': {
        'categories': ['Work', 'Personal', 'Finance', 'Photos & Media'],
        'context':    'a working professional',
        'notes':      {'Work': 'projects and client files'},
    },
    'general': {
        'categories': ['Documents', 'Personal', 'Finance', 'Photos & Media'],
        'context':    'a general user',
        'notes':      {},
    },
}

ICONS = {
    'School':             '📚',
    'Work & Internships': '💼',
    'Work':               '💼',
    'Personal':           '📄',
    'Finance':            '💳',
    'Photos & Media':     '📷',
    'Documents':          '📂',
}


def _prompt(label):
    try:
        return input(label)
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"\n{DIM}Setup cancelled.{RESET}")
        sys.exit(0)


def _current_semester():
    now = datetime.now()
    sem = 'SP' if now.month <= 7 else 'FA'
    return f"{sem}{str(now.year)[2:]}"


def _show_categories(categories, notes):
    for i, cat in enumerate(categories, 1):
        icon = ICONS.get(cat, '📁')
        note = f"  {DIM}({notes.get(cat, '')}){RESET}" if notes.get(cat) else ''
        print(f"       {CYAN}{i}{RESET}  {icon}  {cat}{note}")


def run_wizard():
    """Run the interactive setup wizard and write config.json."""
    print()
    print(f"{BOLD}Drive Organizer · Setup{RESET}")
    print(f"{DIM}config.json not found. Answer three questions to get started.{RESET}")
    print()

    # ── Step 1: User type ─────────────────────────────────────────────────────
    print(f"{BOLD}1 / 3  What best describes you?{RESET}")
    print()
    types = ['Student', 'Professional', 'General user']
    for i, t in enumerate(types, 1):
        print(f"       {CYAN}{i}{RESET}  {t}")
    print()

    while True:
        raw = _prompt("  > ").strip()
        if raw in ('1', '2', '3'):
            user_type = ['student', 'professional', 'general'][int(raw) - 1]
            break
        print(f"       {DIM}Enter 1, 2, or 3.{RESET}")
    print()

    # ── Step 2: Categories ────────────────────────────────────────────────────
    defaults  = DEFAULTS[user_type]
    categories = list(defaults['categories'])
    notes      = dict(defaults['notes'])

    print(f"{BOLD}2 / 3  Your folder categories:{RESET}")
    print()
    _show_categories(categories, notes)
    print()
    print(f"  {DIM}Press Enter to use these as-is.")
    print(f"  Type a number to remove that category.")
    print(f"  Type a name to add a new one.{RESET}")
    print()

    while True:
        raw = _prompt("  > ").strip()
        if raw == '':
            break
        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(categories):
                removed = categories.pop(idx)
                notes.pop(removed, None)
                print(f"       {DIM}Removed \"{removed}\".{RESET}")
                print()
                _show_categories(categories, notes)
                print()
            else:
                print(f"       {DIM}No item at position {raw}.{RESET}")
        else:
            # Treat as a new category name
            name_to_add = raw.strip()
            if name_to_add in categories:
                print(f"       {DIM}\"{name_to_add}\" is already listed.{RESET}")
            else:
                categories.append(name_to_add)
                print(f"       {DIM}Added \"{name_to_add}\".{RESET}")
                print()
                _show_categories(categories, notes)
                print()

    if not categories:
        categories = list(defaults['categories'])
        print(f"       {DIM}No categories left — restored defaults.{RESET}")
    print()

    # ── Step 3: Name ──────────────────────────────────────────────────────────
    print(f"{BOLD}3 / 3  What's your name?{RESET}")
    print(f"       {DIM}Used to personalize how your files get categorized.{RESET}")
    print()

    while True:
        name = _prompt("  > ").strip()
        if name:
            break
        print(f"       {DIM}Please enter a name.{RESET}")
    print()

    # ── Write config.json ─────────────────────────────────────────────────────
    config = {
        "owner_name":            name,
        "owner_context":         defaults['context'],
        "user_type":             user_type,
        "categories":            categories,
        "default_org_semester":  _current_semester() if user_type == 'student' else "",
        "course_normalizations": {},
        "course_semester_map":   {},
    }

    with open('config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print(f"  {GREEN}{BOLD}✓ config.json created{RESET}")
    print()
    print(f"  Name        {name}")
    print(f"  Type        {user_type.title()}")
    print(f"  Categories  {', '.join(categories)}")
    if user_type == 'student':
        print(f"  Semester    {config['default_org_semester']}  (auto-detected from today's date)")
    print()
    print(f"  {DIM}To add course→semester mappings, edit config.json directly.")
    print(f"  See config.example.json for the full schema.{RESET}")
    print()


if __name__ == '__main__':
    if os.path.exists('config.json'):
        print("config.json already exists. Delete it first to re-run setup.")
        sys.exit(1)
    run_wizard()
    print("Run python3 organizer.py to start organizing your Drive.")
