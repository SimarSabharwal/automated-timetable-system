# Real-Time Smart Academic ERP — Automated Timetable & Venue Allotment System

A comprehensive, zero-conflict college timetable generation and room allocation module. Built with Flask, SQLite, and vanilla ES-module frontend, featuring **Admin, Teacher, and Student** portals, **Lifetime & Dated scheduling**, **Building Room Master with Co-Curricular venues**, and strict **Student System uniqueness clauses**.

---

## 🌟 Key Features

### 1. Three Dedicated Role Portals
- **Admin Panel**: Complete scheduling command center:
  - **Self-Assigned (Manual) Allotment**: Conflict-checked manual slot assignment with mandatory reasons.
  - **Automation (Smart)**: Batch generator for selected section, entire year, or entire course.
  - **Co-Curricular Booking**: Rough-timing venue booking (`09:00–10:00`, `11:00–12:00`, etc.) for clubs, societies, and cultural rehearsals.
  - **Building Room Master**: Real-time room inventory, maintenance toggling, and live occupancy inspection.
  - **Teacher Clauses & Calendar**: Faculty qualifications, leave/unavailability windows, and academic calendar exclusions.
  - **Curriculum & Subjects**: Manage courses, years, subjects, and weekly lecture quotas.
- **Teacher Panel**:
  - Live weekly schedule showing all assigned lectures and co-curricular sessions.
  - Room numbers, class details, validity indicators, and assignment reasons.
  - Self-service unavailability / leave reporting form.
- **Student Panel**:
  - Course, Year, Shift, Section selector with 30 students per class.
  - Live class timetable automatically reflecting admin allocations.
  - 30-student class roster with roll numbers and ERP IDs.
  - Campus co-curricular and club venue schedule.

---

### 2. Academic Course & Section Architecture
- **BCA (Bachelor of Computer Applications)**: 3 Years, 2 Shifts (Morning & Afternoon). **Grade-wise** scheduling (no section divisions).
- **BBA (Bachelor of Business Administration)**: 3 Years, 2 Shifts (Morning sections M1–M3, Afternoon sections A1–A3).
- **MBA (Master of Business Administration)**: 1 Year, Morning shift only (Sections M1–M2).
- **LLB (Integrated 5-Year Law)**: 5 Years, 2 Shifts (Morning sections M1–M2, Afternoon sections A1–A2).
- **Pre-Seeded Roster**: 30 students per class/section (1,380 students total with ERP IDs and roll numbers).

---

### 3. Comprehensive Building Room Master (30 Venues)
- **Ground Floor (`G01`–`G04`)**:
  - `G01`, `G02`, `G03`: Classrooms (Capacity 65–70).
  - `G04`: **Computer Lab** (Capacity 60).
- **First Floor (`101`–`108`)**:
  - `101`, `102`, `103`, `105`, `106`, `108`: Classrooms (Capacity 65).
  - `104`, `107`: **Computer Labs** (Capacity 60).
- **Second Floor (`201`–`208`)**: 8 Classrooms (Capacity 65, strictly no labs).
- **Third Floor (`301`–`308`)**: 8 Classrooms (Capacity 65, strictly no labs).
- **Co-Curricular Venues**:
  - **`AMPHITHEATER`**: Cultural Wing, Ground Floor (Capacity 300).
  - **`AUDITORIUM`**: Main Block, Ground Floor (Capacity 500).
  - *Rule*: Amphitheater and Auditorium are strictly reserved for Co-Curricular / Society events and excluded from regular academic course scheduling.

---

### 4. Scheduling Modes
1. **Self-Assigned (Manual)**:
   - Select Day, Shift, Slot, Subject, Faculty, Room, and Lifetime/Dated validity.
   - Requires a mandatory reason (e.g., Primary class, Faculty request, Lab session).
2. **Automation (Smart)**:
   - Generates conflict-free timetable across working days.
   - Prioritizes section's primary room when available.
   - Balances subject frequency according to weekly requirements.
   - Preserves manual / self-assigned entries.
3. **Co-Curricular Assignment**:
   - Independent of course or fixed lecture slot structure.
   - Uses rough timings (`From Time` → `To Time`, with presets for `9:00–10:00`, `11:00–12:00`, `14:00–16:00`).
   - Supports Amphitheater, Auditorium, and standard rooms.
   - Captures Society / Event name and optional Teacher In-Charge.

---

