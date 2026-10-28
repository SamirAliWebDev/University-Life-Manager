---
name: study
description: Turn lecture material into comprehensive plain-language study notes and manage the academic record around it — courses, lectures, assignments, and quizzes, semester by semester. Use this skill whenever the user provides lecture slides, notes, a PDF, a PPTX, or a transcript and wants study notes, or states a fact about their university work in plain language such as "this is the assignment for Database", "quiz on Friday", "I got 14 out of 20 on quiz 1", or "lecture 4 is on normalization". Also use it when they ask which semester they are in, how their semester is going, which subject is behind, when the next quiz is, or what a lecture covered.
---

# Study

Turn one lecture's material into a complete, plain-language study note, and keep the academic record around it accurate: courses, lectures, assignments, and quizzes, organised by semester.

Two modes:

- **Notes mode** — one lecture in, one detailed note out. This exists because incomplete notes are worse than no notes.
- **Track mode** — a plain-language statement is acted on directly. The agent does the structuring; the user only states the fact.

## Storage

All university material goes in one folder at the workspace root. It is separate from this skill and separate from `knowledge/`.

```text
University/
├── semester.md
├── 03-semester-3/
│   ├── track.md
│   └── courses/
│       └── database-management-systems/
│           ├── course.md
│           ├── lectures/
│           │   └── 07-normalization/
│           │       ├── source/
│           │       ├── notes.md
│           │       └── open-questions.md
│           ├── assignments/
│           │   └── 01_pak-assignment.md
│           └── quizzes/
│               └── 01_quiz-01.md
```

`University/` holds university work only. It is not a general notes folder and is never used for book learning or any other project.

Nothing for a different semester ever goes inside a semester folder. A semester 4 course is never created inside `03-semester-3/`.

### Three tracking levels

Each level has exactly one job. No file answers a question belonging to another level, and no fact is stored in two places.

| File | Level | Answers | Never contains |
|---|---|---|---|
| `University/semester.md` | Degree | Which semesters are completed, ongoing, or not started | Anything about one subject's lectures |
| `NN-semester-N/track.md` | Semester | Every subject in this semester and how far through each one | Lecture notes, quiz detail |
| `courses/<slug>/course.md` | Subject | This subject's syllabus, lectures, assignments, quizzes, schedule, session log | Anything about other subjects or semesters |

`University/semester.md` is also the pointer that resolves "the current semester". The semester marked **ongoing** is the one used for every track-mode statement. If no row is marked ongoing, ask which semester is current rather than guessing.

There is no `upcoming.md` file. The dated schedule lives in the Quizzes and Assignments tables of each `course.md`. A semester-wide "what is due" view is derived from those tables when asked, never written to disk, because a stored aggregate goes stale the moment a date changes.

A course slug is the shared identifier linking lectures, assignments, and quizzes inside one subject. If the same subject is taken in two semesters, each gets its own independent copy.

## Numbering

| Type | Pattern | Example | Resets |
|---|---|---|---|
| Semester folder | `NN-semester-N` | `03-semester-3` | never |
| Course folder | `<subject-slug>` | `database-management-systems` | never |
| Lecture folder | `NN-topic-slug` | `07-normalization` | per course |
| Assignment file | `NN_name.md` | `01_pak-assignment.md` | per course |
| Quiz file | `NN_name.md` | `01_quiz-01.md` | per course |

All numbers are zero-padded to two digits so items sort correctly by name.

- Assignment and quiz numbers are independent counters.
- Numbers are never reused after an item is deleted or archived.
- Run `scripts/setup_semester.py next-number` rather than guessing the next free number.
- A statement with no name supplied gets a descriptive name inferred from its content, and the agent states the name it chose.

## Source Files

| Source | How it is read |
|---|---|
| PDF | Run `scripts/extract_content.py <file> [--pages N-M]` or read directly with the file reading tool. |
| PPTX | Run `scripts/extract_content.py <file> --notes` first, then work from the outline. |
| DOCX | Run `scripts/extract_content.py <file>` first, then work from the outline. |
| Transcript | Read directly as text. Treated as spoken content from the same lecture. |
| Other | Read it directly and extract text however it can be read. |

Copy every provided file into the lecture's `source/` folder before writing notes, so the notes stay traceable to the exact material they came from.

