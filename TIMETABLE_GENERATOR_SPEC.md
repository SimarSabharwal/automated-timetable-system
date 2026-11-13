# Automated Timetable Generator — Technical Specification

This document details the exact API contract, constraint solver logic, publication pipeline, and dynamic reallocation engine contained in `src/`.

---

## 1. Smart Timetable Generation (`src/smart_timetable.py`)

### Endpoint
`POST /api/v1/admin/smart-timetables/generate`
- **Auth:** `ADMIN` role + valid CSRF token.
- **Output:** Creates `DRAFT` `TimetableVersion` records (one per selected section) and `TimetableEntry` rows. Does **not** auto-publish.

### Required JSON Payload
All 14 keys are strictly required:

```json
{
  "academic_year_id": 1,
  "course_ids": [1, 2, 3],
  "effective_from": "2026-10-19",
  "effective_to": "2026-10-23",
  "weekdays": [0, 1, 2, 3, 4],
  "lectures_per_day": 4,
  "morning_start": "09:10",
  "morning_end": "13:15",
  "morning_lecture_minutes": 55,
  "morning_break_minutes": 10,
  "afternoon_start": "13:30",
  "afternoon_end": "16:30",
  "afternoon_lecture_minutes": 40,
  "afternoon_break_minutes": 5
}
```

### Validation & Constraint Rules
1. **Date & Slot Window Checks:**
   - `effective_from <= effective_to`, max span `371` days, must fall inside `AcademicYear.starts_on..ends_on`.
   - `lectures_per_day` must be `4`; lecture duration `1..180` min; break `0..60` min.
   - All 4 computed slots + gaps must fit strictly within `morning_start..morning_end` (for `MORNING` sections) and `afternoon_start..afternoon_end` (for `AFTERNOON` sections).
2. **Overlap Guard Against Existing Versions:**
   - Rejects with `409 Conflict` if any selected section already has an overlapping `DRAFT` or `PUBLISHED` `TimetableVersion` in `[effective_from, effective_to]`.
3. **Curriculum & Qualification Gate:**
   - Each section must have `SectionSubject` curriculum rows and active `TeachingAssignment` rows matching the section's `course_id`, `semester`, and date range.
4. **Resource Grid & Hard Constraints (Per Weekday, Section, Slot):**
   - **Distinct Subject Preference:** Prefers subjects not yet scheduled on the same weekday for that section (if `>= 4` distinct subjects exist).
   - **Room Suitability:** `Room.status == "ACTIVE"`, `Room.capacity >= Section.capacity`, and if `Subject.requires_lab` is true, `Room.room_type` must be `COMPUTER_LAB` or `SCIENCE_LAB`.
   - **Unavailability Windows:** Checks `TeacherAvailability` and `RoomAvailability` (`UNAVAILABLE`) across every matching calendar date in `[effective_from, effective_to]`.
   - **Zero Double-Booking:** Rejects any candidate where `teacher_id`, `room_id`, or `section_id` overlaps an already-placed draft entry or an existing active `TimetableEntry` on that weekday.
   - **Atomic Failure:** If any slot for any section cannot be placed conflict-free, aborts with `422` and saves nothing.
5. **Holiday / Exam Exclusion Preview:**
   - Evaluates `AcademicEvent` rows (`HOLIDAY`, `EXAM`) across `[effective_from, effective_to]` and returns `required_dates`, `excluded_dates`, and `partial_exclusions`.

---

## 2. Timetable Publication (`src/scheduling.py`)

### Endpoint
`POST /api/v1/admin/timetable-versions/<version_id>/publish`
- Transitions a `DRAFT` `TimetableVersion` to `PUBLISHED` (making its entries immutable).
- Iterates every calendar day in `[effective_from, effective_to]`, matches `TimetableEntry.weekday`, skips `HOLIDAY`/`EXAM` events and `UNAVAILABLE` teacher/room windows, and inserts dated `ClassSession` records.
- Protected at the PostgreSQL layer (`src/models.py`) by **GiST exclusion constraints** preventing overlapping `PUBLISHED` versions and overlapping `ClassSession`s for the same section, teacher, or room.

---

## 3. Dynamic Lecture Reallocation (`src/reallocation.py`)

When a teacher or room is marked `UNAVAILABLE` for a dated `ClassSession`:
1. **No Generic Substitutes:** Only active `TeachingAssignment`s belonging to the affected section are eligible.
2. **Hard Constraint Verification (`_conflict`):** Validates active assignment, room capacity `>=` section capacity, lab room type, teacher/room availability, no holiday/exam overlap, and no section/teacher/room booking collision.
3. **Depth-2 Cascade Resolution (`_plan_move`):** If a target slot is blocked by another session, recursively attempts to shift blockers within an 8-day, `08:00–18:00` (30-min grid) window up to `max_cascade_depth` (bounded at 2).
4. **Policy & Notifications:** Respects `SchedulingPolicy` (`SUGGEST_AND_APPROVE` by default, or `AUTO_APPLY`), records `AuditEvent` and `PendingLecture` recovery links, and queues `Notification` + `OutboxEvent` records for real-time WebSocket delivery.

---

## 4. Database Tables Involved (`src/models.py`)

- **Academic Structure:** `academic_years`, `courses`, `subjects`, `sections`, `section_subjects`
- **People & Rooms:** `teachers`, `teacher_subjects`, `teaching_assignments`, `rooms`, `room_features`
- **Availability & Events:** `teacher_availability`, `room_availability`, `academic_events`
- **Timetables & Sessions:** `timetable_versions`, `timetable_entries`, `class_sessions`
- **Reallocation & Policy:** `scheduling_policies`, `reallocations`, `pending_lectures`, `audit_events`, `outbox_events`, `notifications`
