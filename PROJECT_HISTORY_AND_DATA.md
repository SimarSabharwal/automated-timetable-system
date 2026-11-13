# Project History, Server Architecture & User-Provided Data

This document captures the complete history of how the **BVP Student System** server was built, every architectural decision made along the way, what was verified vs. what remains partial, and all datasets/inputs provided by the user.

---

## 1. Origin: The Legacy Prototype (`old version/`)

The project started as a lightweight, in-memory Flask prototype (`old version/app.py`) with static HTML/CSS/JS templates (`index.html`, `student_login.html`, `student_dashboard.html`, `faculty_login.html`, `faculty_dashboard.html`, `style.css`, `animations.css`, `main.js`).

### What the Old Prototype Contained
- **Hardcoded Demo Accounts:**
  - Students: `0251BCA001` ("Student Morning", shift `M`) and `0251BCA101` ("Student Afternoon", shift `A`), both with plaintext password `"1234"`.
  - Faculty: `MKC` ("Dr. Mahesh Kumar Chaubey") with plaintext password `"mkc123"`.
  - Runtime-only empty dicts `REGISTERED_STUDENTS` and `REGISTERED_FACULTY`.
- **Hardcoded Subjects (9 codes):**
  - `JP` (Java Programming), `OS` (Operating Systems), `SE` (Software Engineering), `ST` (Statistics), `SUM` (Start-up Management), `LAB JP` (Java Programming Lab), `LAB ORACLE` (Oracle Lab), `YOGA` (Yoga & Meditation), and `BREAK`.
- **Hardcoded Faculty Name Codes (9 codes):**
  - `MGS` (Dr. Megha Sehgal), `MAG` (Dr. Mansi Agnihotri), `DSB` (Dr. Daljeet Singh Bawa), `UG` (Dr. Usha Gupta), `MKC` (Dr. Mahesh Kumar Chaubey), `AK` (Dr. Ajay Kumar), `AKR` (Mr. Amit Kumar), `YK` (Mr. Yashwant Kumar), `NPN` (Mr. Nripesh Kumar).
- **Hardcoded Timetable (`MORNING` and `AFTERNOON`):**
  - 50 total entries across weekdays including 10 `BREAK` slots.
  - Room labels: `AK108`, `UG104`, `FF LAB`, `108`, `109`.
- **Limitations:** No database, no migrations, no conflict checking, no course/year/semester/section/capacity/qualification mappings, and no real-time updates.

All literal data from that prototype was extracted into `sample_data/sample_data.json` and preserved strictly as demo-only unmapped data.

---

## 2. How the Production Server Was Built (Phase 0 to Phase 10)

### Phase 0 — Decisions & Schema Planning (2026-10-15)
Before writing backend code, all schema-critical and operational decisions were locked down:
- **Hosting & Database Target:** Render Web Service (Flask + Gunicorn) + Managed PostgreSQL 18 (Singapore region recommended; never free Render Postgres for prod). Currently, no Render resources are provisioned—everything runs locally on PostgreSQL 18.
- **Timezone:** `Asia/Kolkata`. All instants stored as `timestamptz`; recurring timetable wall-clock times interpreted in `Asia/Kolkata`.
- **Identity & Multi-Role RBAC:** Login IDs are Student ERP ID or Faculty Code. A single user can hold multiple explicit roles (`STUDENT`, `TEACHER`, `ADMIN`).
- **Availability & Reallocation Policy:** Teachers can report unavailability; Admins can enter or override it. Reallocation defaults to **suggest-and-approve** (per PRD FR-6.4, Admins can configure auto-apply).
- **Attendance Policy:** `EXCUSED` is excluded from the attendance percentage denominator. Only Admins may correct attendance after a session is closed.
- **Dated Session Generation:** Publishing a timetable materializes dated `class_sessions` across the full effective period, automatically skipping `HOLIDAY` and `EXAM` academic events.
- **MVP Scope:** Section-based sessions. Lab subgroups and cross-section shared lectures are deferred past MVP.
- **Data Integrity Rule:** Never guess missing institutional mappings (rooms, capacities, enrollments, qualifications) from old sample data.

