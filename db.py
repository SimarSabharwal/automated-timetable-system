import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "timetable.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        # Check if schema needs upgrade from v1 (without validity_type)
        cols = [
            r["name"]
            for r in conn.execute("PRAGMA table_info(timetable_entries)").fetchall()
        ]
        if cols and ("validity_type" not in cols or "allocation_category" not in cols):
            conn.executescript(
                """
                DROP TABLE IF EXISTS timetable_entries;
                DROP TABLE IF EXISTS teacher_subjects;
                DROP TABLE IF EXISTS teacher_availability;
                DROP TABLE IF EXISTS academic_events;
                """
            )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                duration_years INTEGER NOT NULL,
                shifts TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_code TEXT NOT NULL UNIQUE,
                building TEXT NOT NULL,
                floor TEXT NOT NULL,
                room_type TEXT NOT NULL DEFAULT 'CLASSROOM',
                capacity INTEGER NOT NULL DEFAULT 60,
                status TEXT NOT NULL DEFAULT 'ACTIVE'
            );

            CREATE TABLE IF NOT EXISTS faculty (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_code TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT 'General',
                max_lectures_per_day INTEGER NOT NULL DEFAULT 4
            );

            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                year_number INTEGER NOT NULL,
                shift TEXT NOT NULL,
                section_code TEXT NOT NULL,
                capacity INTEGER NOT NULL DEFAULT 60,
                primary_room_id INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
                UNIQUE(course_id, year_number, shift, section_code)
            );

            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                erp_id TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                roll_no INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                year_number INTEGER NOT NULL,
                subject_code TEXT NOT NULL,
                subject_name TEXT NOT NULL,
                requires_lab INTEGER NOT NULL DEFAULT 0,
                lectures_per_week INTEGER NOT NULL DEFAULT 4,
                faculty_id INTEGER REFERENCES faculty(id) ON DELETE SET NULL,
                UNIQUE(course_id, year_number, subject_code)
            );

            -- Clause 1 (Student System): Teacher Qualification Mapping
            CREATE TABLE IF NOT EXISTS teacher_subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                UNIQUE(faculty_id, subject_id)
            );

            -- Clause 2 (Student System): Teacher Unavailability Windows
            CREATE TABLE IF NOT EXISTS teacher_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                shift TEXT NOT NULL DEFAULT 'ALL', -- ALL, MORNING, AFTERNOON
                reason TEXT NOT NULL DEFAULT ''
            );

            -- Clause 4 (Student System): Holiday & Exam Calendar Exclusions
            CREATE TABLE IF NOT EXISTS academic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL, -- HOLIDAY, EXAM
                title TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL
            );

            -- Lifetime vs Dated Timetable Entries (Course OR Club/Extracurricular)
            CREATE TABLE IF NOT EXISTS timetable_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_category TEXT NOT NULL DEFAULT 'COURSE', -- COURSE or CLUB_EXTRACURRICULAR
                section_id INTEGER REFERENCES sections(id) ON DELETE CASCADE,
                day_of_week TEXT NOT NULL,
                shift TEXT NOT NULL,
                slot_index INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
                faculty_id INTEGER REFERENCES faculty(id) ON DELETE SET NULL,
                room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                custom_title TEXT NOT NULL DEFAULT '',
                assignment_mode TEXT NOT NULL DEFAULT 'MANUAL',
                validity_type TEXT NOT NULL DEFAULT 'LIFETIME', -- LIFETIME or DATED
                effective_from TEXT, -- YYYY-MM-DD when DATED, NULL when LIFETIME
                effective_to TEXT,   -- YYYY-MM-DD when DATED, NULL when LIFETIME
                reason TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
        seed_initial_data(conn)
    finally:
        conn.close()


