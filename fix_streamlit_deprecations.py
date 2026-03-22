#!/usr/bin/env python3
"""
fix_streamlit_deprecations.py

Mass-fixes two deprecated Streamlit APIs across the entire RTD_SIM codebase:

1. width='stretch'  →  width='stretch'
2. width='content' →  width='content'
3. Styler.map(          →  Styler.map(

Run from the project root:
    python fix_streamlit_deprecations.py [--dry-run] [path]

Without --dry-run, files are edited in place.
With    --dry-run, only lists what would change.
"""

import sys
import re
from pathlib import Path


def fix_file(path: Path, dry_run: bool = False) -> int:
    """Return number of replacements made."""
    src = path.read_text(encoding='utf-8')
    original = src

    # 1. width='stretch'  → width='stretch'
    src = re.sub(r'\buse_container_width\s*=\s*True\b', "width='stretch'", src)

    # 2. width='content' → width='content'
    src = re.sub(r'\buse_container_width\s*=\s*False\b', "width='content'", src)

    # 3. Styler.applymap → Styler.map
    src = src.replace('.map(', '.map(')

    changes = sum(1 for a, b in zip(original.splitlines(), src.splitlines()) if a != b)

    if src == original:
        return 0

    if dry_run:
        print(f"  WOULD FIX {path} ({changes} lines changed)")
    else:
        path.write_text(src, encoding='utf-8')
        print(f"  FIXED {path} ({changes} lines changed)")

    return changes


def main():
    dry_run = '--dry-run' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    root = Path(args[0]) if args else Path('.')

    py_files = list(root.rglob('*.py'))
    # Exclude venv, .git, __pycache__
    py_files = [f for f in py_files
                if not any(part in f.parts
                           for part in ('venv', '.git', '__pycache__', 'node_modules'))]

    total_changes = 0
    files_changed = 0

    print(f"{'[DRY RUN] ' if dry_run else ''}Scanning {len(py_files)} Python files in {root}/\n")

    for f in sorted(py_files):
        n = fix_file(f, dry_run)
        if n:
            total_changes += n
            files_changed += 1

    print(f"\n{'Would change' if dry_run else 'Changed'} {total_changes} lines across {files_changed} files.")

if __name__ == '__main__':
    main()
