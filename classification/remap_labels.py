"""
remap_labels.py
---------------
Remaps fine-grained labels in annotation txt files to broader category groups.

File format expected (one entry per line):
    <filename>, <label>

Usage:
    python remap_labels.py

Edit BASE_DIR to point to your dataset/annotation folder if needed.
"""

import os

# ── Configuration ────────────────────────────────────────────────────────────

BASE_DIR = "./dataset/annotation"   # adjust if running from a different CWD
FILES    = ["train.txt", "test.txt"]

# Maps every fine-grained label → its broad group.
# Labels are matched case-insensitively and stripped of surrounding whitespace.
LABEL_MAP = {
    # graph
    "line graph":       "graph",
    "bar plot":         "graph",
    "bar plots":        "graph",
    "scatter plot":     "graph",
    "histogram":        "graph",
    "box plot":         "graph",
    "bubble chart":     "graph",
    "area chart":       "graph",
    "pareto chart":     "graph",
    "pareto charts":    "graph",
    "graph plots":      "graph",
    "graphs":           "graph",

    # tables
    "table":            "table",
    "confusion matrix": "table",
    "tables":           "table",

    # diagram
    "block diagram":    "diagram",
    "venn diagram":     "diagram",
    "pie chart":        "diagram",
    "tree diagram":     "diagram",

    # meta figure
    "flow chart":       "meta figure",
    "sketch":           "meta figure",
    "sketches":         "meta figure",
    "heat map":         "meta figure",
    "mask":             "meta figure",
    "vector plot":      "meta figure",
    "surface plot":     "meta figure",
    "contour plot":     "meta figure",

    # photograph
    "natural image":    "photograph",
    "natural images":   "photograph",
    "3d object":        "photograph",
    "3d objects":       "photograph",
    "medical image":    "photograph",
    "medical images":   "photograph",
    "geographic map":   "photograph",

    # screenshot
    "algorithm":        "screenshot",

    # circular graph
    "polar plot":       "circular graph",
    "radar chart":      "circular graph",
    "circular graphs":  "circular graph",
}

# ── Processing ───────────────────────────────────────────────────────────────

def remap_file(filepath: str) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    remapped   = []
    unknown    = set()
    changed    = 0

    for lineno, line in enumerate(lines, start=1):
        stripped = line.rstrip("\n")
        if not stripped.strip():          # preserve blank lines
            remapped.append(line)
            continue

        if "," not in stripped:
            print(f"  [WARN] line {lineno}: no comma found — kept as-is: {stripped!r}")
            remapped.append(line)
            continue

        fname, _, label = stripped.partition(",")
        label_clean = label.strip()
        new_label   = LABEL_MAP.get(label_clean.lower())

        if new_label is None:
            unknown.add(label_clean)
            remapped.append(line)         # keep original if not in map
        else:
            if new_label != label_clean:
                changed += 1
            remapped.append(f"{fname}, {new_label}\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(remapped)

    print(f"  ✓ {changed} label(s) remapped in {os.path.basename(filepath)}")
    if unknown:
        print(f"  ⚠  Unrecognised labels (kept unchanged): {sorted(unknown)}")


def main():
    for fname in FILES:
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            print(f"[SKIP] File not found: {path}")
            continue
        print(f"Processing {path} …")
        remap_file(path)
    print("\nDone.")


if __name__ == "__main__":
    main()