### Phase 1 — Backend Foundation (2026-10-15)
- Built the Flask application factory (`app/__init__.py`), environment config (`app/config.py`), SQLAlchemy 2.0 lazy request-scoped sessions (`app/extensions.py`), Gunicorn entrypoint (`wsgi.py`), `/api/v1` blueprint with `/api/v1/health`, structured JSON errors with request IDs, and `openapi.yaml`.

### Phase 2 — Normalized PostgreSQL Schema & Migrations (2026-10-15 / 2026-10-16)
- Implemented **29 normalized tables** in `app/models/__init__.py` and Alembic migrations (`migrations/versions/0001_initial_schema.py` through `0004_subject_course.py`).
- Added **6 PostgreSQL GiST exclusion constraints** (`btree_gist`) using half-open intervals `[start, end)` so adjacent classes are allowed while overlapping classes for the same **section**, **teacher**, or **room** are rejected at the database level.
- Composite foreign keys bind timetable entries and dated sessions to exact section/subject/qualified teaching assignments.
- Verified with live PostgreSQL 18: upgrade, downgrade, re-upgrade, adjacent-slot allowance, and overlap rejection all passed.

### Phase 3 — Seed & Data Migration Framework (2026-10-15 / 2026-10-16)
- Created `scripts/seed_dev.py` and `sample_data/dev_demo_seed.json` containing only verified sample identities (`0251BCA001`, `0251BCA101`, `MKC`) and the 8 subject codes without inferred mappings.
- Verified transactional rollback on conflict and idempotency across repeated runs.

### Phases 4 & 5 — Auth, RBAC & Master Data APIs (2026-10-16)
- **Auth (`app/api/v1/auth.py`):** Signed HTTP-only/SameSite session cookies storing only `user_id`; active status and roles loaded from PostgreSQL on every protected request. Werkzeug password hashes, login throttling/lockout (5 failures in 15 min -> 15-min lock), CSRF protection on cookie writes, and `scripts/create_admin.py`.
- **Master Data (`app/api/v1/master_data.py`):** Admin CRUD for academic years, courses, sections, subjects, enrollments, `SectionSubject` curricula, `TeacherSubject` qualifications, `TeachingAssignment`s, rooms, and room features. Soft-deactivation instead of physical delete; bounded 100-row projections.

### Phase 6 — Scheduling & Publication (2026-10-16)
- Implemented `app/api/v1/scheduling.py` for draft `TimetableVersion` / `TimetableEntry` management, constraint-checked publication into dated `ClassSession` rows, availability/academic-event APIs, and bounded free-slot queries.

### Phase 7 — Dynamic Lecture Reallocation (2026-10-16)
- Implemented `app/api/v1/reallocation.py`: analyzes unavailable teachers/rooms, filters valid candidates by hard constraints (capacity, lab type, active assignment, availability), scores candidates by curriculum backlog, and supports **depth-2 grouped cascade moves** with atomic approve/reject/revert, audit logs, outbox events, and notifications.

### Phase 8 — Attendance, Communications & Reports (2026-10-16)
- Implemented `app/api/v1/attendance.py`, `communications.py`, and `reports.py`: open/mark/close attendance, date-effective enrollment checks, admin-only closed-session corrections, recovered-lecture completion links, `EXCUSED`-excluding summaries, role/section-scoped announcements, and 5 admin reports.

### Phase 9 — Realtime WebSockets, Security & Load Baseline (2026-10-16) — *Partial*
- Added `Flask-Sock` WebSocket endpoint (`/api/v1/ws/events`), transactional outbox dispatcher (`scripts/dispatch_outbox.py`), and `scripts/benchmark_phase9.py`.
- **Status:** Local synthetic 100-client fanout and security review completed, but Phase 9 remains **Partial** pending representative institutional load tests and Render deployment verification (TLS/proxy WebSocket upgrade, backups, pool limits).

