"""Create the University folder structure, courses, and tracking files.

Idempotent by design. Running a command against an existing semester adds only
what is missing and reports what already exists, so it is safe to re-run.

    python setup_semester.py init --semester 3 --degree "BS Software Engineering" \
        --institution "Iqra University" --total 8 \
        --subject "Database Management Systems" --code SE-204

    python setup_semester.py add-subject --semester 3 --name "Data Structures"
    python setup_semester.py list
    python setup_semester.py next-number --semester 3 --subject "Data Structures" --kind quiz
"""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "University"
SKILL = Path(__file__).resolve().parents[1]
UNKNOWN = "not yet known"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def template(name: str) -> str:
    return (SKILL / "templates" / name).read_text(encoding="utf-8")


def fill(text: str, **values: str) -> str:
    """Replace {{TOKEN}} placeholders. Unknown tokens are left in place so a
    missing value is visible rather than silently blanked."""
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def today() -> str:
    return date.today().isoformat()


# --- markdown table helpers -------------------------------------------------

def strip_comments(text: str) -> list[str]:
    """Blank out HTML comments while preserving line count, so line indices
    from the stripped copy still address the same line in the original."""
    out: list[str] = []
    in_comment = False
    for line in text.splitlines():
        kept: list[str] = []
        i = 0
        while i < len(line):
            if in_comment:
                end = line.find("-->", i)
                if end == -1:
                    i = len(line)
                else:
                    in_comment = False
                    i = end + 3
            else:
                start = line.find("<!--", i)
                if start == -1:
                    kept.append(line[i:])
                    i = len(line)
                else:
                    kept.append(line[i:start])
                    in_comment = True
                    i = start + 4
        out.append("".join(kept))
    return out


def table_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    """Return (first_table_line, end_of_table_line) for the table under a
    heading, ignoring blanks and comments in between."""
    visible = strip_comments("\n".join(lines))
    wanted = f"## {heading}".lower()
    for i, line in enumerate(visible):
        if line.strip().lower() != wanted:
            continue
        for j in range(i + 1, len(visible)):
            stripped = visible[j].strip()
            if stripped.startswith("|"):
                k = j
                while k < len(visible) and visible[k].strip().startswith("|"):
                    k += 1
                return j, k
            if stripped:
                return None
    return None


