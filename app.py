from __future__ import annotations

import datetime as dt
import os
import sqlite3
from flask import Flask, jsonify, render_template, request

from db import get_connection, init_db
from scheduler import (
    DEFAULT_SHIFT_CONFIG,
    WEEKDAYS,
    automate_timetable,
    check_slot_conflict,
    compute_shift_slots,
    get_room_availability_matrix,
    reallocate_entry,
)

app = Flask(__name__)

# Optional API Key Authentication for Microservice / External ERP Integration
ERP_API_KEY = os.environ.get("ERP_API_KEY", "").strip()


@app.before_request
def handle_options_preflight():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        return response


@app.before_request
def verify_api_auth():
    """Enforce optional API key if ERP_API_KEY environment variable is configured."""
    if not ERP_API_KEY:
        return
    # Skip UI and static files
    if request.path == "/" or request.path.startswith("/static") or request.path == "/api/v1/health":
        return
    if request.method == "OPTIONS":
        return

    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif api_key_header:
        token = api_key_header.strip()

    if token != ERP_API_KEY:
        return jsonify({
            "error": "Unauthorized: Invalid or missing ERP API key.",
            "hint": "Provide header 'X-API-Key: <key>' or 'Authorization: Bearer <key>'."
        }), 401


@app.after_request
def add_cors_headers(response):
    """Enable Cross-Origin Resource Sharing (CORS) for external ERP frontend/backend integration."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key, X-ERP-Secret"
    return response


@app.route("/api/v1/health", methods=["GET"])
def health_check():
    """Health & Readiness probe for external ERP integration."""
    db_status = "connected"
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as exc:
        db_status = f"error: {exc}"

    return jsonify(
        {
            "status": "healthy" if db_status == "connected" else "degraded",
            "module": "Automated Timetable & Venue Allotment Engine",
            "version": "1.2.0",
            "database": db_status,
            "auth_configured": bool(ERP_API_KEY),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/v1/bootstrap", methods=["GET"])
def bootstrap():
    conn = get_connection()
    try:
        courses = [dict(r) for r in conn.execute("SELECT * FROM courses ORDER BY id").fetchall()]
        sections = [
            dict(r)
            for r in conn.execute(
                """
                SELECT s.*, c.code AS course_code, c.name AS course_name,
                       r.room_code AS primary_room_code
                FROM sections s
                JOIN courses c ON c.id = s.course_id
                LEFT JOIN rooms r ON r.id = s.primary_room_id
                ORDER BY c.id, s.year_number, s.shift DESC, s.section_code
                """
            ).fetchall()
        ]
        rooms = [dict(r) for r in conn.execute("SELECT * FROM rooms ORDER BY room_code").fetchall()]
        faculty = [dict(r) for r in conn.execute("SELECT * FROM faculty ORDER BY full_name").fetchall()]
        subjects = [
            dict(r)
            for r in conn.execute(
                """
                SELECT sub.*, c.code AS course_code, f.faculty_code, f.full_name AS faculty_name
                FROM subjects sub
                JOIN courses c ON c.id = sub.course_id
                LEFT JOIN faculty f ON f.id = sub.faculty_id
                ORDER BY c.id, sub.year_number, sub.subject_code
                """
            ).fetchall()
        ]
        teacher_subjects = [
            dict(r)
            for r in conn.execute(
                """
                SELECT ts.*, f.faculty_code, f.full_name AS faculty_name,
                       sub.subject_code, sub.subject_name, c.code AS course_code, sub.year_number
                FROM teacher_subjects ts
                JOIN faculty f ON f.id = ts.faculty_id
                JOIN subjects sub ON sub.id = ts.subject_id
                JOIN courses c ON c.id = sub.course_id
                ORDER BY f.full_name, c.code, sub.year_number
                """
            ).fetchall()
        ]
        teacher_availability = [
            dict(r)
            for r in conn.execute(
                """
                SELECT ta.*, f.faculty_code, f.full_name AS faculty_name
                FROM teacher_availability ta
                JOIN faculty f ON f.id = ta.faculty_id
                ORDER BY ta.start_date DESC
                """
            ).fetchall()
        ]
        academic_events = [
            dict(r)
            for r in conn.execute("SELECT * FROM academic_events ORDER BY start_date").fetchall()
        ]
        return jsonify(
            {
                "courses": courses,
                "sections": sections,
                "rooms": rooms,
                "faculty": faculty,
                "subjects": subjects,
                "teacher_subjects": teacher_subjects,
                "teacher_availability": teacher_availability,
                "academic_events": academic_events,
                "weekdays": WEEKDAYS,
                "shift_config": DEFAULT_SHIFT_CONFIG,
                "slots": {
                    "MORNING": compute_shift_slots("MORNING"),
                    "AFTERNOON": compute_shift_slots("AFTERNOON"),
                },
            }
        )
    finally:
        conn.close()


@app.route("/api/v1/sections/<int:section_id>/primary-room", methods=["POST"])
def set_primary_room(section_id: int):
    data = request.get_json(force=True) or {}
    room_id = data.get("room_id")
    conn = get_connection()
    try:
        sec = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
        if not sec:
            return jsonify({"error": "Section not found"}), 404
        if room_id is not None and room_id != "":
            room = conn.execute("SELECT * FROM rooms WHERE id = ?", (int(room_id),)).fetchone()
            if not room:
                return jsonify({"error": "Room not found"}), 404
            conn.execute(
                "UPDATE sections SET primary_room_id = ? WHERE id = ?",
                (int(room_id), section_id),
            )
        else:
            conn.execute("UPDATE sections SET primary_room_id = NULL WHERE id = ?", (section_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/timetable", methods=["GET"])
def get_timetable():
    section_id = request.args.get("section_id", type=int)
    conn = get_connection()
    try:
        sql = """
            SELECT te.*, c.code AS course_code, s.year_number, s.section_code,
                   sub.subject_code, sub.subject_name, sub.requires_lab,
                   f.faculty_code, f.full_name AS faculty_name,
                   r.room_code, r.building, r.floor, r.room_type
            FROM timetable_entries te
            LEFT JOIN sections s ON s.id = te.section_id
            LEFT JOIN courses c ON c.id = s.course_id
            LEFT JOIN subjects sub ON sub.id = te.subject_id
            LEFT JOIN faculty f ON f.id = te.faculty_id
            JOIN rooms r ON r.id = te.room_id
        """
        params = []
        if section_id:
            sql += " WHERE te.section_id = ?"
            params.append(section_id)
        sql += " ORDER BY te.allocation_category, c.id, s.year_number, te.shift DESC, s.section_code, te.day_of_week, te.slot_index"
        entries = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return jsonify({"entries": entries})
    finally:
        conn.close()


def _resolve_identifiers(conn: sqlite3.Connection, data: dict, is_club: bool):
    """Enable external ERP callers to supply either numeric IDs or natural codes."""
    room_id = data.get("room_id")
    if not room_id and data.get("room_code"):
        rm = conn.execute(
            "SELECT id FROM rooms WHERE UPPER(room_code) = UPPER(?)",
            (str(data["room_code"]).strip(),),
        ).fetchone()
        if rm:
            room_id = rm["id"]

    faculty_id = data.get("faculty_id")
    if not faculty_id and data.get("faculty_code"):
        fac = conn.execute(
            "SELECT id FROM faculty WHERE UPPER(faculty_code) = UPPER(?)",
            (str(data["faculty_code"]).strip(),),
        ).fetchone()
        if fac:
            faculty_id = fac["id"]

    section_id = data.get("section_id")
    subject_id = data.get("subject_id")

    if not is_club:
        if not section_id and data.get("course_code"):
            c_code = str(data["course_code"]).strip().upper()
            yr = int(data.get("year_number", 1))
            sh = str(data.get("shift", "MORNING")).strip().upper()
            sec_code = str(data.get("section_code", "Grade-Wise" if c_code == "BCA" else "M1")).strip()
            sec = conn.execute(
                """
                SELECT s.id FROM sections s
                JOIN courses c ON c.id = s.course_id
                WHERE UPPER(c.code) = ? AND s.year_number = ? AND UPPER(s.shift) = ? AND UPPER(s.section_code) = ?
                """,
                (c_code, yr, sh, sec_code.upper()),
            ).fetchone()
            if sec:
                section_id = sec["id"]

        if not subject_id and data.get("subject_code"):
            sub_params = [str(data["subject_code"]).strip()]
            sub_sql = "SELECT id FROM subjects WHERE UPPER(subject_code) = UPPER(?)"
            if section_id:
                sub_sql += " AND (course_id, year_number) IN (SELECT course_id, year_number FROM sections WHERE id = ?)"
                sub_params.append(section_id)
            sub = conn.execute(sub_sql, sub_params).fetchone()
            if sub:
                subject_id = sub["id"]

    return (
        int(room_id) if room_id is not None else None,
        int(faculty_id) if faculty_id is not None else None,
        int(section_id) if section_id is not None else None,
        int(subject_id) if subject_id is not None else None,
    )


@app.route("/api/v1/timetable/manual", methods=["POST"])
def manual_allot():
    data = request.get_json(force=True) or {}
    allocation_category = (data.get("allocation_category") or "COURSE").upper()
    if allocation_category not in ("COURSE", "CLUB_EXTRACURRICULAR"):
        return jsonify({"error": "Invalid allocation_category."}), 400

    is_club = allocation_category == "CLUB_EXTRACURRICULAR"
    conn = get_connection()
    try:
        # Auto-resolve natural external codes (room_code, course_code, etc.) if IDs were not sent
        res_room_id, res_fac_id, res_sec_id, res_sub_id = _resolve_identifiers(conn, data, is_club)
        if res_room_id:
            data["room_id"] = res_room_id
        if res_fac_id:
            data["faculty_id"] = res_fac_id
        if res_sec_id:
            data["section_id"] = res_sec_id
        if res_sub_id:
            data["subject_id"] = res_sub_id

        required = ["day_of_week", "room_id"] + (
            ["start_time", "end_time"] if is_club else ["section_id", "subject_id", "slot_index"]
        )
        for key in required:
            if not data.get(key):
                return jsonify({"error": f"Missing required field: {key}"}), 400

        section_id = None if is_club else int(data["section_id"])
        subject_id = None if is_club else int(data["subject_id"])
        day_of_week = str(data["day_of_week"])
        slot_index = 0 if is_club else int(data["slot_index"])
        room_id = int(data["room_id"])
        faculty_id = int(data["faculty_id"]) if data.get("faculty_id") else None
        validity_type = (data.get("validity_type") or "LIFETIME").upper()
        effective_from = data.get("effective_from") or None
        effective_to = data.get("effective_to") or effective_from
        reason = (data.get("reason") or "").strip()
        custom_title = (data.get("custom_title") or reason).strip() if is_club else ""

        if validity_type not in ("LIFETIME", "DATED"):
            return jsonify({"error": "Invalid validity_type. Must be LIFETIME or DATED."}), 400
        if not reason:
            return jsonify({"error": "Please provide a society name or reason for allotment."}), 400

        if is_club:
            start_time = str(data["start_time"])
            end_time = str(data["end_time"])
            shift = "MORNING" if start_time < "13:00" else "AFTERNOON"
        else:
            sec = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
            if not sec:
                return jsonify({"error": "Section not found."}), 404
            shift = sec["shift"]
            slots = compute_shift_slots(shift)
            slot_info = next((s for s in slots if s["slot_index"] == slot_index), None)
            if not slot_info:
                return jsonify({"error": "Invalid slot index."}), 400
            start_time = slot_info["start_time"]
            end_time = slot_info["end_time"]

        conflicts = check_slot_conflict(
            conn,
            section_id=section_id,
            day_of_week=day_of_week,
            shift=shift,
            slot_index=slot_index,
            room_id=room_id,
            faculty_id=faculty_id,
            subject_id=subject_id,
            start_time=start_time,
            end_time=end_time,
            allocation_category=allocation_category,
            validity_type=validity_type,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        if conflicts:
            return jsonify({"error": conflicts[0], "conflicts": conflicts}), 409

        cur = conn.execute(
            """
            INSERT INTO timetable_entries (
                allocation_category, section_id, day_of_week, shift, slot_index,
                start_time, end_time, subject_id, faculty_id, room_id, custom_title,
                assignment_mode, validity_type, effective_from, effective_to, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL', ?, ?, ?, ?)
            """,
            (
                allocation_category,
                section_id,
                day_of_week,
                shift,
                slot_index,
                start_time,
                end_time,
                subject_id,
                faculty_id,
                room_id,
                custom_title,
                validity_type,
                effective_from if validity_type == "DATED" else None,
                effective_to if validity_type == "DATED" else None,
                reason,
            ),
        )
        conn.commit()
        return jsonify({
            "ok": True,
            "message": "Slot allotted successfully.",
            "entry_id": cur.lastrowid
        }), 201
    finally:
        conn.close()


@app.route("/api/v1/timetable/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id: int):
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM timetable_entries WHERE id = ?", (entry_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Entry not found"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/timetable/<int:entry_id>/reallocate", methods=["POST"])
def reallocate_slot(entry_id: int):
    conn = get_connection()
    try:
        res = reallocate_entry(conn, entry_id)
        if not res["ok"]:
            return jsonify({"error": res["error"]}), 409
        return jsonify(res)
    finally:
        conn.close()


@app.route("/api/v1/timetable/clear", methods=["POST"])
def clear_timetable():
    data = request.get_json(force=True) or {}
    section_id = data.get("section_id")
    section_ids = [int(x) for x in (data.get("section_ids") or [])]
    mode = (data.get("mode") or "ALL").upper()
    conn = get_connection()
    try:
        if section_ids:
            placeholders = ",".join("?" for _ in section_ids)
            if mode == "AUTO":
                cur = conn.execute(
                    f"DELETE FROM timetable_entries WHERE section_id IN ({placeholders}) AND assignment_mode = 'AUTO'",
                    tuple(section_ids),
                )
            else:
                cur = conn.execute(
                    f"DELETE FROM timetable_entries WHERE section_id IN ({placeholders})",
                    tuple(section_ids),
                )
        elif section_id:
            if mode == "AUTO":
                cur = conn.execute(
                    "DELETE FROM timetable_entries WHERE section_id = ? AND assignment_mode = 'AUTO'",
                    (int(section_id),),
                )
            else:
                cur = conn.execute("DELETE FROM timetable_entries WHERE section_id = ?", (int(section_id),))
        else:
            if mode == "AUTO":
                cur = conn.execute("DELETE FROM timetable_entries WHERE assignment_mode = 'AUTO'")
            else:
                cur = conn.execute("DELETE FROM timetable_entries")
        conn.commit()
        return jsonify({"ok": True, "deleted_count": cur.rowcount})
    finally:
        conn.close()


@app.route("/api/v1/timetable/automate", methods=["POST"])
def run_automation():
    data = request.get_json(force=True) or {}
    section_ids = [int(x) for x in (data.get("section_ids") or [])]
    conn = get_connection()
    try:
        # Auto-resolve course_code and year if section_ids not provided
        if not section_ids and data.get("course_code"):
            c_code = str(data["course_code"]).strip().upper()
            yr = data.get("year_number")
            sh = data.get("shift")
            sql = "SELECT s.id FROM sections s JOIN courses c ON c.id = s.course_id WHERE UPPER(c.code) = ?"
            params: list[Any] = [c_code]
            if yr is not None:
                sql += " AND s.year_number = ?"
                params.append(int(yr))
            if sh is not None:
                sql += " AND UPPER(s.shift) = UPPER(?)"
                params.append(str(sh).strip())
            rows = conn.execute(sql, params).fetchall()
            section_ids = [r["id"] for r in rows]

        if not section_ids:
            return jsonify({"error": "Select or provide at least one section/course to automate."}), 400

        weekdays = data.get("weekdays") or WEEKDAYS[:5]
        shift_config = data.get("shift_config")
        overwrite_auto = bool(data.get("overwrite_auto", True))
        validity_type = (data.get("validity_type") or "LIFETIME").upper()
        effective_from = data.get("effective_from") or None
        effective_to = data.get("effective_to") or effective_from

        result = automate_timetable(
            conn,
            section_ids=section_ids,
            weekdays=weekdays,
            shift_config=shift_config,
            overwrite_auto=overwrite_auto,
            validity_type=validity_type,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/v1/rooms/availability", methods=["GET"])
def room_availability():
    day_of_week = request.args.get("day", "Monday")
    shift = request.args.get("shift", "MORNING")
    slot_index = request.args.get("slot_index", 1, type=int)
    target_date = request.args.get("target_date") or None
    start_time = request.args.get("start_time") or None
    end_time = request.args.get("end_time") or None
    conn = get_connection()
    try:
        matrix = get_room_availability_matrix(
            conn,
            day_of_week,
            shift,
            slot_index,
            target_date=target_date,
            start_time=start_time,
            end_time=end_time,
        )
        return jsonify({"rooms": matrix})
    finally:
        conn.close()


@app.route("/api/v1/rooms", methods=["POST"])
def create_room():
    data = request.get_json(force=True) or {}
    room_code = (data.get("room_code") or "").strip().upper()
    building = (data.get("building") or "Main Block").strip()
    floor = (data.get("floor") or "Ground Floor").strip()
    room_type = data.get("room_type") or "CLASSROOM"
    capacity = int(data.get("capacity") or 60)
    if not room_code:
        return jsonify({"error": "Room code is required."}), 400

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO rooms (room_code, building, floor, room_type, capacity, status)
            VALUES (?, ?, ?, ?, ?, 'ACTIVE')
            """,
            (room_code, building, floor, room_type, capacity),
        )
        conn.commit()
        return jsonify({"ok": True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Room '{room_code}' already exists."}), 409
    finally:
        conn.close()


@app.route("/api/v1/rooms/<int:room_id>", methods=["PATCH", "DELETE"])
def modify_room(room_id: int):
    conn = get_connection()
    try:
        if request.method == "DELETE":
            conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
            conn.commit()
            return jsonify({"ok": True})

        data = request.get_json(force=True) or {}
        if "status" in data:
            conn.execute("UPDATE rooms SET status = ? WHERE id = ?", (data["status"], room_id))
        if "capacity" in data:
            conn.execute("UPDATE rooms SET capacity = ? WHERE id = ?", (int(data["capacity"]), room_id))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/subjects", methods=["POST"])
def create_subject():
    data = request.get_json(force=True) or {}
    course_id = int(data["course_id"])
    year_number = int(data["year_number"])
    subject_code = (data.get("subject_code") or "").strip().upper()
    subject_name = (data.get("subject_name") or "").strip()
    requires_lab = 1 if data.get("requires_lab") else 0
    lectures_per_week = int(data.get("lectures_per_week") or 4)
    faculty_id = int(data["faculty_id"]) if data.get("faculty_id") else None

    if not subject_code or not subject_name:
        return jsonify({"error": "Subject code and name are required."}), 400

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO subjects (
                course_id, year_number, subject_code, subject_name,
                requires_lab, lectures_per_week, faculty_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (course_id, year_number, subject_code, subject_name, requires_lab, lectures_per_week, faculty_id),
        )
        if faculty_id:
            conn.execute(
                "INSERT OR IGNORE INTO teacher_subjects (faculty_id, subject_id) VALUES (?, ?)",
                (faculty_id, cur.lastrowid),
            )
        conn.commit()
        return jsonify({"ok": True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Subject '{subject_code}' already exists for this course & year."}), 409
    finally:
        conn.close()


@app.route("/api/v1/subjects/<int:subject_id>", methods=["DELETE"])
def delete_subject(subject_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/faculty", methods=["POST"])
def create_faculty():
    data = request.get_json(force=True) or {}
    code = (data.get("faculty_code") or "").strip().upper()
    name = (data.get("full_name") or "").strip()
    dept = (data.get("department") or "General").strip()
    max_lpd = int(data.get("max_lectures_per_day") or 4)
    if not code or not name:
        return jsonify({"error": "Faculty code and full name are required."}), 400

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO faculty (faculty_code, full_name, department, max_lectures_per_day) VALUES (?, ?, ?, ?)",
            (code, name, dept, max_lpd),
        )
        conn.commit()
        return jsonify({"ok": True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Faculty '{code}' already exists."}), 409
    finally:
        conn.close()


@app.route("/api/v1/teacher-subjects", methods=["POST"])
def add_teacher_qualification():
    data = request.get_json(force=True) or {}
    faculty_id = int(data["faculty_id"])
    subject_id = int(data["subject_id"])
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO teacher_subjects (faculty_id, subject_id) VALUES (?, ?)",
            (faculty_id, subject_id),
        )
        conn.commit()
        return jsonify({"ok": True}), 201
    finally:
        conn.close()


@app.route("/api/v1/teacher-subjects/<int:qual_id>", methods=["DELETE"])
def delete_teacher_qualification(qual_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM teacher_subjects WHERE id = ?", (qual_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/teacher-availability", methods=["POST"])
def add_teacher_unavailability():
    data = request.get_json(force=True) or {}
    faculty_id = int(data["faculty_id"])
    start_date = data.get("start_date")
    end_date = data.get("end_date") or start_date
    shift = data.get("shift") or "ALL"
    reason = (data.get("reason") or "").strip()
    if not start_date or not end_date or start_date > end_date:
        return jsonify({"error": "Valid start_date and end_date are required."}), 400

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO teacher_availability (faculty_id, start_date, end_date, shift, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (faculty_id, start_date, end_date, shift, reason),
        )
        conn.commit()
        return jsonify({"ok": True}), 201
    finally:
        conn.close()


@app.route("/api/v1/teacher-availability/<int:avail_id>", methods=["DELETE"])
def delete_teacher_unavailability(avail_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM teacher_availability WHERE id = ?", (avail_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/academic-events", methods=["POST"])
def add_academic_event():
    data = request.get_json(force=True) or {}
    event_type = (data.get("event_type") or "HOLIDAY").upper()
    title = (data.get("title") or "").strip()
    start_date = data.get("start_date")
    end_date = data.get("end_date") or start_date
    if not title or not start_date or not end_date or start_date > end_date:
        return jsonify({"error": "Event title and valid date range are required."}), 400

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO academic_events (event_type, title, start_date, end_date) VALUES (?, ?, ?, ?)",
            (event_type, title, start_date, end_date),
        )
        conn.commit()
        return jsonify({"ok": True}), 201
    finally:
        conn.close()


@app.route("/api/v1/academic-events/<int:event_id>", methods=["DELETE"])
def delete_academic_event(event_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM academic_events WHERE id = ?", (event_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/v1/students", methods=["GET"])
def list_students():
    section_id = request.args.get("section_id", type=int)
    q = (request.args.get("q") or "").strip()
    conn = get_connection()
    try:
        sql = """
            SELECT st.*, c.code AS course_code, s.year_number, s.shift, s.section_code
            FROM students st
            JOIN sections s ON s.id = st.section_id
            JOIN courses c ON c.id = s.course_id
            WHERE 1=1
        """
        params = []
        if section_id:
            sql += " AND st.section_id = ?"
            params.append(section_id)
        if q:
            sql += " AND (UPPER(st.erp_id) LIKE UPPER(?) OR UPPER(st.full_name) LIKE UPPER(?))"
            params.extend([f"%{q}%", f"%{q}%"])
        sql += " ORDER BY st.section_id, st.roll_no LIMIT 100"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return jsonify({"students": rows})
    finally:
        conn.close()


@app.route("/api/v1/portal/teacher/<int:faculty_id>", methods=["GET"])
def teacher_portal(faculty_id: int):
    conn = get_connection()
    try:
        fac = conn.execute("SELECT * FROM faculty WHERE id = ?", (faculty_id,)).fetchone()
        if not fac:
            return jsonify({"error": "Faculty not found"}), 404

        entries = [
            dict(r)
            for r in conn.execute(
                """
                SELECT te.*, c.code AS course_code, s.year_number, s.section_code,
                       sub.subject_code, sub.subject_name, r.room_code, r.building, r.floor
                FROM timetable_entries te
                LEFT JOIN sections s ON s.id = te.section_id
                LEFT JOIN courses c ON c.id = s.course_id
                LEFT JOIN subjects sub ON sub.id = te.subject_id
                JOIN rooms r ON r.id = te.room_id
                WHERE te.faculty_id = ?
                ORDER BY te.day_of_week, te.slot_index
                """,
                (faculty_id,),
            ).fetchall()
        ]
        qualifications = [
            dict(r)
            for r in conn.execute(
                """
                SELECT sub.subject_code, sub.subject_name, c.code AS course_code, sub.year_number
                FROM teacher_subjects ts
                JOIN subjects sub ON sub.id = ts.subject_id
                JOIN courses c ON c.id = sub.course_id
                WHERE ts.faculty_id = ?
                ORDER BY c.code, sub.year_number
                """,
                (faculty_id,),
            ).fetchall()
        ]
        unavailability = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM teacher_availability WHERE faculty_id = ? ORDER BY start_date DESC",
                (faculty_id,),
            ).fetchall()
        ]
        return jsonify(
            {
                "faculty": dict(fac),
                "entries": entries,
                "qualifications": qualifications,
                "unavailability": unavailability,
            }
        )
    finally:
        conn.close()


@app.route("/api/v1/portal/student/<int:student_id>", methods=["GET"])
def student_portal(student_id: int):
    conn = get_connection()
    try:
        st = conn.execute(
            """
            SELECT st.*, c.code AS course_code, c.name AS course_name,
                   s.year_number, s.shift, s.section_code, r.room_code AS primary_room_code
            FROM students st
            JOIN sections s ON s.id = st.section_id
            JOIN courses c ON c.id = s.course_id
            LEFT JOIN rooms r ON r.id = s.primary_room_id
            WHERE st.id = ?
            """,
            (student_id,),
        ).fetchone()
        if not st:
            return jsonify({"error": "Student not found"}), 404

        entries = [
            dict(r)
            for r in conn.execute(
                """
                SELECT te.*, sub.subject_code, sub.subject_name, sub.requires_lab,
                       f.faculty_code, f.full_name AS faculty_name,
                       r.room_code, r.building, r.floor
                FROM timetable_entries te
                JOIN subjects sub ON sub.id = te.subject_id
                LEFT JOIN faculty f ON f.id = te.faculty_id
                JOIN rooms r ON r.id = te.room_id
                WHERE te.section_id = ?
                ORDER BY te.day_of_week, te.slot_index
                """,
                (st["section_id"],),
            ).fetchall()
        ]
        classmates = [
            dict(r)
            for r in conn.execute(
                "SELECT id, erp_id, full_name, roll_no FROM students WHERE section_id = ? ORDER BY roll_no",
                (st["section_id"],),
            ).fetchall()
        ]
        clubs = [
            dict(r)
            for r in conn.execute(
                """
                SELECT te.*, r.room_code, f.full_name AS faculty_name
                FROM timetable_entries te
                JOIN rooms r ON r.id = te.room_id
                LEFT JOIN faculty f ON f.id = te.faculty_id
                WHERE te.allocation_category = 'CLUB_EXTRACURRICULAR'
                ORDER BY te.day_of_week, te.slot_index
                """
            ).fetchall()
        ]
        return jsonify(
            {
                "student": dict(st),
                "entries": entries,
                "classmates": classmates,
                "clubs": clubs,
            }
        )
    finally:
        conn.close()


# =========================================================================
# ERP INTEGRATION & BULK SYNC ENDPOINTS
# =========================================================================

@app.route("/api/v1/sync/rooms", methods=["POST"])
def sync_rooms():
    """Bulk upsert rooms from external ERP."""
    data = request.get_json(force=True) or {}
    room_list = data.get("rooms") or []
    if not isinstance(room_list, list) or not room_list:
        return jsonify({"error": "Expected non-empty 'rooms' array."}), 400

    conn = get_connection()
    upserted = 0
    try:
        for r in room_list:
            code = (r.get("room_code") or "").strip().upper()
            if not code:
                continue
            bld = (r.get("building") or "Main Block").strip()
            flr = (r.get("floor") or "Ground Floor").strip()
            rtype = (r.get("room_type") or "CLASSROOM").strip().upper()
            cap = int(r.get("capacity") or 60)
            status = (r.get("status") or "ACTIVE").strip().upper()

            conn.execute(
                """
                INSERT INTO rooms (room_code, building, floor, room_type, capacity, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(room_code) DO UPDATE SET
                    building = excluded.building,
                    floor = excluded.floor,
                    room_type = excluded.room_type,
                    capacity = excluded.capacity,
                    status = excluded.status
                """,
                (code, bld, flr, rtype, cap, status),
            )
            upserted += 1
        conn.commit()
        return jsonify({"ok": True, "upserted_count": upserted})
    finally:
        conn.close()


@app.route("/api/v1/sync/faculty", methods=["POST"])
def sync_faculty():
    """Bulk upsert faculty members and qualified subject codes from external ERP."""
    data = request.get_json(force=True) or {}
    faculty_list = data.get("faculty") or []
    if not isinstance(faculty_list, list) or not faculty_list:
        return jsonify({"error": "Expected non-empty 'faculty' array."}), 400

    conn = get_connection()
    upserted = 0
    try:
        for f in faculty_list:
            code = (f.get("faculty_code") or "").strip().upper()
            name = (f.get("full_name") or "").strip()
            if not code or not name:
                continue
            dept = (f.get("department") or "General").strip()
            max_lpd = int(f.get("max_lectures_per_day") or 4)

            conn.execute(
                """
                INSERT INTO faculty (faculty_code, full_name, department, max_lectures_per_day)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(faculty_code) DO UPDATE SET
                    full_name = excluded.full_name,
                    department = excluded.department,
                    max_lectures_per_day = excluded.max_lectures_per_day
                """,
                (code, name, dept, max_lpd),
            )
            fac_id = conn.execute("SELECT id FROM faculty WHERE faculty_code = ?", (code,)).fetchone()["id"]

            # Optional qualification mapping via subject codes
            for sub_code in f.get("qualified_subject_codes", []):
                sub = conn.execute(
                    "SELECT id FROM subjects WHERE UPPER(subject_code) = UPPER(?)",
                    (str(sub_code).strip(),),
                ).fetchone()
                if sub:
                    conn.execute(
                        "INSERT OR IGNORE INTO teacher_subjects (faculty_id, subject_id) VALUES (?, ?)",
                        (fac_id, sub["id"]),
                    )
            upserted += 1

        conn.commit()
        return jsonify({"ok": True, "upserted_count": upserted})
    finally:
        conn.close()


@app.route("/api/v1/sync/academic-events", methods=["POST"])
def sync_academic_events():
    """Bulk replace or insert academic calendar events (Holidays & Exams) from external ERP."""
    data = request.get_json(force=True) or {}
    events = data.get("events") or []
    replace = bool(data.get("replace", False))
    conn = get_connection()
    inserted = 0
    try:
        if replace:
            conn.execute("DELETE FROM academic_events")
        for ev in events:
            etype = (ev.get("event_type") or "HOLIDAY").strip().upper()
            title = (ev.get("title") or "").strip()
            s_date = ev.get("start_date")
            e_date = ev.get("end_date") or s_date
            if not title or not s_date or not e_date or s_date > e_date:
                continue
            conn.execute(
                "INSERT INTO academic_events (event_type, title, start_date, end_date) VALUES (?, ?, ?, ?)",
                (etype, title, s_date, e_date),
            )
            inserted += 1
        conn.commit()
        return jsonify({"ok": True, "synced_count": inserted})
    finally:
        conn.close()


@app.route("/api/v1/export/timetable", methods=["GET"])
def export_timetable():
    """Full timetable export with natural ERP codes for seamless parent-system ingestion."""
    course_code = request.args.get("course_code")
    validity_type = request.args.get("validity_type")
    conn = get_connection()
    try:
        sql = """
            SELECT te.id, te.allocation_category, te.custom_title,
                   c.code AS course_code, c.name AS course_name,
                   s.year_number, s.shift, s.section_code,
                   te.day_of_week, te.slot_index, te.start_time, te.end_time,
                   sub.subject_code, sub.subject_name, sub.requires_lab,
                   f.faculty_code, f.full_name AS faculty_name,
                   r.room_code, r.room_type, r.building, r.floor,
                   te.assignment_mode, te.validity_type, te.effective_from, te.effective_to,
                   te.reason, te.created_at
            FROM timetable_entries te
            LEFT JOIN sections s ON s.id = te.section_id
            LEFT JOIN courses c ON c.id = s.course_id
            LEFT JOIN subjects sub ON sub.id = te.subject_id
            LEFT JOIN faculty f ON f.id = te.faculty_id
            JOIN rooms r ON r.id = te.room_id
            WHERE 1=1
        """
        params = []
        if course_code:
            sql += " AND UPPER(c.code) = UPPER(?)"
            params.append(course_code.strip())
        if validity_type:
            sql += " AND UPPER(te.validity_type) = UPPER(?)"
            params.append(validity_type.strip())
        sql += " ORDER BY c.id, s.year_number, te.shift DESC, s.section_code, te.day_of_week, te.start_time"

        entries = [dict(r) for r in conn.execute(sql, params).fetchall()]
        return jsonify({
            "count": len(entries),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "timetable": entries
        })
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