### Phase 10 — Glassmorphism Frontend, Winter 2026 Catalog & Smart Timetable (2026-10-16) — *Partial*
- Built a native ES-module SPA (`app/templates/index.html`, `app/static/css/glassmorphism.css`, `app/static/js/`) with Student, Teacher, and Admin dashboards, role switching, CSRF headers, and WebSocket live updates.
- Added the **Winter 2026 PDF Catalog** (`sample_data/mock_catalog_winter_2026.json` + `mock_data.py`) and **Smart Timetable Creation** (`smart_timetable.py` + `admin.js`).
- **Status:** Core UI, auth boundaries, mock seeder, and draft generation work end-to-end on the local PostgreSQL 18 demo. Phase 10 remains **Partial** until full role/attendance/notification acceptance walkthroughs and formal accessibility checks are completed.

---

## 3. Everything the User Provided (Data & Rules)

1. **Legacy Flask Prototype (`old version/`):**
   - Original `app.py` with 2 students, 1 faculty login, 9 faculty codes, 9 subjects, and 50 hardcoded morning/afternoon timetable entries.
2. **Winter 2026 Theory Examination PDF (CBCS 2026, BCA & BBA Sem-I):**
   - **Rule enforced:** Used *strictly* as a subject catalog for BCA and BBA Semester I. Examination dates and times were **deliberately not** imported as recurring class periods.
   - **BCA Sem-I Subjects (4):** `34344` Algorithms & Program Design Using C, `34345` Mathematical Foundation, `34346` Foundations of Computing, `34347` Client-Side Web Technologies.
   - **BBA Sem-I Subjects (6):** `34136` Principles of Management, `34137` Business Communication, `34138` Financial Accounting: Concepts & Practices, `34139` Business Mathematics, `34140` Micro Economics (Optional 1), `34142` Environmental Studies.
3. **Literal Course `B` Requirement:**
   - User requested retaining literal course code `B`. Because the PDF contained no catalog for `B`, four explicitly synthetic placeholder subjects (`B-DEMO-01` through `B-DEMO-04`) were created for Course `B`.
4. **Linked Synthetic Mock Dataset (`mock_data.py`):**
   - Authorized on 2026-10-16 for local demo/testing only:
     - **3 Courses:** `BCA`, `BBA`, `B`
     - **9 Sections:** `BCA` (`M1` Morning, `A1` Afternoon), `BBA` (`M1–M3` Morning, `A1–A3` Afternoon), `B` (`M1` Morning) — capacity `40` each
     - **14 Subjects:** 4 BCA + 6 BBA + 4 synthetic B
     - **9 Rooms:** `Mock Building` `M-01` through `M-09`, capacity `50`, type `NORMAL`
     - **9 Mock Students:** `MOCK-STU-01` through `MOCK-STU-09`
     - **48 Mock Teachers:** `MOCK-TCH-011` through `MOCK-TCH-094` (mapped with `TeacherSubject` + `TeachingAssignment`)
5. **Timetable Shift & Slot Rules:**
   - **4 lectures per day** per section.
   - **Morning Shift window:** `09:10` to `13:15` (e.g., 55-min lectures + breaks).
   - **Afternoon Shift window:** `13:30` to `16:30`.
   - **Generated Demo Drafts:** 9 unpublished draft versions covering `2026-10-19` through `2026-10-23` (180 recurring entries total).

---

## 4. Local Runtime & Database Setup

- **PostgreSQL 18 Demo Cluster:** Stored in ignored `.local-demo-postgres/`, listening on `127.0.0.1:55432`, database `student_system_demo`, user `student_demo`.
- **Flask Server:** Runs via `.venv314\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5050 --no-reload`.
- **Demo Accounts:** Listed in ignored `reports/demo-credentials.txt` (`admin-demo`, `MKC`, `0251BCA001`, `0251BCA101`, `MOCK-STU-*`, `MOCK-TCH-*`). All share the generated local-only demo password in that file.
