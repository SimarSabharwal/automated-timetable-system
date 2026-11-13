import tempfile
from pathlib import Path

import db
from app import app


def run_tests():
    with tempfile.TemporaryDirectory() as tmpdir:
        db.DB_PATH = Path(tmpdir) / "test_timetable.db"
        db.init_db()

        client = app.test_client()

        boot = client.get("/api/v1/bootstrap").get_json()
        courses = {c["code"]: c for c in boot["courses"]}
        assert set(courses.keys()) == {"BCA", "BBA", "MBA", "LLB"}

        sections = boot["sections"]
        rooms = {r["room_code"]: r for r in boot["rooms"]}
        assert len(rooms) == 30
        assert rooms["AMPHITHEATER"]["room_type"] == "AMPHITHEATER"
        assert rooms["AUDITORIUM"]["room_type"] == "AUDITORIUM"
        assert rooms["G04"]["room_type"] == "COMPUTER_LAB"
        assert rooms["104"]["room_type"] == "COMPUTER_LAB"
        assert rooms["107"]["room_type"] == "COMPUTER_LAB"
        assert all(rooms[f"20{i}"]["room_type"] == "CLASSROOM" for i in range(1, 9))
        assert all(rooms[f"30{i}"]["room_type"] == "CLASSROOM" for i in range(1, 9))
        faculty = {f["faculty_code"]: f for f in boot["faculty"]}
        g01 = rooms["G01"]
        g02 = rooms["G02"]

        llb_m1 = next(
            s for s in sections
            if s["course_code"] == "LLB" and s["year_number"] == 1 and s["shift"] == "MORNING" and s["section_code"] == "M1"
        )
        bba_m1 = next(
            s for s in sections
            if s["course_code"] == "BBA" and s["year_number"] == 1 and s["shift"] == "MORNING" and s["section_code"] == "M1"
        )
        bca_secs = [s for s in sections if s["course_code"] == "BCA"]
        assert len(bca_secs) == 6
        assert all(s["section_code"] == "Grade-Wise" for s in bca_secs)
        assert len([s for s in sections if s["course_code"] == "BBA"]) == 18
        assert len([s for s in sections if s["course_code"] == "MBA"]) == 2
        assert len([s for s in sections if s["course_code"] == "LLB"]) == 20

        bca_m1 = next(
            s for s in sections
            if s["course_code"] == "BCA" and s["year_number"] == 1 and s["shift"] == "MORNING"
        )

        llb_sub = next(sub for sub in boot["subjects"] if sub["course_code"] == "LLB" and sub["year_number"] == 1)
        bba_sub = next(sub for sub in boot["subjects"] if sub["course_code"] == "BBA" and sub["year_number"] == 1)
        bca_sub = next(
            sub for sub in boot["subjects"]
            if sub["course_code"] == "BCA" and sub["year_number"] == 1 and sub["requires_lab"] == 0
        )

        # 1. LIFETIME booking of G02 by LLB blocks BBA even on future dates
        res = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": llb_m1["id"],
                "day_of_week": "Monday",
                "slot_index": 1,
                "subject_id": llb_sub["id"],
                "faculty_id": llb_sub["faculty_id"],
                "room_id": g02["id"],
                "validity_type": "LIFETIME",
                "reason": "LLB permanent primary class",
            },
        )
        assert res.status_code == 201, res.get_json()

        conflict_lifetime = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Monday",
                "slot_index": 1,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": g02["id"],
                "validity_type": "DATED",
                "effective_from": "2026-12-01",
                "effective_to": "2026-12-05",
                "reason": "Should fail against Lifetime booking",
            },
        )
        assert conflict_lifetime.status_code == 409

        # 2. DATED booking of G01 by LLB (2026-11-16..2026-11-18) blocks overlapping date, allows non-overlapping date
        res_dated = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": llb_m1["id"],
                "day_of_week": "Tuesday",
                "slot_index": 1,
                "subject_id": llb_sub["id"],
                "faculty_id": llb_sub["faculty_id"],
                "room_id": g01["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-16",
                "effective_to": "2026-11-18",
                "reason": "3-day moot workshop",
            },
        )
        assert res_dated.status_code == 201, res_dated.get_json()

        overlap_res = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Tuesday",
                "slot_index": 1,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": g01["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-17",
                "effective_to": "2026-11-19",
                "reason": "Overlapping date must fail",
            },
        )
        assert overlap_res.status_code == 409

        non_overlap_res = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Tuesday",
                "slot_index": 1,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": g01["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-23",
                "effective_to": "2026-11-23",
                "reason": "Non-overlapping date is allowed",
            },
        )
        assert non_overlap_res.status_code == 201, non_overlap_res.get_json()

        # 3. Clause 1: Teacher Qualification Lock (VKS cannot teach BCA subject)
        qual_fail = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bca_m1["id"],
                "day_of_week": "Wednesday",
                "slot_index": 1,
                "subject_id": bca_sub["id"],
                "faculty_id": faculty["VKS"]["id"],
                "room_id": g01["id"],
                "validity_type": "LIFETIME",
                "reason": "Testing unqualified substitute",
            },
        )
        assert qual_fail.status_code == 409
        assert "Qualification Clause" in qual_fail.get_json()["error"]

        # 4. Clause 2: Teacher Unavailability Window
        unav = client.post(
            "/api/v1/teacher-availability",
            json={
                "faculty_id": bca_sub["faculty_id"],
                "start_date": "2026-11-18",
                "end_date": "2026-11-20",
                "shift": "ALL",
                "reason": "Conference",
            },
        )
        assert unav.status_code == 201

        unav_fail = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bca_m1["id"],
                "day_of_week": "Wednesday",
                "slot_index": 2,
                "subject_id": bca_sub["id"],
                "faculty_id": bca_sub["faculty_id"],
                "room_id": g01["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-19",
                "effective_to": "2026-11-19",
                "reason": "Should fail due to teacher unavailability",
            },
        )
        assert unav_fail.status_code == 409
        assert "Availability Clause" in unav_fail.get_json()["error"]

        # 5. Clause 4: Holiday Calendar Exclusion (2026-11-24 is Guru Nanak Jayanti)
        holiday_fail = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bca_m1["id"],
                "day_of_week": "Tuesday",
                "slot_index": 3,
                "subject_id": bca_sub["id"],
                "faculty_id": bca_sub["faculty_id"],
                "room_id": g01["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-24",
                "effective_to": "2026-11-24",
                "reason": "Class on holiday",
            },
        )
        assert holiday_fail.status_code == 409
        assert "Holiday/Exam Clause" in holiday_fail.get_json()["error"]

        # 5b. Teacher Repeat Clause (same teacher in adjacent Slot 1 & Slot 2 for same class)
        r_s1 = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Friday",
                "slot_index": 1,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": rooms["101"]["id"],
                "validity_type": "LIFETIME",
                "reason": "Slot 1",
            },
        )
        assert r_s1.status_code == 201, r_s1.get_json()
        r_s2_repeat = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Friday",
                "slot_index": 2,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": rooms["102"]["id"],
                "validity_type": "LIFETIME",
                "reason": "Slot 2 repeat teacher",
            },
        )
        assert r_s2_repeat.status_code == 409
        assert "Teacher Repeat Clause" in r_s2_repeat.get_json()["error"]

        # 6. Clause 5: Dynamic Reallocation when room goes to MAINTENANCE
        tt_all = client.get("/api/v1/timetable").get_json()["entries"]
        g02_entry = next(e for e in tt_all if e["room_code"] == "G02")
        client.patch(f"/api/v1/rooms/{g02['id']}", json={"status": "MAINTENANCE"})
        realloc = client.post(f"/api/v1/timetable/{g02_entry['id']}/reallocate")
        assert realloc.status_code == 200, realloc.get_json()
        assert realloc.get_json()["action"] == "ROOM_SWAPPED"

        # 7. Co-Curricular rough-timing booking (09:00-10:00) & Amphitheater/Auditorium rules
        # Course cannot book AUDITORIUM
        aud_course_fail = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Wednesday",
                "slot_index": 1,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": rooms["AUDITORIUM"]["id"],
                "validity_type": "LIFETIME",
                "reason": "Courses cannot use Auditorium",
            },
        )
        assert aud_course_fail.status_code == 409

        # Co-Curricular can book AUDITORIUM for 09:00-10:00 on 2026-11-25 with Teacher In-Charge
        aud_ok = client.post(
            "/api/v1/timetable/manual",
            json={
                "allocation_category": "CLUB_EXTRACURRICULAR",
                "day_of_week": "Wednesday",
                "start_time": "09:00",
                "end_time": "10:00",
                "room_id": rooms["AUDITORIUM"]["id"],
                "faculty_id": faculty["AKR"]["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-25",
                "effective_to": "2026-11-25",
                "reason": "Dramatics Society — Street Play",
            },
        )
        assert aud_ok.status_code == 201, aud_ok.get_json()

        # Overlapping 09:30-10:30 on same date in AUDITORIUM is blocked
        aud_overlap = client.post(
            "/api/v1/timetable/manual",
            json={
                "allocation_category": "CLUB_EXTRACURRICULAR",
                "day_of_week": "Wednesday",
                "start_time": "09:30",
                "end_time": "10:30",
                "room_id": rooms["AUDITORIUM"]["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-25",
                "effective_to": "2026-11-25",
                "reason": "Music Society",
            },
        )
        assert aud_overlap.status_code == 409

        # Non-overlapping 11:00-12:00 on same date in AUDITORIUM succeeds
        aud_later = client.post(
            "/api/v1/timetable/manual",
            json={
                "allocation_category": "CLUB_EXTRACURRICULAR",
                "day_of_week": "Wednesday",
                "start_time": "11:00",
                "end_time": "12:00",
                "room_id": rooms["AUDITORIUM"]["id"],
                "validity_type": "DATED",
                "effective_from": "2026-11-25",
                "effective_to": "2026-11-25",
                "reason": "Debate Society",
            },
        )
        assert aud_later.status_code == 201, aud_later.get_json()

        # Co-Curricular booking in regular room 103 (09:00-10:00) blocks Course Slot 1 (09:10-10:05)
        club_res = client.post(
            "/api/v1/timetable/manual",
            json={
                "allocation_category": "CLUB_EXTRACURRICULAR",
                "day_of_week": "Wednesday",
                "start_time": "09:00",
                "end_time": "10:00",
                "room_id": rooms["103"]["id"],
                "validity_type": "LIFETIME",
                "reason": "Coding Club",
            },
        )
        assert club_res.status_code == 201, club_res.get_json()

        club_conflict = client.post(
            "/api/v1/timetable/manual",
            json={
                "section_id": bba_m1["id"],
                "day_of_week": "Wednesday",
                "slot_index": 1,
                "subject_id": bba_sub["id"],
                "faculty_id": bba_sub["faculty_id"],
                "room_id": rooms["103"]["id"],
                "validity_type": "LIFETIME",
                "reason": "Should be blocked by Coding Club",
            },
        )
        assert club_conflict.status_code == 409
        assert "Coding Club" in club_conflict.get_json()["error"]

        # 8. Verify 30 students per section & Teacher/Student Portals reflect allotments
        bba_students = client.get(f"/api/v1/students?section_id={bba_m1['id']}").get_json()["students"]
        assert len(bba_students) == 30
        bca_students = client.get(f"/api/v1/students?section_id={bca_m1['id']}").get_json()["students"]
        assert len(bca_students) == 30
        assert any(st["erp_id"] == "0251BCA001" for st in bca_students)

        tp = client.get(f"/api/v1/portal/teacher/{bba_sub['faculty_id']}").get_json()
        assert any(e["section_id"] == bba_m1["id"] for e in tp["entries"])

        sp = client.get(f"/api/v1/portal/student/{bba_students[0]['id']}").get_json()
        assert len(sp["classmates"]) == 30
        assert any(e["subject_id"] == bba_sub["id"] for e in sp["entries"])
        assert any(c["custom_title"] == "Coding Club" for c in sp["clubs"])

        # 9. Automate & Reset Auto-Generated Timetable (preserving Manual slots)
        auto_res = client.post(
            "/api/v1/timetable/automate",
            json={"section_ids": [bba_m1["id"]], "weekdays": ["Monday", "Tuesday"]},
        )
        assert auto_res.status_code == 200, auto_res.get_json()
        created_auto = auto_res.get_json()["created_count"]
        assert created_auto > 0

        reset_res = client.post(
            "/api/v1/timetable/clear",
            json={"section_ids": [bba_m1["id"]], "mode": "AUTO"},
        )
        assert reset_res.status_code == 200, reset_res.get_json()
        assert reset_res.get_json()["deleted_count"] == created_auto

        remaining_bba = client.get(f"/api/v1/timetable?section_id={bba_m1['id']}").get_json()["entries"]
        assert all(e["assignment_mode"] == "MANUAL" for e in remaining_bba)
        assert len(remaining_bba) >= 2  # Manual slots remain untouched

        print("ALL STUDENT SYSTEM CLAUSES & LIFETIME/DATED TESTS PASSED!")


if __name__ == "__main__":
    run_tests()