def seed_initial_data(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    if existing == 0:
        courses_data = [
            ("BCA", "Bachelor of Computer Applications", 3, "MORNING,AFTERNOON"),
            ("BBA", "Bachelor of Business Administration", 3, "MORNING,AFTERNOON"),
            ("MBA", "Master of Business Administration", 1, "MORNING"),
            ("LLB", "Bachelor of Laws (Integrated LLB)", 5, "MORNING,AFTERNOON"),
        ]
        conn.executemany(
            "INSERT INTO courses (code, name, duration_years, shifts) VALUES (?, ?, ?, ?)",
            courses_data,
        )
        course_map = {
            row["code"]: row["id"]
            for row in conn.execute("SELECT id, code FROM courses").fetchall()
        }

        rooms_data = [
            # Ground Floor: G01–G04 (G04 is a Computer Lab)
            ("G01", "Main Block", "Ground Floor", "CLASSROOM", 70, "ACTIVE"),
            ("G02", "Main Block", "Ground Floor", "CLASSROOM", 70, "ACTIVE"),
            ("G03", "Main Block", "Ground Floor", "CLASSROOM", 65, "ACTIVE"),
            ("G04", "Main Block", "Ground Floor", "COMPUTER_LAB", 60, "ACTIVE"),
            # First Floor: 101–108 (104 and 107 are Computer Labs)
            ("101", "Main Block", "First Floor", "CLASSROOM", 65, "ACTIVE"),
            ("102", "Main Block", "First Floor", "CLASSROOM", 65, "ACTIVE"),
            ("103", "Main Block", "First Floor", "CLASSROOM", 65, "ACTIVE"),
            ("104", "Main Block", "First Floor", "COMPUTER_LAB", 60, "ACTIVE"),
            ("105", "Main Block", "First Floor", "CLASSROOM", 65, "ACTIVE"),
            ("106", "Main Block", "First Floor", "CLASSROOM", 65, "ACTIVE"),
            ("107", "Main Block", "First Floor", "COMPUTER_LAB", 60, "ACTIVE"),
            ("108", "Main Block", "First Floor", "CLASSROOM", 65, "ACTIVE"),
            # Second Floor: 201–208 (All Classrooms, no labs)
            ("201", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("202", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("203", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("204", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("205", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("206", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("207", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            ("208", "Main Block", "Second Floor", "CLASSROOM", 65, "ACTIVE"),
            # Third Floor: 301–308 (All Classrooms, no labs)
            ("301", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("302", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("303", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("304", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("305", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("306", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("307", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            ("308", "Main Block", "Third Floor", "CLASSROOM", 65, "ACTIVE"),
            # Co-Curricular Venues (Excluded from regular course scheduling)
            ("AMPHITHEATER", "Cultural Wing", "Ground Floor", "AMPHITHEATER", 300, "ACTIVE"),
            ("AUDITORIUM", "Main Block", "Ground Floor", "AUDITORIUM", 500, "ACTIVE"),
        ]
        conn.executemany(
            """
            INSERT INTO rooms (room_code, building, floor, room_type, capacity, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rooms_data,
        )

        faculty_data = [
            ("MGS", "Dr. Megha Sehgal", "Computer Science", 4),
            ("MAG", "Dr. Mansi Agnihotri", "Computer Science", 4),
            ("DSB", "Dr. Daljeet Singh Bawa", "Computer Science", 4),
            ("UG", "Dr. Usha Gupta", "Computer Science", 4),
            ("MKC", "Dr. Mahesh Kumar Chaubey", "Computer Science", 4),
            ("AK", "Dr. Ajay Kumar", "Management", 4),
            ("AKR", "Mr. Amit Kumar", "General", 4),
            ("YK", "Mr. Yashwant Kumar", "Computer Science", 4),
            ("NPN", "Mr. Nripesh Kumar", "Management", 4),
            ("RKS", "Prof. R.K. Sharma", "Management", 4),
            ("PM", "Dr. Priya Malhotra", "Management", 4),
            ("VKS", "Adv. Vikram Singh", "Law", 4),
            ("ANS", "Dr. Ananya Sen", "Law", 4),
            ("RJV", "Prof. Rajeev Verma", "Law", 4),
        ]
        conn.executemany(
            "INSERT INTO faculty (faculty_code, full_name, department, max_lectures_per_day) VALUES (?, ?, ?, ?)",
            faculty_data,
        )
        fac_map = {
            row["faculty_code"]: row["id"]
            for row in conn.execute("SELECT id, faculty_code FROM faculty").fetchall()
        }

        sections_to_insert = []
        # BCA: Grade-wise (no sections), 3 years, Morning & Afternoon
        for yr in range(1, 4):
            sections_to_insert.append((course_map["BCA"], yr, "MORNING", "Grade-Wise", 60, None))
            sections_to_insert.append((course_map["BCA"], yr, "AFTERNOON", "Grade-Wise", 60, None))

        # BBA: 3 years, Morning (M1-M3) & Afternoon (A1-A3)
        for yr in range(1, 4):
            for s in ("M1", "M2", "M3"):
                sections_to_insert.append((course_map["BBA"], yr, "MORNING", s, 60, None))
            for s in ("A1", "A2", "A3"):
                sections_to_insert.append((course_map["BBA"], yr, "AFTERNOON", s, 60, None))

        # MBA: 1 year, Morning (M1, M2)
        for s in ("M1", "M2"):
            sections_to_insert.append((course_map["MBA"], 1, "MORNING", s, 60, None))

        # LLB: 5 years, Morning (M1-M2) & Afternoon (A1-A2)
        for yr in range(1, 6):
            for s in ("M1", "M2"):
                sections_to_insert.append((course_map["LLB"], yr, "MORNING", s, 60, None))
            for s in ("A1", "A2"):
                sections_to_insert.append((course_map["LLB"], yr, "AFTERNOON", s, 60, None))

        conn.executemany(
            """
            INSERT INTO sections (course_id, year_number, shift, section_code, capacity, primary_room_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            sections_to_insert,
        )

        subjects_data = [
            (course_map["BCA"], 1, "34344", "Algorithms & Program Design Using C", 0, 4, fac_map["MGS"]),
            (course_map["BCA"], 1, "34345", "Mathematical Foundation", 0, 4, fac_map["YK"]),
            (course_map["BCA"], 1, "34346", "Foundations of Computing", 0, 4, fac_map["MAG"]),
            (course_map["BCA"], 1, "34347", "Client-Side Web Technologies", 0, 4, fac_map["DSB"]),
            (course_map["BCA"], 1, "LAB-C", "C Programming Lab", 1, 2, fac_map["MGS"]),
            (course_map["BCA"], 1, "YOGA", "Yoga & Meditation", 0, 2, fac_map["AKR"]),
            (course_map["BCA"], 2, "JP", "Java Programming", 0, 4, fac_map["MGS"]),
            (course_map["BCA"], 2, "OS", "Operating Systems", 0, 4, fac_map["MAG"]),
            (course_map["BCA"], 2, "SE", "Software Engineering", 0, 4, fac_map["DSB"]),
            (course_map["BCA"], 2, "ST", "Statistics", 0, 4, fac_map["YK"]),
            (course_map["BCA"], 2, "LAB JP", "Java Programming Lab", 1, 2, fac_map["MGS"]),
            (course_map["BCA"], 2, "LAB ORACLE", "Oracle Lab", 1, 2, fac_map["MKC"]),
            (course_map["BCA"], 3, "PY-301", "Python & Data Science", 0, 4, fac_map["MKC"]),
            (course_map["BCA"], 3, "CN-302", "Computer Networks", 0, 4, fac_map["UG"]),
            (course_map["BCA"], 3, "AI-303", "Artificial Intelligence", 0, 4, fac_map["MAG"]),
            (course_map["BCA"], 3, "SUM", "Start-up Management", 0, 4, fac_map["AK"]),
            (course_map["BCA"], 3, "LAB PY", "Python & AI Lab", 1, 4, fac_map["MKC"]),
            (course_map["BBA"], 1, "34136", "Principles of Management", 0, 4, fac_map["AK"]),
            (course_map["BBA"], 1, "34137", "Business Communication", 0, 4, fac_map["PM"]),
            (course_map["BBA"], 1, "34138", "Financial Accounting: Concepts & Practices", 0, 4, fac_map["RKS"]),
            (course_map["BBA"], 1, "34139", "Business Mathematics", 0, 4, fac_map["NPN"]),
            (course_map["BBA"], 1, "34140", "Micro Economics", 0, 2, fac_map["PM"]),
            (course_map["BBA"], 1, "34142", "Environmental Studies", 0, 2, fac_map["AKR"]),
            (course_map["BBA"], 2, "BBA-201", "Organizational Behaviour", 0, 4, fac_map["AK"]),
            (course_map["BBA"], 2, "BBA-202", "Marketing Management", 0, 4, fac_map["PM"]),
            (course_map["BBA"], 2, "BBA-203", "Cost & Management Accounting", 0, 4, fac_map["RKS"]),
            (course_map["BBA"], 2, "BBA-204", "Business Research Methods", 0, 4, fac_map["NPN"]),
            (course_map["BBA"], 2, "BBA-205", "Human Resource Management", 0, 4, fac_map["AK"]),
            (course_map["BBA"], 3, "BBA-301", "Strategic Management", 0, 5, fac_map["AK"]),
            (course_map["BBA"], 3, "BBA-302", "Corporate Finance", 0, 5, fac_map["RKS"]),
            (course_map["BBA"], 3, "BBA-303", "International Business", 0, 5, fac_map["PM"]),
            (course_map["BBA"], 3, "BBA-304", "Entrepreneurship Development", 0, 5, fac_map["NPN"]),
            (course_map["MBA"], 1, "MBA-101", "Managerial Economics", 0, 4, fac_map["PM"]),
            (course_map["MBA"], 1, "MBA-102", "Corporate Strategy & Governance", 0, 4, fac_map["AK"]),
            (course_map["MBA"], 1, "MBA-103", "Financial Management", 0, 4, fac_map["RKS"]),
            (course_map["MBA"], 1, "MBA-104", "Quantitative Techniques", 0, 4, fac_map["NPN"]),
            (course_map["MBA"], 1, "MBA-105", "Marketing Analytics", 0, 4, fac_map["PM"]),
            (course_map["LLB"], 1, "LLB-101", "Jurisprudence & Legal Theory", 0, 4, fac_map["ANS"]),
            (course_map["LLB"], 1, "LLB-102", "Law of Contract I", 0, 4, fac_map["VKS"]),
            (course_map["LLB"], 1, "LLB-103", "Law of Torts & Consumer Protection", 0, 4, fac_map["RJV"]),
            (course_map["LLB"], 1, "LLB-104", "Constitutional Law I", 0, 4, fac_map["ANS"]),
            (course_map["LLB"], 1, "LLB-105", "Legal English & Moot Advocacy", 0, 4, fac_map["VKS"]),
            (course_map["LLB"], 2, "LLB-201", "Constitutional Law II", 0, 5, fac_map["ANS"]),
            (course_map["LLB"], 2, "LLB-202", "Family Law I", 0, 5, fac_map["RJV"]),
            (course_map["LLB"], 2, "LLB-203", "Law of Crimes (BNS)", 0, 5, fac_map["VKS"]),
            (course_map["LLB"], 2, "LLB-204", "Administrative Law", 0, 5, fac_map["ANS"]),
            (course_map["LLB"], 3, "LLB-301", "Property Law", 0, 5, fac_map["RJV"]),
            (course_map["LLB"], 3, "LLB-302", "Company Law", 0, 5, fac_map["VKS"]),
            (course_map["LLB"], 3, "LLB-303", "Public International Law", 0, 5, fac_map["ANS"]),
            (course_map["LLB"], 3, "LLB-304", "Labour & Industrial Law", 0, 5, fac_map["RJV"]),
            (course_map["LLB"], 4, "LLB-401", "Civil Procedure Code (CPC)", 0, 5, fac_map["VKS"]),
            (course_map["LLB"], 4, "LLB-402", "Law of Evidence (BSA)", 0, 5, fac_map["ANS"]),
            (course_map["LLB"], 4, "LLB-403", "Environmental Law", 0, 5, fac_map["RJV"]),
            (course_map["LLB"], 4, "LLB-404", "Taxation Law", 0, 5, fac_map["RKS"]),
            (course_map["LLB"], 5, "LLB-501", "Arbitration & ADR", 0, 5, fac_map["VKS"]),
            (course_map["LLB"], 5, "LLB-502", "Intellectual Property Rights", 0, 5, fac_map["ANS"]),
            (course_map["LLB"], 5, "LLB-503", "Drafting, Pleading & Conveyancing", 0, 5, fac_map["RJV"]),
            (course_map["LLB"], 5, "LLB-504", "Moot Court & Trial Advocacy", 0, 5, fac_map["VKS"]),
        ]
        conn.executemany(
            """
            INSERT INTO subjects (
                course_id, year_number, subject_code, subject_name,
                requires_lab, lectures_per_week, faculty_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            subjects_data,
        )

    # Seed teacher_subjects from each subject's default faculty_id if empty
    ts_count = conn.execute("SELECT COUNT(*) FROM teacher_subjects").fetchone()[0]
    if ts_count == 0:
        conn.execute(
            """
            INSERT OR IGNORE INTO teacher_subjects (faculty_id, subject_id)
            SELECT faculty_id, id FROM subjects WHERE faculty_id IS NOT NULL
            """
        )

    # Seed sample academic event (Winter Exam / Holiday example) if empty
    ev_count = conn.execute("SELECT COUNT(*) FROM academic_events").fetchone()[0]
    if ev_count == 0:
        conn.executemany(
            "INSERT INTO academic_events (event_type, title, start_date, end_date) VALUES (?, ?, ?, ?)",
            [
                ("HOLIDAY", "Guru Nanak Jayanti", "2026-11-24", "2026-11-24"),
                ("EXAM", "Winter 2026 Theory Examinations", "2026-12-14", "2026-12-23"),
            ],
        )

    # Seed 30 students per section/shift if students table is empty
    stu_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    if stu_count == 0:
        first_names = [
            "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
            "Ananya", "Diya", "Saanvi", "Aadhya", "Kiara", "Pari", "Myra", "Riya", "Kavya", "Navya",
            "Rohan", "Kabir", "Karan", "Rahul", "Siddharth", "Tanvi", "Neha", "Pooja", "Simran", "Harsh",
        ]
        last_names = [
            "Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Mehta", "Joshi", "Malhotra", "Kapoor",
            "Bansal", "Agarwal", "Chopra", "Nair", "Iyer", "Rao", "Mishra", "Tiwari", "Saxena", "Chauhan",
        ]
        sec_rows = conn.execute(
            """
            SELECT s.id, c.code AS course_code, s.year_number, s.shift, s.section_code
            FROM sections s
            JOIN courses c ON c.id = s.course_id
            ORDER BY c.id, s.year_number, s.shift DESC, s.section_code
            """
        ).fetchall()

        students_to_insert = []
        for s_idx, sec in enumerate(sec_rows):
            shift_ch = "M" if sec["shift"] == "MORNING" else "A"
            sec_tag = "G" if sec["section_code"] == "Grade-Wise" else sec["section_code"]
            for roll in range(1, 31):
                fname = first_names[(roll - 1 + s_idx) % len(first_names)]
                lname = last_names[(roll * 3 + s_idx) % len(last_names)]
                erp_id = f"26{sec['course_code']}{sec['year_number']}{shift_ch}{sec_tag}{roll:02d}"
                # Preserve sample_data.json demo IDs on BCA Year 1 Morning/Afternoon Roll 1
                if sec["course_code"] == "BCA" and sec["year_number"] == 1 and roll == 1:
                    erp_id = "0251BCA001" if sec["shift"] == "MORNING" else "0251BCA101"
                students_to_insert.append((erp_id, f"{fname} {lname}", sec["id"], roll))

        conn.executemany(
            "INSERT INTO students (erp_id, full_name, section_id, roll_no) VALUES (?, ?, ?, ?)",
            students_to_insert,
        )

    conn.commit()
