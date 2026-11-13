from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
WEEKDAY_TO_INT = {name: idx for idx, name in enumerate(WEEKDAYS)}
EVENT_ONLY_ROOM_TYPES = ("AMPHITHEATER", "AUDITORIUM")

DEFAULT_SHIFT_CONFIG = {
    "MORNING": {
        "start": "09:10",
        "lecture_minutes": 55,
        "break_minutes": 10,
        "break_after_slot": 2,
    },
    "AFTERNOON": {
        "start": "13:30",
        "lecture_minutes": 40,
        "break_minutes": 5,
        "break_after_slot": 2,
    },
}

# Reusable SQL predicate for LIFETIME vs DATED overlap
OVERLAP_PREDICATE = """
    (? = 'LIFETIME' OR te.validity_type = 'LIFETIME' OR (te.effective_from <= ? AND ? <= te.effective_to))
"""


def _overlap_params(validity_type: str, effective_from: str | None, effective_to: str | None) -> tuple[str, str, str]:
    if validity_type == "LIFETIME":
        return ("LIFETIME", "9999-12-31", "0001-01-01")
    return ("DATED", effective_to or effective_from or "9999-12-31", effective_from or "0001-01-01")


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(total_minutes: int) -> str:
    h = (total_minutes // 60) % 24
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def compute_shift_slots(shift: str, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = (config or {}).get(shift) or DEFAULT_SHIFT_CONFIG[shift]
    cur = _to_minutes(cfg["start"])
    lec_min = int(cfg["lecture_minutes"])
    brk_min = int(cfg["break_minutes"])
    break_after = int(cfg.get("break_after_slot", 2))

    slots = []
    for idx in range(1, 5):
        s_str = _to_hhmm(cur)
        e_str = _to_hhmm(cur + lec_min)
        slots.append({"slot_index": idx, "start_time": s_str, "end_time": e_str})
        cur += lec_min
        cur += brk_min if idx == break_after else 5
    return slots


def _format_validity(validity_type: str, effective_from: str | None, effective_to: str | None) -> str:
    if validity_type == "LIFETIME":
        return "Lifetime"
    if effective_from == effective_to:
        return f"Date: {effective_from}"
    return f"{effective_from} to {effective_to}"


def check_slot_conflict(
    conn: sqlite3.Connection,
    *,
    section_id: int | None,
    day_of_week: str,
    shift: str,
    slot_index: int,
    room_id: int,
    faculty_id: int | None,
    subject_id: int | None,
    start_time: str | None = None,
    end_time: str | None = None,
    allocation_category: str = "COURSE",
    validity_type: str = "LIFETIME",
    effective_from: str | None = None,
    effective_to: str | None = None,
    exclude_entry_id: int | None = None,
) -> list[str]:
    """Validate all Student System hard constraints, Co-Curricular venue locks & time/date overlaps."""
    conflicts: list[str] = []
    is_club = allocation_category == "CLUB_EXTRACURRICULAR"

    if not start_time or not end_time:
        slots = compute_shift_slots(shift if shift in DEFAULT_SHIFT_CONFIG else "MORNING")
        slot_info = next((s for s in slots if s["slot_index"] == slot_index), None)
        if not slot_info:
            return ["Invalid slot index or timing."]
        start_time = slot_info["start_time"]
        end_time = slot_info["end_time"]

    if start_time >= end_time:
        return ["Start time must be before End time."]

    if validity_type == "DATED":
        if not effective_from or not effective_to:
            return ["Dated allotment requires both Effective From and Effective To dates."]
        if effective_from > effective_to:
            return ["Effective From date cannot be after Effective To date."]

    section = None
    if not is_club:
        section = conn.execute(
            """
            SELECT s.*, c.code AS course_code
            FROM sections s JOIN courses c ON c.id = s.course_id
            WHERE s.id = ?
            """,
            (section_id,),
        ).fetchone()
        if not section:
            return ["Selected section not found."]

    room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        return ["Selected room not found."]

    if room["status"] != "ACTIVE":
        conflicts.append(
            f"Room {room['room_code']} is currently marked as {room['status']} and cannot be allotted."
        )

    if not is_club and room["room_type"] in EVENT_ONLY_ROOM_TYPES:
        conflicts.append(
            f"{room['room_code']} ({room['room_type']}) is reserved for Co-Curricular events only and cannot be allotted to courses."
        )

    if section and room["capacity"] < section["capacity"]:
        conflicts.append(
            f"Room {room['room_code']} capacity ({room['capacity']}) is smaller than section capacity ({section['capacity']})."
        )

    subject = None
    if not is_club:
        subject = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        if not subject:
            return ["Selected subject not found."]

        if subject["requires_lab"] and room["room_type"] != "COMPUTER_LAB":
            conflicts.append(
                f"Subject '{subject['subject_name']}' is a lab subject and requires a dedicated COMPUTER_LAB (e.g. G04, 104, 107), but {room['room_code']} is {room['room_type']}."
            )
        elif not subject["requires_lab"] and room["room_type"] == "COMPUTER_LAB":
            conflicts.append(
                f"Subject '{subject['subject_name']}' is a theory subject and must be assigned to a standard CLASSROOM. Computer labs are dedicated exclusively to lab practicals."
            )
        elif not subject["requires_lab"] and room["room_type"] in EVENT_ONLY_ROOM_TYPES:
            conflicts.append(
                f"Subject '{subject['subject_name']}' is a regular course lecture and cannot be scheduled in {room['room_type']}. Regular courses must use CLASSROOM or COMPUTER_LAB."
            )

    # Clause 4 (Student System): Holiday / Exam Exclusion for DATED allotments
    if validity_type == "DATED" and effective_from and effective_to:
        d_start = dt.date.fromisoformat(effective_from)
        d_end = dt.date.fromisoformat(effective_to)
        target_wd = WEEKDAY_TO_INT.get(day_of_week)
        events = conn.execute(
            "SELECT * FROM academic_events WHERE start_date <= ? AND ? <= end_date",
            (effective_to, effective_from),
        ).fetchall()
        for ev in events:
            ev_s = max(d_start, dt.date.fromisoformat(ev["start_date"]))
            ev_e = min(d_end, dt.date.fromisoformat(ev["end_date"]))
            cur_d = ev_s
            while cur_d <= ev_e:
                if d_start == d_end or target_wd is None or cur_d.weekday() == target_wd:
                    conflicts.append(
                        f"Holiday/Exam Clause: Cannot assign class on {cur_d.isoformat()} — marked as {ev['event_type']} '{ev['title']}'."
                    )
                    break
                cur_d += dt.timedelta(days=1)
            if conflicts:
                break

    # Clause 1 (Student System): Teacher Qualification Lock (Course classes only)
    if not is_club and faculty_id is not None and subject is not None:
        fac = conn.execute("SELECT * FROM faculty WHERE id = ?", (faculty_id,)).fetchone()
        if not fac:
            return ["Selected faculty not found."]

        qual = conn.execute(
            "SELECT 1 FROM teacher_subjects WHERE faculty_id = ? AND subject_id = ?",
            (faculty_id, subject_id),
        ).fetchone()
        if not qual:
            conflicts.append(
                f"Qualification Clause: {fac['full_name']} ({fac['faculty_code']}) is not qualified/mapped to teach '{subject['subject_name']}' (no generic substitutes allowed)."
            )

        # Clause 2 (Student System): Teacher Unavailability Window
        if validity_type == "DATED" and effective_from and effective_to:
            unavail = conn.execute(
                """
                SELECT * FROM teacher_availability
                WHERE faculty_id = ? AND (shift = 'ALL' OR shift = ?)
                  AND start_date <= ? AND ? <= end_date
                """,
                (faculty_id, shift, effective_to, effective_from),
            ).fetchone()
            if unavail:
                conflicts.append(
                    f"Availability Clause: {fac['full_name']} is marked UNAVAILABLE ({unavail['start_date']} to {unavail['end_date']}, Reason: {unavail['reason'] or 'N/A'})."
                )
        else:
            unavail = conn.execute(
                """
                SELECT * FROM teacher_availability
                WHERE faculty_id = ? AND (shift = 'ALL' OR shift = ?)
                """,
                (faculty_id, shift),
            ).fetchone()
            if unavail:
                conflicts.append(
                    f"Availability Clause: {fac['full_name']} has an unavailability window ({unavail['start_date']} to {unavail['end_date']}); use a non-overlapping Dated allotment or clear unavailability."
                )

    ov = _overlap_params(validity_type, effective_from, effective_to)

    # 1. Room double-booking check (time-interval overlap across ALL courses AND co-curricular)
    params: list[Any] = [room_id, day_of_week, end_time, start_time, *ov]
    room_sql = f"""
        SELECT te.id, te.allocation_category, te.custom_title, te.start_time, te.end_time,
               c.code AS course_code, s.year_number, s.section_code,
               sub.subject_name, te.reason, te.validity_type, te.effective_from, te.effective_to
        FROM timetable_entries te
        LEFT JOIN sections s ON s.id = te.section_id
        LEFT JOIN courses c ON c.id = s.course_id
        LEFT JOIN subjects sub ON sub.id = te.subject_id
        WHERE te.room_id = ? AND te.day_of_week = ?
          AND te.start_time < ? AND ? < te.end_time
          AND {OVERLAP_PREDICATE}
    """
    if exclude_entry_id is not None:
        room_sql += " AND te.id != ?"
        params.append(exclude_entry_id)

    booked_room = conn.execute(room_sql, params).fetchone()
    if booked_room:
        val_txt = _format_validity(
            booked_room["validity_type"], booked_room["effective_from"], booked_room["effective_to"]
        )
        reason_note = f" — Reason: {booked_room['reason']}" if booked_room["reason"] else ""
        if booked_room["allocation_category"] == "CLUB_EXTRACURRICULAR":
            owner = f"Co-Curricular '{booked_room['custom_title']}'"
        else:
            owner = (
                f"{booked_room['course_code']} Year {booked_room['year_number']} Sec {booked_room['section_code']} "
                f"for {booked_room['subject_name']}"
            )
        conflicts.append(
            f"Room {room['room_code']} is ALREADY BOOKED on {day_of_week} ({booked_room['start_time']}–{booked_room['end_time']}, {val_txt}) by {owner}{reason_note}."
        )

    if not is_club and section is not None and subject is not None:
        # 2. Section double-booking check (date/lifetime-aware)
        sec_params: list[Any] = [section_id, day_of_week, slot_index, *ov]
        sec_sql = f"""
            SELECT te.id, sub.subject_name, r.room_code, te.validity_type, te.effective_from, te.effective_to
            FROM timetable_entries te
            JOIN subjects sub ON sub.id = te.subject_id
            JOIN rooms r ON r.id = te.room_id
            WHERE te.section_id = ? AND te.day_of_week = ? AND te.slot_index = ?
              AND {OVERLAP_PREDICATE}
        """
        if exclude_entry_id is not None:
            sec_sql += " AND te.id != ?"
            sec_params.append(exclude_entry_id)

        booked_sec = conn.execute(sec_sql, sec_params).fetchone()
        if booked_sec:
            val_txt = _format_validity(
                booked_sec["validity_type"], booked_sec["effective_from"], booked_sec["effective_to"]
            )
            conflicts.append(
                f"{section['course_code']} Year {section['year_number']} Sec {section['section_code']} "
                f"already has '{booked_sec['subject_name']}' in Room {booked_sec['room_code']} ({val_txt}) at this slot."
            )

        # Max 2 lectures of same subject per day for a class/section
        sub_day_params: list[Any] = [section_id, day_of_week, subject_id, *ov]
        sub_day_sql = f"""
            SELECT COUNT(*) FROM timetable_entries te
            WHERE te.section_id = ? AND te.day_of_week = ? AND te.subject_id = ? AND {OVERLAP_PREDICATE}
        """
        if exclude_entry_id is not None:
            sub_day_sql += " AND te.id != ?"
            sub_day_params.append(exclude_entry_id)
        if conn.execute(sub_day_sql, sub_day_params).fetchone()[0] >= 2:
            conflicts.append(
                f"Uniqueness Clause: '{subject['subject_name']}' already has 2 lectures on {day_of_week} for this class (max 2 allowed)."
            )

    # 3. Faculty double-booking, Consecutive Teacher Repeat & Max Daily Workload check
    if faculty_id is not None:
        fac_params: list[Any] = [faculty_id, day_of_week, end_time, start_time, *ov]
        fac_sql = f"""
            SELECT te.id, te.allocation_category, te.custom_title, f.full_name,
                   c.code AS course_code, s.year_number, s.section_code, r.room_code
            FROM timetable_entries te
            JOIN faculty f ON f.id = te.faculty_id
            LEFT JOIN sections s ON s.id = te.section_id
            LEFT JOIN courses c ON c.id = s.course_id
            JOIN rooms r ON r.id = te.room_id
            WHERE te.faculty_id = ? AND te.day_of_week = ?
              AND te.start_time < ? AND ? < te.end_time
              AND {OVERLAP_PREDICATE}
        """
        if exclude_entry_id is not None:
            fac_sql += " AND te.id != ?"
            fac_params.append(exclude_entry_id)

        booked_fac = conn.execute(fac_sql, fac_params).fetchone()
        if booked_fac:
            target_lbl = (
                f"Club '{booked_fac['custom_title']}'"
                if booked_fac["allocation_category"] == "CLUB_EXTRACURRICULAR"
                else f"{booked_fac['course_code']} Year {booked_fac['year_number']} Sec {booked_fac['section_code']}"
            )
            conflicts.append(
                f"Faculty {booked_fac['full_name']} is already assigned to {target_lbl} in Room {booked_fac['room_code']} at this slot."
            )

        if not is_club and section_id is not None:
            # Teacher Repeat Clause: no consecutive back-to-back lectures for same section
            adj_params: list[Any] = [section_id, day_of_week, faculty_id, slot_index - 1, slot_index + 1, *ov]
            adj_sql = f"""
                SELECT te.slot_index, f.full_name FROM timetable_entries te
                JOIN faculty f ON f.id = te.faculty_id
                WHERE te.section_id = ? AND te.day_of_week = ? AND te.faculty_id = ?
                  AND te.slot_index IN (?, ?) AND {OVERLAP_PREDICATE}
            """
            if exclude_entry_id is not None:
                adj_sql += " AND te.id != ?"
                adj_params.append(exclude_entry_id)
            adj_fac = conn.execute(adj_sql, adj_params).fetchone()
            if adj_fac:
                conflicts.append(
                    f"Teacher Repeat Clause: {adj_fac['full_name']} is already teaching this class in adjacent Slot {adj_fac['slot_index']} on {day_of_week}."
                )

        # Clause 3: Max lectures per day per teacher
        fac_row = conn.execute("SELECT full_name, max_lectures_per_day FROM faculty WHERE id = ?", (faculty_id,)).fetchone()
        wl_params: list[Any] = [faculty_id, day_of_week, *ov]
        wl_sql = f"""
            SELECT COUNT(*) FROM timetable_entries te
            WHERE te.faculty_id = ? AND te.day_of_week = ? AND {OVERLAP_PREDICATE}
        """
        if exclude_entry_id is not None:
            wl_sql += " AND te.id != ?"
            wl_params.append(exclude_entry_id)
        day_load = conn.execute(wl_sql, wl_params).fetchone()[0]
        if fac_row and day_load >= fac_row["max_lectures_per_day"]:
            conflicts.append(
                f"Workload Clause: {fac_row['full_name']} has reached their daily limit of {fac_row['max_lectures_per_day']} lectures on {day_of_week}."
            )

    return conflicts


def get_room_availability_matrix(
    conn: sqlite3.Connection,
    day_of_week: str,
    shift: str,
    slot_index: int,
    target_date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict[str, Any]]:
    rooms = conn.execute("SELECT * FROM rooms ORDER BY room_code").fetchall()
    if target_date:
        ov = _overlap_params("DATED", target_date, target_date)
    else:
        ov = _overlap_params("LIFETIME", None, None)

    if not start_time or not end_time:
        slots = compute_shift_slots(shift if shift in DEFAULT_SHIFT_CONFIG else "MORNING")
        slot_info = next((s for s in slots if s["slot_index"] == slot_index), slots[0])
        start_time = slot_info["start_time"]
        end_time = slot_info["end_time"]

    bookings = conn.execute(
        f"""
        SELECT te.room_id, te.allocation_category, te.custom_title, te.start_time, te.end_time,
               c.code AS course_code, s.year_number, s.section_code,
               sub.subject_code, sub.subject_name, f.faculty_code, te.assignment_mode,
               te.validity_type, te.effective_from, te.effective_to, te.reason
        FROM timetable_entries te
        LEFT JOIN sections s ON s.id = te.section_id
        LEFT JOIN courses c ON c.id = s.course_id
        LEFT JOIN subjects sub ON sub.id = te.subject_id
        LEFT JOIN faculty f ON f.id = te.faculty_id
        WHERE te.day_of_week = ? AND te.start_time < ? AND ? < te.end_time
          AND {OVERLAP_PREDICATE}
        """,
        (day_of_week, end_time, start_time, *ov),
    ).fetchall()
    booking_map = {b["room_id"]: dict(b) for b in bookings}

    primary_rows = conn.execute(
        """
        SELECT s.primary_room_id, c.code AS course_code, s.year_number, s.section_code
        FROM sections s
        JOIN courses c ON c.id = s.course_id
        WHERE s.shift = ? AND s.primary_room_id IS NOT NULL
        """,
        (shift,),
    ).fetchall()
    primary_map = {r["primary_room_id"]: dict(r) for r in primary_rows}

    result = []
    for r in rooms:
        item = dict(r)
        if r["status"] != "ACTIVE":
            item["availability"] = "MAINTENANCE"
            item["booking"] = None
        elif r["id"] in booking_map:
            item["availability"] = "BOOKED"
            item["booking"] = booking_map[r["id"]]
        else:
            item["availability"] = "FREE"
            item["booking"] = None
        item["primary_for"] = primary_map.get(r["id"])
        result.append(item)
    return result


def automate_timetable(
    conn: sqlite3.Connection,
    *,
    section_ids: list[int],
    weekdays: list[str],
    shift_config: dict[str, Any] | None = None,
    overwrite_auto: bool = True,
    validity_type: str = "LIFETIME",
    effective_from: str | None = None,
    effective_to: str | None = None,
) -> dict[str, Any]:
    """
    Auto-generate timetable entries with Lifetime/Dated support and all Student System clauses:
    - Respects existing MANUAL slots & non-overlapping DATED slots.
    - Enforces Teacher Qualification Lock (teacher_subjects).
    - Respects Teacher Unavailability windows (teacher_availability).
    - Enforces Teacher Max Daily Workload (max_lectures_per_day).
    - Reports overlapping Holiday/Exam events (academic_events).
    """
    if validity_type == "DATED":
        if not effective_from or not effective_to:
            raise ValueError("Dated automation requires Effective From and Effective To dates.")
        if effective_from > effective_to:
            raise ValueError("Effective From date cannot be after Effective To date.")

    ov = _overlap_params(validity_type, effective_from, effective_to)

    if overwrite_auto and section_ids:
        placeholders = ",".join("?" for _ in section_ids)
        conn.execute(
            f"""
            DELETE FROM timetable_entries
            WHERE section_id IN ({placeholders})
              AND assignment_mode = 'AUTO'
              AND (? = 'LIFETIME' OR validity_type = 'LIFETIME' OR (effective_from <= ? AND ? <= effective_to))
            """,
            (*section_ids, *ov),
        )

    rooms = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM rooms WHERE status = 'ACTIVE' AND room_type NOT IN ('AMPHITHEATER', 'AUDITORIUM') ORDER BY room_code"
        ).fetchall()
    ]

    # Qualification lookup: subject_id -> list of qualified faculty_ids
    qual_map: dict[int, list[int]] = {}
    for row in conn.execute("SELECT faculty_id, subject_id FROM teacher_subjects").fetchall():
        qual_map.setdefault(row["subject_id"], []).append(row["faculty_id"])

    fac_limits = {
        r["id"]: r["max_lectures_per_day"]
        for r in conn.execute("SELECT id, max_lectures_per_day FROM faculty").fetchall()
    }

    excluded_events = []
    if validity_type == "DATED" and effective_from and effective_to:
        excluded_events = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM academic_events WHERE start_date <= ? AND ? <= end_date",
                (effective_to, effective_from),
            ).fetchall()
        ]

    primary_reservations: dict[tuple[str, int], int] = {}
    for row in conn.execute(
        "SELECT id, shift, primary_room_id FROM sections WHERE primary_room_id IS NOT NULL"
    ).fetchall():
        primary_reservations[(row["shift"], row["primary_room_id"])] = row["id"]

    created_count = 0
    skipped_slots: list[dict[str, Any]] = []
    section_summaries: list[dict[str, Any]] = []

    # Pre-load all requested sections
    placeholders = ",".join("?" for _ in section_ids)
    all_sections = [
        dict(s)
        for s in conn.execute(
            f"""
            SELECT s.*, c.code AS course_code, c.name AS course_name
            FROM sections s JOIN courses c ON c.id = s.course_id
            WHERE s.id IN ({placeholders})
            ORDER BY s.shift, s.course_id, s.year_number, s.section_code
            """,
            tuple(section_ids),
        ).fetchall()
    ]

    # Pre-load per-section data
    sec_data: dict[int, dict[str, Any]] = {}
    for sec in all_sections:
        sid = sec["id"]
        subjects = [
            dict(sub)
            for sub in conn.execute(
                "SELECT * FROM subjects WHERE course_id = ? AND year_number = ? ORDER BY id",
                (sec["course_id"], sec["year_number"]),
            ).fetchall()
        ]
        existing_rows = conn.execute(
            f"""
            SELECT te.* FROM timetable_entries te
            WHERE te.section_id = ? AND {OVERLAP_PREDICATE}
            """,
            (sid, *ov),
        ).fetchall()

        subject_counts: dict[int, int] = {sub["id"]: 0 for sub in subjects}
        day_subjects: dict[str, dict[int, int]] = {d: {} for d in weekdays}
        day_slot_faculty: dict[tuple[str, int], int] = {}
        day_has_lab: dict[str, bool] = {d: False for d in weekdays}

        for r in existing_rows:
            if r["subject_id"] in subject_counts:
                subject_counts[r["subject_id"]] += 1
            if r["day_of_week"] in day_subjects:
                day_subjects[r["day_of_week"]][r["subject_id"]] = (
                    day_subjects[r["day_of_week"]].get(r["subject_id"], 0) + 1
                )
                if r["faculty_id"]:
                    day_slot_faculty[(r["day_of_week"], r["slot_index"])] = r["faculty_id"]

        # Check if existing entries had a lab on that day
        for r in existing_rows:
            matched_sub = next((sb for sb in subjects if sb["id"] == r["subject_id"]), None)
            if matched_sub and matched_sub["requires_lab"] and r["day_of_week"] in day_has_lab:
                day_has_lab[r["day_of_week"]] = True

        sec_data[sid] = {
            "sec": sec,
            "subjects": subjects,
            "lab_subjects": [sb for sb in subjects if sb["requires_lab"]],
            "theory_subjects": [sb for sb in subjects if not sb["requires_lab"]],
            "existing_slot_keys": {(r["day_of_week"], r["slot_index"]) for r in existing_rows},
            "subject_counts": subject_counts,
            "day_subjects": day_subjects,
            "day_slot_faculty": day_slot_faculty,
            "day_has_lab": day_has_lab,
            "sec_created": 0,
        }

    # Group sections by shift (Morning vs Afternoon run on different clock times)
    classrooms = [r for r in rooms if r["room_type"] == "CLASSROOM"]
    labs = [r for r in rooms if r["room_type"] == "COMPUTER_LAB"]

    def _is_room_busy(room_id: int, day: str, slot: dict[str, Any]) -> bool:
        return bool(
            conn.execute(
                f"""
                SELECT 1 FROM timetable_entries te
                WHERE te.room_id = ? AND te.day_of_week = ?
                  AND te.start_time < ? AND ? < te.end_time
                  AND {OVERLAP_PREDICATE}
                """,
                (room_id, day, slot["end_time"], slot["start_time"], *ov),
            ).fetchone()
        )

    def _pick_faculty(sub: dict[str, Any], sec: dict[str, Any], s_info: dict[str, Any], day: str, slot: dict[str, Any]) -> int | None:
        shift = sec["shift"]
        s_idx = slot["slot_index"]
        qualified_ids = qual_map.get(sub["id"], [])
        cand_fac_ids: list[int] = []
        if sub.get("faculty_id") and sub["faculty_id"] in qualified_ids:
            cand_fac_ids.append(sub["faculty_id"])
        for qid in qualified_ids:
            if qid not in cand_fac_ids:
                cand_fac_ids.append(qid)
        if not cand_fac_ids:
            return None

        for fid in cand_fac_ids:
            # 1. Unavailability window
            if validity_type == "DATED" and effective_from and effective_to:
                unav = conn.execute(
                    """
                    SELECT 1 FROM teacher_availability
                    WHERE faculty_id = ? AND (shift = 'ALL' OR shift = ?)
                      AND start_date <= ? AND ? <= end_date
                    """,
                    (fid, shift, effective_to, effective_from),
                ).fetchone()
            else:
                unav = conn.execute(
                    "SELECT 1 FROM teacher_availability WHERE faculty_id = ? AND (shift = 'ALL' OR shift = ?)",
                    (fid, shift),
                ).fetchone()
            if unav:
                continue

            # 2. Collision (time-interval overlap)
            fac_busy = conn.execute(
                f"""
                SELECT 1 FROM timetable_entries te
                WHERE te.faculty_id = ? AND te.day_of_week = ?
                  AND te.start_time < ? AND ? < te.end_time
                  AND {OVERLAP_PREDICATE}
                """,
                (fid, day, slot["end_time"], slot["start_time"], *ov),
            ).fetchone()
            if fac_busy:
                continue

            # 3. Teacher Repeat Clause: avoid consecutive back-to-back in same section if alternatives exist
            if (
                s_info["day_slot_faculty"].get((day, s_idx - 1)) == fid
                or s_info["day_slot_faculty"].get((day, s_idx + 1)) == fid
            ):
                if len(cand_fac_ids) > 1:
                    continue

            # 4. Check max daily workload
            day_load = conn.execute(
                f"""
                SELECT COUNT(*) FROM timetable_entries te
                WHERE te.faculty_id = ? AND te.day_of_week = ? AND {OVERLAP_PREDICATE}
                """,
                (fid, day, *ov),
            ).fetchone()[0]
            if day_load >= fac_limits.get(fid, 4):
                continue

            return fid
        return None

    def _pick_free_lab(sec: dict[str, Any], day: str, slot: dict[str, Any]) -> dict[str, Any] | None:
        for rm in labs:
            if rm["capacity"] < sec["capacity"]:
                continue
            if not _is_room_busy(rm["id"], day, slot):
                return rm
        return None

    def _pick_free_classroom(sec: dict[str, Any], day: str, slot: dict[str, Any]) -> dict[str, Any] | None:
        shift = sec["shift"]
        # Priority 1: Section's own primary classroom
        prim_id = sec.get("primary_room_id")
        if prim_id and not _is_room_busy(prim_id, day, slot):
            return next((r for r in classrooms if r["id"] == prim_id), None)

        # Priority 2: Free classroom that is NOT the primary classroom of another section in this shift
        for rm in classrooms:
            if rm["capacity"] < sec["capacity"]:
                continue
            reserved_owner = primary_reservations.get((shift, rm["id"]))
            if reserved_owner is not None and reserved_owner != sec["id"]:
                continue  # Reserved for another section's primary room
            if not _is_room_busy(rm["id"], day, slot):
                return rm

        # Priority 3: Any free classroom
        for rm in classrooms:
            if rm["capacity"] >= sec["capacity"] and not _is_room_busy(rm["id"], day, slot):
                return rm
        return None

    def _insert_entry(sec: dict[str, Any], sub: dict[str, Any], fac_id: int, rm: dict[str, Any], day: str, slot: dict[str, Any], is_lab: bool = False, is_primary: bool = False):
        val_label = "Lifetime" if validity_type == "LIFETIME" else f"{effective_from}..{effective_to}"
        if is_lab:
            room_label = f"Computer Lab {rm['room_code']}"
        elif is_primary:
            room_label = f"Primary Room {rm['room_code']}"
        else:
            room_label = f"Classroom {rm['room_code']}"
        reason = f"Auto-allotted [{val_label}] ({room_label})"

        conn.execute(
            """
            INSERT INTO timetable_entries (
                section_id, day_of_week, shift, slot_index,
                start_time, end_time, subject_id, faculty_id, room_id,
                assignment_mode, validity_type, effective_from, effective_to, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'AUTO', ?, ?, ?, ?)
            """,
            (
                sec["id"],
                day,
                sec["shift"],
                slot["slot_index"],
                slot["start_time"],
                slot["end_time"],
                sub["id"],
                fac_id,
                rm["id"],
                validity_type,
                effective_from if validity_type == "DATED" else None,
                effective_to if validity_type == "DATED" else None,
                reason,
            ),
        )

    # Process each shift cohesively slot-by-slot
    for shift in ("MORNING", "AFTERNOON"):
        shift_secs = [s for s in all_sections if s["shift"] == shift]
        if not shift_secs:
            continue
        slots = compute_shift_slots(shift, shift_config)

        for day in weekdays:
            for slot in slots:
                s_idx = slot["slot_index"]

                # Find sections in this shift needing a class in this slot
                unfilled_secs = [
                    s for s in shift_secs
                    if (day, s_idx) not in sec_data[s["id"]]["existing_slot_keys"]
                ]
                if not unfilled_secs:
                    continue

                # --- PHASE 1: COHESIVE COMPUTER LAB ALLOCATION ---
                # Rotate available computer labs (G04, 104, 107) across sections needing labs
                lab_candidates = []
                for s in unfilled_secs:
                    s_info = sec_data[s["id"]]
                    needed_labs = [
                        sub for sub in s_info["lab_subjects"]
                        if s_info["subject_counts"].get(sub["id"], 0) < sub["lectures_per_week"]
                        and s_info["day_subjects"][day].get(sub["id"], 0) < 1
                    ]
                    if needed_labs and not s_info["day_has_lab"].get(day, False):
                        deficit = sum(sub["lectures_per_week"] - s_info["subject_counts"].get(sub["id"], 0) for sub in needed_labs)
                        lab_candidates.append((deficit, s, needed_labs))

                # Prioritize section with highest remaining lab deficit
                lab_candidates.sort(key=lambda x: x[0], reverse=True)

                assigned_in_slot: set[int] = set()

                for deficit, s, needed_labs in lab_candidates:
                    s_info = sec_data[s["id"]]
                    needed_labs.sort(key=lambda sb: (s_info["subject_counts"].get(sb["id"], 0) - sb["lectures_per_week"], s_info["subject_counts"].get(sb["id"], 0)))

                    for sub in needed_labs:
                        fac_id = _pick_faculty(sub, s, s_info, day, slot)
                        if fac_id is None:
                            continue
                        lab_rm = _pick_free_lab(s, day, slot)
                        if lab_rm is None:
                            continue

                        _insert_entry(s, sub, fac_id, lab_rm, day, slot, is_lab=True)
                        s_info["subject_counts"][sub["id"]] = s_info["subject_counts"].get(sub["id"], 0) + 1
                        s_info["day_subjects"][day][sub["id"]] = s_info["day_subjects"][day].get(sub["id"], 0) + 1
                        s_info["day_slot_faculty"][(day, s_idx)] = fac_id
                        s_info["existing_slot_keys"].add((day, s_idx))
                        s_info["day_has_lab"][day] = True
                        s_info["sec_created"] += 1
                        created_count += 1
                        assigned_in_slot.add(s["id"])
                        break

                # --- PHASE 2: THEORY ALLOCATION IN PRIMARY CLASSROOMS ---
                # All remaining sections take theory lectures in their primary classrooms
                theory_secs = [s for s in unfilled_secs if s["id"] not in assigned_in_slot]
                for s in theory_secs:
                    s_info = sec_data[s["id"]]
                    theory_subs = [
                        sub for sub in s_info["theory_subjects"]
                        if s_info["day_subjects"][day].get(sub["id"], 0) < 2
                    ]
                    if not theory_subs:
                        continue

                    theory_subs.sort(
                        key=lambda sb: (
                            s_info["day_subjects"][day].get(sb["id"], 0),
                            s_info["subject_counts"].get(sb["id"], 0) - sb["lectures_per_week"],
                            s_info["subject_counts"].get(sb["id"], 0),
                        )
                    )

                    placed_theory = False
                    for sub in theory_subs:
                        fac_id = _pick_faculty(sub, s, s_info, day, slot)
                        if fac_id is None:
                            continue
                        theory_rm = _pick_free_classroom(s, day, slot)
                        if theory_rm is None:
                            continue

                        is_prim = (theory_rm["id"] == s.get("primary_room_id"))
                        _insert_entry(s, sub, fac_id, theory_rm, day, slot, is_lab=False, is_primary=is_prim)
                        s_info["subject_counts"][sub["id"]] = s_info["subject_counts"].get(sub["id"], 0) + 1
                        s_info["day_subjects"][day][sub["id"]] = s_info["day_subjects"][day].get(sub["id"], 0) + 1
                        s_info["day_slot_faculty"][(day, s_idx)] = fac_id
                        s_info["existing_slot_keys"].add((day, s_idx))
                        s_info["sec_created"] += 1
                        created_count += 1
                        placed_theory = True
                        break

                    if not placed_theory:
                        skipped_slots.append(
                            {
                                "section": f"{s['course_code']} Y{s['year_number']} {s['section_code']}",
                                "day": day,
                                "slot_index": s_idx,
                                "reason": "No conflict-free classroom or qualified available teacher combination.",
                            }
                        )

    for s in all_sections:
        s_info = sec_data[s["id"]]
        summary_item: dict[str, Any] = {
            "section_id": s["id"],
            "label": f"{s['course_code']} Y{s['year_number']} {s['section_code']}",
            "created": s_info["sec_created"],
        }
        if not s_info["subjects"]:
            summary_item["warning"] = "No subjects configured for this course/year."
        section_summaries.append(summary_item)

    conn.commit()
    return {
        "created_count": created_count,
        "validity_type": validity_type,
        "effective_from": effective_from if validity_type == "DATED" else None,
        "effective_to": effective_to if validity_type == "DATED" else None,
        "sections": section_summaries,
        "skipped_slots": skipped_slots,
        "excluded_events": excluded_events,
    }