### 5. Strict Uniqueness Clauses & Constraints
- **Holiday & Exam Exclusion**: Any dated allotment falling within an academic event (`HOLIDAY` or `EXAM`) is strictly rejected with a calendar clause conflict.
- **Room Uniqueness**: Prevents double-booking across all courses, shifts, and co-curricular time intervals.
- **Teacher Double-Booking & Unavailability**: Teachers cannot be in two rooms simultaneously; unapproved bookings during unavailability windows are blocked.
- **Teacher Repeat Clause**: Prevents consecutive back-to-back lectures for the same class by the same teacher.
- **Max Daily Subject Quota**: A section cannot have more than 2 lectures of the same subject on the same day.
- **Teacher Qualification Lock**: Enforces `teacher_subjects` mapping—teachers can only be assigned to subjects they are qualified to teach (no generic substitutes).
- **Lab Requirements**: Lab subjects (`requires_lab=1`) can only be scheduled into rooms designated as `COMPUTER_LAB`.
- **Dynamic Reallocation**: Automatically shifts affected sessions to compatible alternative rooms or qualified subjects without generic substitution.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+ (tested on Python 3.12 and 3.14)
- Modern web browser (Chrome, Firefox, Edge, Safari)

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd "automated time table generator"
   ```

2. **Create and activate a virtual environment**:
   ```bash
   # Windows PowerShell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize Database & Start Server**:
   ```bash
   python app.py
   ```
   The database (`timetable.db`) and all seed data (courses, sections, 28 rooms + 2 event venues, faculty, subjects, qualifications, and 1,380 students) are initialized automatically.

5. **Open in Browser**:
   Navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 🧪 Running Automated Tests

Run the test suite verifying all Student System clauses, lifetime/dated scheduling, room constraints, co-curricular venue booking, and portals:

```bash
python test_scheduler.py
```

Expected output:
```text
ALL STUDENT SYSTEM CLAUSES & LIFETIME/DATED TESTS PASSED!
```

---

## 📂 Project Structure

```text
├── app.py                      # Flask application factory, REST APIs & portal endpoints
├── db.py                       # SQLite schema, GiST-equivalent constraint logic & seeders
├── scheduler.py                # Conflict solver, automation engine & reallocation logic
├── test_scheduler.py           # Automated test suite for all scheduling clauses & constraints
├── requirements.txt            # Python dependencies (Flask >= 3.0.0)
├── .gitignore                  # Git ignore rules
├── templates/
│   └── index.html              # Single-page interface (Admin, Teacher, and Student portals)
├── static/
│   ├── app.js                  # Frontend ES module controller & API bindings
│   └── styles.css              # Custom responsive stylesheet & role-based themes
├── sample_data/                # Raw catalog and reference datasets
│   ├── sample_data.json
│   ├── dev_demo_seed.json
│   └── mock_catalog_winter_2026.json
└── docs/                       # Technical architecture & specification documents
    ├── PRD.md                  # Product Requirements Document
    ├── DATABASE_DESIGN.md      # PostgreSQL 29-table schema & exclusion specifications
    ├── TECH_STACK_TRD.md       # Technical Requirements Document
    └── TIMETABLE_GENERATOR_SPEC.md
```

---

## 📡 REST API Summary

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/bootstrap` | Bootstraps courses, sections, rooms, faculty, subjects, slots, and calendar events |
| `GET` | `/api/v1/timetable` | Retrieves timetable entries (filterable by `section_id`) |
| `POST` | `/api/v1/timetable/manual` | Creates a Self-Assigned or Co-Curricular allotment |
| `POST` | `/api/v1/timetable/automate` | Runs automated conflict-free timetable generation |
| `DELETE` | `/api/v1/timetable/<id>` | Releases / deletes an allotment |
| `POST` | `/api/v1/timetable/<id>/reallocate` | Dynamically reallocates a disrupted slot |
| `GET` | `/api/v1/rooms/availability` | Checks live room availability for day, shift, slot, or time window |
| `POST` | `/api/v1/rooms` | Adds a new room to Building Room Master |
| `PATCH` | `/api/v1/rooms/<id>` | Updates room status (`ACTIVE` / `MAINTENANCE`) or capacity |
| `GET` | `/api/v1/portal/teacher/<id>` | Fetches schedule and qualifications for Teacher Portal |
| `GET` | `/api/v1/portal/student/<id>` | Fetches timetable, classmates roster, and club events for Student Portal |
| `GET` | `/api/v1/students` | Lists enrolled students (supports search and section filter) |

---

## 🛡️ License

This project is licensed under the MIT License.