def table_rows(path: Path, heading: str) -> list[str]:
    """Return the body rows of a table, excluding header and separator."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    bounds = table_bounds(lines, heading)
    if not bounds:
        return []
    start, end = bounds
    rows = [ln for ln in lines[start + 2:end] if ln.strip().startswith("|")]
    return rows


def append_row(path: Path, heading: str, row: str) -> str:
    """Append a row to a table. Returns 'added', 'present', or a reason."""
    if not path.exists():
        return "missing file"
    lines = path.read_text(encoding="utf-8").splitlines()
    bounds = table_bounds(lines, heading)
    if not bounds:
        return f"no table under '## {heading}'"
    _, end = bounds
    marker = row.split("|")[1].strip().lower() if "|" in row else ""
    for existing in lines[:end]:
        if marker and marker in existing.lower():
            return "present"
    lines.insert(end, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "added"


# --- semester scaffolding ---------------------------------------------------

def semester_folder(number: int) -> Path:
    return ROOT / f"{number:02d}-semester-{number}"


def course_folder(number: int, subject: str) -> Path:
    return semester_folder(number) / "courses" / slugify(subject)


def current_semester() -> int | None:
    """Read the ongoing row from semester.md. This single word is the pointer
    that every other command relies on."""
    path = ROOT / "semester.md"
    if not path.exists():
        return None
    for row in table_rows(path, "Semesters"):
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) >= 2 and cells[1].lower() == "ongoing":
            try:
                return int(cells[0])
            except ValueError:
                return None
    return None


def require_semester(number: int | None) -> int:
    if number is None:
        found = current_semester()
        if found is None:
            raise SystemExit(
                "ERROR: No semester marked 'ongoing' in University/semester.md. "
                "Run init with --semester, or set one row to ongoing first."
            )
        return found
    return number


def semester_rows(total: int, current: int, earlier_completed: bool) -> str:
    rows = []
    for n in range(1, total + 1):
        if n == current:
            status = "ongoing"
        elif n < current and earlier_completed:
            status = "completed"
        elif n < current:
            status = "not yet confirmed"
        else:
            status = "not started"
        rows.append(f"| {n} | {status} | — | — | — |")
    return "\n".join(rows)


def cmd_init(args: argparse.Namespace) -> None:
    current = args.semester
    total = max(args.total, current)
    created: list[str] = []
    kept: list[str] = []

    ROOT.mkdir(parents=True, exist_ok=True)
    created.append(str(ROOT))

    semester_path = ROOT / "semester.md"
    if semester_path.exists():
        kept.append(str(semester_path))
    else:
        semester_path.write_text(
            fill(
                template("semester-template.md"),
                DEGREE=args.degree or UNKNOWN,
                INSTITUTION=args.institution or UNKNOWN,
                STARTED=args.started or UNKNOWN,
                EXPECTED_COMPLETION=UNKNOWN,
                SEMESTER_ROWS=semester_rows(total, current, args.earlier_completed),
                COMPLETED_COUNT="0",
                TOTAL_SEMESTERS=str(total),
                CURRENT_SEMESTER=str(current),
                DATE=today(),
                LOG_ENTRY=f"Started tracking semester {current}.",
            ),
            encoding="utf-8",
        )
        created.append(str(semester_path))

    folder = semester_folder(current)
    for path in (folder, folder / "courses"):
        if path.exists():
            kept.append(str(path))
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))

    track = folder / "track.md"
    if track.exists():
        kept.append(str(track))
    else:
        track.write_text(
            fill(
                template("track-template.md"),
                SEMESTER=str(current),
                STATUS="ongoing",
                DATES=UNKNOWN,
                SUBJECT_COUNT="0",
                SUBJECT_ROWS="",
                DATE=today(),
                LOG_ENTRY=f"Semester {current} tracking started.",
            ),
            encoding="utf-8",
        )
        created.append(str(track))

    for subject in args.subject or []:
        state = add_subject(current, subject, args.code, args.teacher, args.credits)
        (created if state == "added" else kept).append(subject)

    print(f"Semester {current} — ready at {folder}")
    for path in created:
        print(f"  created  {path}")
    for path in kept:
        print(f"  exists   {path}")
    if not args.earlier_completed and current > 1:
        print(
            f"\nNote: semesters 1 to {current - 1} are marked 'not yet confirmed'. "
            "Re-run with --earlier-completed, or edit semester.md, once their status is right."
        )


def add_subject(
    number: int,
    name: str,
    code: str | None = None,
    teacher: str | None = None,
    credits: str | None = None,
) -> str:
    """Create a course folder and course.md, then register it in track.md."""
    folder = course_folder(number, name)
    existed = folder.exists()
    for sub in (folder, folder / "lectures", folder / "assignments", folder / "quizzes"):
        sub.mkdir(parents=True, exist_ok=True)

    course_md = folder / "course.md"
    if course_md.exists():
        state = "present"
    else:
        course_md.write_text(
            fill(
                template("course-template.md"),
                SUBJECT=name,
                CODE=code or UNKNOWN,
                TEACHER=teacher or UNKNOWN,
                CREDITS=credits or UNKNOWN,
                SEMESTER=str(number),
                CONTACT_HOURS=UNKNOWN,
                THEORY_MARKS=UNKNOWN,
                SESSIONAL_MARKS=UNKNOWN,
                PASSING_RULE=UNKNOWN,
                DATE=today(),
                LOG_ENTRY=f"Course created from the subject list.",
            ),
            encoding="utf-8",
        )
        state = "added"

    slug = slugify(name)
    append_row(
        semester_folder(number) / "track.md",
        "Subjects",
        f"| {name} | [course.md](courses/{slug}/course.md) | 0 / {UNKNOWN} "
        f"| 0 / {UNKNOWN} | 0 / {UNKNOWN} | not yet known | active |",
    )
    return state if not existed or state == "added" else "present"


def cmd_add_subject(args: argparse.Namespace) -> None:
    number = require_semester(args.semester)
    state = add_subject(number, args.name, args.code, args.teacher, args.credits)
    folder = course_folder(number, args.name)
    print(f"{state}: {folder}")
    print(f"  course file: {folder / 'course.md'}")
    print("  next: add the real syllabus to the Syllabus and Coverage table.")


def cmd_list(_args: argparse.Namespace) -> None:
    if not ROOT.exists():
        raise SystemExit(f"ERROR: {ROOT} does not exist. Run init first.")
    current = current_semester()
    print(f"University root: {ROOT}")
    print(f"Current semester: {current if current else UNKNOWN}")
    if current is None:
        return
    folder = semester_folder(current)
    courses = sorted(p for p in (folder / "courses").glob("*") if p.is_dir())
    if not courses:
        print("  (no courses yet)")
        return
    for course in courses:
        counts = []
        for kind in ("lectures", "assignments", "quizzes"):
            sub = course / kind
            counts.append(f"{len(list(sub.glob('*'))) if sub.exists() else 0} {kind}")
        print(f"  {course.name}  ({', '.join(counts)})")


def cmd_next_number(args: argparse.Namespace) -> None:
    number = require_semester(args.semester)
    folder = course_folder(number, args.subject)
    if not folder.exists():
        raise SystemExit(f"ERROR: Course not found: {folder}")
    targets = {"lecture": "lectures", "assignment": "assignments", "quiz": "quizzes"}
    sub = folder / targets[args.kind]
    used = []
    for path in sub.glob("*") if sub.exists() else []:
        match = re.match(r"(\d+)", path.name)
        if match:
            used.append(int(match.group(1)))
    nxt = (max(used) if used else 0) + 1
    print(f"{nxt:02d}")
    print(f"  folder: {sub}")
    print(f"  name:   {args.kind}-{nxt:02d}  ->  name the file {nxt:02d}_<slug>.md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create the semester, track.md, and courses")
    p_init.add_argument("--semester", type=int, required=True)
    p_init.add_argument("--degree")
    p_init.add_argument("--institution")
    p_init.add_argument("--started")
    p_init.add_argument("--total", type=int, default=8, help="semesters in the degree")
    p_init.add_argument("--earlier-completed", action="store_true",
                        help="mark semesters before this one as completed")
    p_init.add_argument("--subject", action="append", help="subject name, repeatable")
    p_init.add_argument("--code", help="course code for the first subject only")
    p_init.add_argument("--teacher", help="teacher for the first subject only")
    p_init.add_argument("--credits", help="credits for the first subject only")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add-subject", help="add one subject to a semester")
    p_add.add_argument("--semester", type=int)
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--code")
    p_add.add_argument("--teacher")
    p_add.add_argument("--credits")
    p_add.set_defaults(func=cmd_add_subject)

    p_list = sub.add_parser("list", help="show the current semester and its courses")
    p_list.set_defaults(func=cmd_list)

    p_num = sub.add_parser("next-number", help="next free NN for a lecture, assignment, or quiz")
    p_num.add_argument("--semester", type=int)
    p_num.add_argument("--subject", required=True)
    p_num.add_argument("--kind", choices=("lecture", "assignment", "quiz"), required=True)
    p_num.set_defaults(func=cmd_next_number)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