def reallocate_entry(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any]:
    """
    Clause 5 (Student System PRD FR-6 & FR-7):
    Dynamic Reallocation without generic substitutes:
    1. Try finding another free compatible room for the same subject & teacher.
    2. Otherwise, find another subject in the section's curriculum taught by a
       FREE & QUALIFIED teacher in their own subject + a free compatible room.
    """
    entry = conn.execute(
        """
        SELECT te.*, s.course_id, s.year_number, s.capacity AS sec_capacity,
               sub.requires_lab, sub.subject_name
        FROM timetable_entries te
        JOIN sections s ON s.id = te.section_id
        JOIN subjects sub ON sub.id = te.subject_id
        WHERE te.id = ?
        """,
        (entry_id,),
    ).fetchone()
    if not entry:
        return {"ok": False, "error": "Timetable entry not found."}

    ov = _overlap_params(entry["validity_type"], entry["effective_from"], entry["effective_to"])
    rooms = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM rooms WHERE status = 'ACTIVE' AND room_type NOT IN ('AMPHITHEATER', 'AUDITORIUM') ORDER BY room_code"
        ).fetchall()
    ]
    booked_rooms = {
        r["room_id"]
        for r in conn.execute(
            f"""
            SELECT te.room_id FROM timetable_entries te
            WHERE te.day_of_week = ? AND te.shift = ? AND te.slot_index = ? AND te.id != ?
              AND {OVERLAP_PREDICATE}
            """,
            (entry["day_of_week"], entry["shift"], entry["slot_index"], entry_id, *ov),
        ).fetchall()
    }

    # Option 1: Keep subject/teacher if teacher is available & move to another free room
    if entry["faculty_id"]:
        conflicts = check_slot_conflict(
            conn,
            section_id=entry["section_id"],
            day_of_week=entry["day_of_week"],
            shift=entry["shift"],
            slot_index=entry["slot_index"],
            room_id=entry["room_id"],
            faculty_id=entry["faculty_id"],
            subject_id=entry["subject_id"],
            validity_type=entry["validity_type"],
            effective_from=entry["effective_from"],
            effective_to=entry["effective_to"],
            exclude_entry_id=entry_id,
        )
        # If only room was the issue (e.g. maintenance), swap room
        if not any("Availability Clause" in c or "Qualification Clause" in c or "already teaching" in c for c in conflicts):
            for rm in rooms:
                if rm["id"] != entry["room_id"] and rm["id"] not in booked_rooms and rm["capacity"] >= entry["sec_capacity"]:
                    if (entry["requires_lab"] and rm["room_type"] == "COMPUTER_LAB") or (
                        not entry["requires_lab"] and rm["room_type"] != "COMPUTER_LAB"
                    ):
                        conn.execute(
                            "UPDATE timetable_entries SET room_id = ?, reason = ? WHERE id = ?",
                            (rm["id"], f"Reallocated room to {rm['room_code']} (No generic substitute)", entry_id),
                        )
                        conn.commit()
                        return {"ok": True, "action": "ROOM_SWAPPED", "message": f"Reallocated to Room {rm['room_code']}."}

    # Option 2: Find another qualified subject+teacher for this section (PRD FR-6: own subject only)
    alt_subjects = conn.execute(
        """
        SELECT sub.*, ts.faculty_id AS qual_faculty_id, f.faculty_code, f.full_name
        FROM subjects sub
        JOIN teacher_subjects ts ON ts.subject_id = sub.id
        JOIN faculty f ON f.id = ts.faculty_id
        WHERE sub.course_id = ? AND sub.year_number = ? AND sub.id != ?
        """,
        (entry["course_id"], entry["year_number"], entry["subject_id"]),
    ).fetchall()

    for alt in alt_subjects:
        for rm in rooms:
            if rm["id"] in booked_rooms or rm["capacity"] < entry["sec_capacity"]:
                continue
            if alt["requires_lab"] and rm["room_type"] != "COMPUTER_LAB":
                continue
            if not alt["requires_lab"] and rm["room_type"] == "COMPUTER_LAB":
                continue
            c_list = check_slot_conflict(
                conn,
                section_id=entry["section_id"],
                day_of_week=entry["day_of_week"],
                shift=entry["shift"],
                slot_index=entry["slot_index"],
                room_id=rm["id"],
                faculty_id=alt["qual_faculty_id"],
                subject_id=alt["id"],
                validity_type=entry["validity_type"],
                effective_from=entry["effective_from"],
                effective_to=entry["effective_to"],
                exclude_entry_id=entry_id,
            )
            if not c_list:
                conn.execute(
                    """
                    UPDATE timetable_entries
                    SET subject_id = ?, faculty_id = ?, room_id = ?, reason = ?
                    WHERE id = ?
                    """,
                    (
                        alt["id"],
                        alt["qual_faculty_id"],
                        rm["id"],
                        f"Dynamic Reallocation: {alt['subject_code']} by {alt['faculty_code']} in {rm['room_code']} (Qualified subject)",
                        entry_id,
                    ),
                )
                conn.commit()
                return {
                    "ok": True,
                    "action": "LECTURE_REALLOCATED",
                    "message": f"Reallocated to {alt['subject_name']} with {alt['full_name']} in Room {rm['room_code']}.",
                }

    return {"ok": False, "error": "No valid conflict-free qualified teacher/room candidate found for reallocation."}