When a lecture has both slides and a transcript, the slides define the structure and order, and the transcript fills in what was said beyond what is written. Content appearing only in the transcript is still included and marked as spoken-only. Neither source is the complete lecture on its own.

## First Run

### Step 1 — Workspace location

Before anything else, ask the user this question only once:

> "Do you want to use this system in this workspace, or in a different location?"

- **This workspace** — the `University/` folder is created at the root of the current workspace.
- **Different location** — ask for the path, then create the `University/` folder there. All scripts, templates, and tracking will use that location from then on.

The answer determines where all university material is stored. It is asked once and remembered for all future sessions.

### Step 2 — Academic context

After the workspace is confirmed, ask for the academic context before creating anything. Nothing is created until these answers are given.

1. Degree, institution, and which semester is current.
2. Total semesters in the degree.
3. The subject list for this semester.
4. Per subject, only what cannot be inferred: course code and teacher.
5. For each subject, the real syllabus — as a list, or as a document to extract it from.

Ask these as one batched set, not one at a time. A subject with no known code or teacher is still created, with those fields marked not yet known.

Never invent a syllabus topic, lecture count, date, or score to fill a gap. If a subject's syllabus is unavailable, create the course anyway and mark its syllabus table not yet known.

If the semester already exists, report what is there and ask only about missing subjects.

## Workflow — track mode

1. Resolve the current semester from the **ongoing** row in `University/semester.md`.
2. Resolve the course by name. Match on slug, then on subject name, case-insensitively. When a name is ambiguous, ask which subject. When it is absent from the current semester, ask which semester rather than creating it in the wrong one.
3. Read the target `course.md` before editing. Never write a change from memory of an earlier read.
4. Create or update the file from its template.
5. Mirror the change into the semester's `track.md` progress figures.
6. Add a dated entry to the `course.md` session log describing what changed.

Statements the agent acts on without further prompting:

- "this is the assignment for Database, save it" — create `assignments/NN_name.md`, attach the file
- "quiz on Friday" — create `quizzes/NN_name.md` with the date and time, even if nothing else is known
- "the quiz covers lectures 1 to 5" — fill the syllabus section and link the related lecture notes
- "lecture 4 is on normalization" — create the lecture folder and register it in `course.md`
- "mark assignment 2 as submitted" — update status and submission date
- "I got 14 out of 20 on quiz 1" — record the result and flag weak topics for revision

When a statement carries partial information, record what was given and mark the rest **not yet known**. Do not ask a blocking question and do not fill the gaps yourself.

Track mode only records. It never generates academic content.

## Workflow — notes mode

1. Confirm the course, the lecture number, and the topic.
2. Read `course.md` to find the next free lecture number and see the syllabus topics already covered.
3. Create `lectures/NN-topic-slug/` with `source/`, `notes.md`, and `open-questions.md`.
4. Copy every source file into `source/`.
5. Read the whole source before writing a word of notes. For a PPTX, extract first.
6. Write `notes.md` from `templates/notes-template.md`.
7. Walk the source once more, item by item, and place each item somewhere in the notes. Anything that cannot be placed goes into Gaps. Fill in the Completeness check counts.
8. Update `course.md`: add the lecture row, link the notes, and mark the matching syllabus topics as covered.
9. Update the semester's `track.md` lecture count.
10. Record a session log entry in `course.md`.

## Core Note Rules

These rules are what make the notes complete. They are not style preferences.

1. **Nothing is dropped.** Every slide, every spoken point, every diagram, every example, and every number in the source appears in the notes. Never write "covered above". Never collapse several examples into one bullet.
2. **Follow lecture order.** Notes follow the order of the slides and the lecture, so the note maps back to what actually happened.
3. **Keep technical terms, define each one.** Technical terms are retained because they are the exam vocabulary. Each gets a plain-language explanation the first time it appears. Plain language means never using an undefined term, not removing the term.
4. **Nothing is invented.** Explanations come only from the source. No outside knowledge, no examples the lecturer did not give. When a slide is too thin to explain, record it as a gap instead of padding it.
5. **Transcribe diagrams, tables, formulas, and sequences.** Reproduce them rather than describing them, because paraphrasing is where details get lost.
6. **Expansions stay separated.** Anything not present in the source goes in a clearly marked section, never blended into the lecturer's content.

### Topic section fields

Every topic section uses the same fields in the same order. Keep the order; delete a field that has nothing in it rather than filling it with a guess.

| Field | Holds |
|---|---|
| `Source` | The slides or pages this topic came from, so the note maps back |
| `Definition` | The term defined as the lecturer defined it |
| `In plain terms` | The same thing explained with no undefined word |
| `How it works` | Parts, steps, or structure, in the order given |
| `Example` | The lecturer's own example, with the real numbers, every step if it was worked through |
| `Why it matters` | What it is for — only if the lecturer said so |
| `Terms defined here` | A small table of terms defined in this topic |

Technical terms are defined in plain terms at their first use in the topic sections, and collected again in the Key terms table. The table is the revision view, never the only place a term is explained.

Diagrams, tables, formulas, and sequences are transcribed in place where the lecturer showed them, and collected under `Diagrams, tables, and formulas` when they span topics. They are never described instead of reproduced.

### The one exception to rule 4

The **Connections** section is the only place outside knowledge is allowed, because its purpose is linking this lecture to things the lecturer never said — an earlier lecture, the textbook, the user's own work.

Two kinds, both labelled: **Internal** links justified by the content of an earlier lecture, and **My own** links to the user's own builds. A connection that cannot be justified from the lecture's own content is left out rather than padded.

## Semester rollover

A new semester never starts without updating the pointer.

1. Mark the previous semester **completed** and the new one **ongoing** in `University/semester.md`.
2. Create the new semester folder and its `track.md`.
3. Scan the previous semester for assignments and quizzes that are not completed. List them and ask which should carry forward.
4. Create only the items the user names, marked as carried over with the original date and a note of where they came from.

Nothing is copied automatically. The previous semester folder stays complete and unchanged. Unfinished items are never silently dropped and never silently resurrected.

## Rules

- Keep the three tracking levels separate. A course file never contains another subject, and no file duplicates a fact held by another file.
- Read the target file before editing it.
- Every change to `course.md` is mirrored into that semester's `track.md` progress figures.
- Quiz and assignment records are creatable from a date alone. Everything unknown is **not yet known**, never blank and never invented.
- A quiz with no date yet stays listed in `course.md` as a placeholder so it is not lost, and is left out of `track.md` until its date is known.
- Related notes links point at the `notes.md` files themselves, never a copy, so corrected notes appear automatically.
- Before a quiz is taken, Topics to Focus On and What Went Wrong both read not yet known. Both are written after the fact, from the actual paper. What Went Wrong records the user's own errors and appears nowhere else.
- A syllabus and coverage table is only ever written from a real syllabus. Unknown syllabus means the table is not written at all.
- Log every session in `course.md` with the date and what changed.
- Use the templates rather than inventing a section order.

## Templates

| File | Template |
|---|---|
| `University/semester.md` | `templates/semester-template.md` |
| `NN-semester-N/track.md` | `templates/track-template.md` |
| `courses/<slug>/course.md` | `templates/course-template.md` |
| `lectures/NN-topic/notes.md` | `templates/notes-template.md` |
| `lectures/NN-topic/open-questions.md` | `templates/open-questions-template.md` |
| `assignments/NN_name.md` | `templates/assignment-template.md` |
| `quizzes/NN_name.md` | `templates/quiz-template.md` |

## Scripts

| Script | Use |
|---|---|
| `scripts/setup_semester.py init --semester N --degree "..." --subject "..."` | Create `University/`, `semester.md`, the semester folder, `track.md`, and one course per subject. Idempotent. |
| `scripts/setup_semester.py add-subject --name "..."` | Add one subject to the current semester. |
| `scripts/setup_semester.py list` | Show the current semester and every course with its lecture, assignment, and quiz counts. |
| `scripts/setup_semester.py next-number --subject "..." --kind quiz` | Next free `NN` for a lecture, assignment, or quiz. |
| `scripts/extract_content.py <file> [--notes] [--pages N-M] [--out file] [--check]` | Extract searchable content from PDF, PPTX, or DOCX. For PPTX use `--notes` to include speaker notes. Uses PyMuPDF if available, falls back to pypdf; PPTX/DOCX use the standard library. |

Both scripts are read-and-report safe. Re-running a command adds only what is missing.
