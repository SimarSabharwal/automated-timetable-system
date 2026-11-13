# College ERP Integration Guide — Automated Timetable & Venue Allotment API

This guide provides end-to-end instructions, architecture diagrams, endpoint specifications, and copy-paste code snippets for integrating this **Automated Timetable & Venue Allotment Module** into an **existing College ERP system** as a standalone microservice / API service.

---

## 🏗️ 1. Integration Architecture

In an existing ERP ecosystem, the main ERP manages user accounts, fees, payroll, and student registrations. Instead of embedding timetable constraint solving inside the monolithic ERP database, this module acts as a **specialized scheduling engine microservice**:

```text
┌─────────────────────────────────────────────────────────────┐
│                     Existing College ERP                    │
│    (Django / Express / Laravel / Spring / Next.js / etc.)   │
└──────────────┬───────────────────────────────▲──────────────┘
               │                               │
       REST/JSON API Calls             Live Timetable & Sync
  (Sync Data, Auto-Schedule,            (Zero Double-Booking,
   Manual Booking, Portals)             Student/Teacher Views)
               │                               │
               ▼                               │
┌──────────────────────────────────────────────┴──────────────┐
│       Automated Timetable & Venue Allotment Engine          │
│                    (This Module :5000)                      │
│                                                             │
│  • Natural Code Resolution (room_code, faculty_code, etc.)  │
│  • Lifetime & Dated Scheduling (Effective Date Ranges)      │
│  • Uniqueness Clauses (Holiday, Room Lock, Teacher Repeat)  │
│  • Building Room Master (G01–308, Labs, Amphitheater, Aud)  │
│  • Smart Automation & Depth-2 Dynamic Reallocation Engine   │
└─────────────────────────────────────────────────────────────┘
```

### Why Use It as an API Caller?
1. **Zero Database Coupling**: The main ERP does not need to alter its primary database schema to accommodate complex timetable matrices, slot rules, or GiST interval exclusions.
2. **Natural Code Resolution**: The parent ERP does **not** need to look up or store internal SQLite IDs. It can pass natural codes already in its system (`"BBA"`, `"G01"`, `"MKC"`, `"34136"`).
3. **Pluggable & Independently Scalable**: Can run on the same server (localhost:5000), in a Docker container, or as a distinct cloud service.
4. **CORS Enabled**: Cross-Origin Resource Sharing is enabled out of the box, allowing client-side calls from existing ERP frontend portals (React, Angular, Vue, or blade/blade/JSP).
5. **Optional Microservice Authentication**: Secure communication between systems via `X-API-Key` or `Authorization: Bearer <key>`.

---

## 🔑 2. Key API-Caller Capabilities

| Capability | What It Does | Why It Solves Integration Issues |
|---|---|---|
| **CORS Support** | Automatically adds `Access-Control-Allow-Origin: *` and preflight `OPTIONS` headers. | Prevents browser cross-origin blocks when called directly from the main ERP frontend. |
| **Natural Code Resolution** | Resolves `course_code`, `section_code`, `room_code`, `faculty_code`, and `subject_code` automatically. | Parent ERP sends natural business keys without having to query our internal database IDs first. |
| **Optional Microservice API Key** | Check enabled if `ERP_API_KEY` environment variable is set. | Protects endpoints from unauthorized access in production while remaining open for local development. |
| **Health Probe (`/api/v1/health`)** | Returns uptime, DB connectivity status, and version. | Enables container readiness checks, uptime monitors, and ERP diagnostic dashboards. |
| **Bulk Master Data Sync** | Dedicated `/api/v1/sync/*` endpoints for rooms, faculty, and academic events. | Parent ERP can push changes whenever a new room is added or a teacher takes leave. |
| **Full Timetable Export** | `/api/v1/export/timetable` returns a clean, fully-resolved JSON dump. | Parent ERP can cache or display the final timetable inside its native mobile app or PDF generator. |

---

## 🔄 3. Typical Integration Flow

```text
[Existing ERP]                                     [Timetable Engine]
       │                                                   │
       ├──── 1. GET /api/v1/health ───────────────────────►│  (Verify service readiness)
       │◄─── {"status": "healthy"} ────────────────────────┤
       │                                                   │
       ├──── 2. POST /api/v1/sync/faculty ────────────────►│  (Sync faculty & qualifications)
       │◄─── {"ok": true, "upserted_count": 14} ───────────┤
       │                                                   │
       ├──── 3. POST /api/v1/timetable/automate ──────────►│  (Generate conflict-free timetable)
       │     {"course_code": "BBA", "year_number": 1}      │
       │◄─── {"created_count": 40} ────────────────────────┤
       │                                                   │
       ├──── 4. POST /api/v1/timetable/manual ────────────►│  (Manual or Co-Curricular booking)
       │     {"room_code": "AMPHITHEATER", ...}            │
       │◄─── {"ok": true, "entry_id": 41} ─────────────────┤
       │                                                   │
       ├──── 5. GET /api/v1/export/timetable ─────────────►│  (Pull final schedule into main ERP)
       │◄─── {"count": 41, "timetable": [...]} ────────────┤
```

---

## 📡 4. Complete REST API Reference

Base URL: `http://localhost:5000/api/v1` (or your deployed URL)

All requests and responses use `application/json`. When `ERP_API_KEY` is configured on the server, include either:
- Header: `X-API-Key: <your_key>`
- Or Header: `Authorization: Bearer <your_key>`

---

### 4.1 Health & Readiness Probe
`GET /api/v1/health` (Always public, no auth required)

#### Response `200 OK`:
```json
{
  "status": "healthy",
  "module": "Automated Timetable & Venue Allotment Engine",
  "version": "1.2.0",
  "database": "connected",
  "auth_configured": true,
  "timestamp": "2026-11-13T18:15:30.123456+00:00"
}
```

---

### 4.2 Automated Timetable Generation
`POST /api/v1/timetable/automate`

Triggers conflict-free timetable generation. You can pass **internal `section_ids`** OR **natural course identifiers** (`course_code`, `year_number`, `shift`).

#### Request Payload:
```json
{
  "course_code": "BBA",
  "year_number": 1,
  "shift": "MORNING",
  "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
  "validity_type": "LIFETIME",
  "overwrite_auto": true
}
```

*Note on Dated Generation:*
To generate for a specific semester date range instead of Lifetime, pass:
```json
{
  "validity_type": "DATED",
  "effective_from": "2026-11-16",
  "effective_to": "2026-12-11"
}
```

#### Response `200 OK`:
```json
{
  "created_count": 40,
  "section_summaries": [
    { "section_id": 7, "label": "BBA Y1 M1", "created": 20 },
    { "section_id": 8, "label": "BBA Y1 M2", "created": 20 }
  ],
  "skipped_slots": [],
  "excluded_events": []
}
```

---

### 4.3 Manual Slot Allotment (Self-Assigned Course Lecture)
`POST /api/v1/timetable/manual`

Allots a lecture with conflict-checking and mandatory reason. Accepts natural codes or numeric IDs.

#### Request Payload (Using Natural Codes):
```json
{
  "allocation_category": "COURSE",
  "course_code": "BBA",
  "year_number": 1,
  "shift": "MORNING",
  "section_code": "M1",
  "day_of_week": "Monday",
  "slot_index": 1,
  "subject_code": "34136",
  "faculty_code": "AK",
  "room_code": "G01",
  "validity_type": "LIFETIME",
  "reason": "Core Management Lecture - Primary Classroom"
}
```

#### Response `201 Created`:
```json
{
  "ok": true,
  "message": "Slot allotted successfully.",
  "entry_id": 105
}
```

#### Conflict Error `409 Conflict`:
```json
{
  "error": "Room G01 is ALREADY BOOKED on Monday (09:10–10:05, Lifetime) by LLB Year 1 Sec M1 for Jurisprudence — Reason: Primary class.",
  "conflicts": [
    "Room G01 is ALREADY BOOKED on Monday (09:10–10:05, Lifetime) by LLB Year 1 Sec M1 for Jurisprudence — Reason: Primary class."
  ]
}
```

---

### 4.4 Co-Curricular & Venue Booking (Rough Timings)
`POST /api/v1/timetable/manual`

Books an event or club venue without binding to any academic course or lecture slot. Can book `AMPHITHEATER`, `AUDITORIUM`, or standard classrooms.

#### Request Payload:
```json
{
  "allocation_category": "CLUB_EXTRACURRICULAR",
  "day_of_week": "Wednesday",
  "start_time": "09:00",
  "end_time": "11:00",
  "room_code": "AMPHITHEATER",
  "faculty_code": "AKR",
  "validity_type": "DATED",
  "effective_from": "2026-11-25",
  "effective_to": "2026-11-25",
  "reason": "Dramatics Society — Annual Play Rehearsal"
}
```

#### Response `201 Created`:
```json
{
  "ok": true,
  "message": "Slot allotted successfully.",
  "entry_id": 106
}
```

---

### 4.5 Live Room Occupancy Inspector
`GET /api/v1/rooms/availability`

Query room availability for a specific day, slot, or exact time window.

#### Query Parameters:
- `day` (e.g., `Monday`)
- `shift` (optional, default `MORNING`)
- `slot_index` (optional, `1`–`4`)
- `start_time` & `end_time` (optional, e.g. `09:00` & `10:30` for custom window)
- `target_date` (optional, `YYYY-MM-DD` for dated checks)

#### Response `200 OK`:
```json
{
  "rooms": [
    {
      "id": 1,
      "room_code": "G01",
      "room_type": "CLASSROOM",
      "capacity": 70,
      "availability": "BOOKED",
      "booking": {
        "course_code": "LLB",
        "year_number": 1,
        "section_code": "M1",
        "subject_name": "Jurisprudence & Legal Theory",
        "faculty_code": "ANS",
        "start_time": "09:10",
        "end_time": "10:05",
        "reason": "Primary class"
      }
    },
    {
      "id": 2,
      "room_code": "G02",
      "room_type": "CLASSROOM",
      "capacity": 70,
      "availability": "FREE",
      "booking": null
    }
  ]
}
```

---

### 4.6 Dynamic Reallocation
`POST /api/v1/timetable/<entry_id>/reallocate`

Triggered when a room goes under maintenance or a faculty member becomes unavailable. It automatically swaps the room or schedules another qualified subject without generic substitutions.

#### Response `200 OK`:
```json
{
  "ok": true,
  "action": "ROOM_SWAPPED",
  "message": "Reallocated to Room 102."
}
```

---

### 4.7 Resetting Auto-Generated Timetable
`POST /api/v1/timetable/clear`

Wipes auto-generated entries while **preserving** manual allotments.

#### Request Payload:
```json
{
  "section_ids": [7, 8],
  "mode": "AUTO"
}
```
*(To clear across all courses, omit `section_ids` and pass `{"mode": "AUTO"}`)*

#### Response `200 OK`:
```json
{
  "ok": true,
  "deleted_count": 40
}
```

---

### 4.8 Master Data Bulk Sync Endpoints

#### A. Sync Rooms
`POST /api/v1/sync/rooms`
```json
{
  "rooms": [
    {
      "room_code": "G01",
      "building": "Main Block",
      "floor": "Ground Floor",
      "room_type": "CLASSROOM",
      "capacity": 70,
      "status": "ACTIVE"
    },
    {
      "room_code": "104",
      "building": "Main Block",
      "floor": "First Floor",
      "room_type": "COMPUTER_LAB",
      "capacity": 60,
      "status": "ACTIVE"
    }
  ]
}
```

#### B. Sync Faculty & Qualifications
`POST /api/v1/sync/faculty`
```json
{
  "faculty": [
    {
      "faculty_code": "MKC",
      "full_name": "Dr. Mahesh Kumar Chaubey",
      "department": "Computer Science",
      "max_lectures_per_day": 4,
      "qualified_subject_codes": ["JP", "LAB ORACLE", "PY-301"]
    }
  ]
}
```

#### C. Sync Academic Events (Holidays & Exams)
`POST /api/v1/sync/academic-events`
```json
{
  "replace": false,
  "events": [
    {
      "event_type": "HOLIDAY",
      "title": "Guru Nanak Jayanti",
      "start_date": "2026-11-24",
      "end_date": "2026-11-24"
    },
    {
      "event_type": "EXAM",
      "title": "Winter Semester End Examinations",
      "start_date": "2026-12-14",
      "end_date": "2026-12-23"
    }
  ]
}
```

---

### 4.9 Full Timetable Export
`GET /api/v1/export/timetable`

Query params: `course_code` (optional), `validity_type` (optional).

#### Response `200 OK`:
```json
{
  "count": 180,
  "generated_at": "2026-11-13T18:18:00+00:00",
  "timetable": [
    {
      "id": 1,
      "allocation_category": "COURSE",
      "course_code": "BBA",
      "course_name": "Bachelor of Business Administration",
      "year_number": 1,
      "shift": "MORNING",
      "section_code": "M1",
      "day_of_week": "Monday",
      "slot_index": 1,
      "start_time": "09:10",
      "end_time": "10:05",
      "subject_code": "34136",
      "subject_name": "Principles of Management",
      "requires_lab": 0,
      "faculty_code": "AK",
      "faculty_name": "Dr. Ajay Kumar",
      "room_code": "G01",
      "room_type": "CLASSROOM",
      "assignment_mode": "MANUAL",
      "validity_type": "LIFETIME",
      "effective_from": null,
      "effective_to": null,
      "reason": "Primary class allotment"
    }
  ]
}
```

---

## 💻 5. Integration Code Snippets

### 5.1 Python (Django / FastAPI / Flask / Requests)

```python
import requests

TIMETABLE_API_BASE = "http://localhost:5000/api/v1"
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": "YOUR_SECRET_API_KEY",  # Optional if configured
}

def allot_room_for_lecture(course, year, shift, section, day, slot, subject, faculty, room, reason):
    """Call the timetable engine using natural ERP codes."""
    url = f"{TIMETABLE_API_BASE}/timetable/manual"
    payload = {
        "allocation_category": "COURSE",
        "course_code": course,
        "year_number": year,
        "shift": shift,
        "section_code": section,
        "day_of_week": day,
        "slot_index": slot,
        "subject_code": subject,
        "faculty_code": faculty,
        "room_code": room,
        "validity_type": "LIFETIME",
        "reason": reason,
    }
    
    response = requests.post(url, json=payload, headers=HEADERS)
    if response.status_code == 201:
        print("Success:", response.json())
        return response.json()["entry_id"]
    elif response.status_code == 409:
        print("Conflict detected by engine:", response.json()["error"])
        raise ValueError(response.json()["error"])
    else:
        response.raise_for_status()

# Example Call:
# allot_room_for_lecture("BBA", 1, "MORNING", "M1", "Monday", 1, "34136", "AK", "G01", "ERP Schedule Sync")
```

---

### 5.2 Node.js / Express / TypeScript (Axios or Fetch)

```typescript
import axios from 'axios';

const client = axios.create({
  baseURL: 'http://localhost:5000/api/v1',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': process.env.TIMETABLE_API_KEY || '',
  },
});

// Run smart automation for an entire course
export async function autoGenerateSchedule(courseCode: string, yearNumber?: number) {
  try {
    const response = await client.post('/timetable/automate', {
      course_code: courseCode,
      year_number: yearNumber,
      weekdays: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
      validity_type: 'LIFETIME',
      overwrite_auto: true,
    });
    console.log(`Generated ${response.data.created_count} conflict-free slots.`);
    return response.data;
  } catch (error: any) {
    if (error.response?.status === 409) {
      console.error('Booking conflict:', error.response.data.error);
    }
    throw error;
  }
}

// Book Auditorium for a Cultural Event
export async function bookAuditorium(eventName: string, date: string, startTime: string, endTime: string) {
  const response = await client.post('/timetable/manual', {
    allocation_category: 'CLUB_EXTRACURRICULAR',
    day_of_week: new Date(date).toLocaleDateString('en-US', { weekday: 'long' }),
    start_time: startTime,
    end_time: endTime,
    room_code: 'AUDITORIUM',
    validity_type: 'DATED',
    effective_from: date,
    effective_to: date,
    reason: eventName,
  });
  return response.data;
}
```

---

### 5.3 PHP / Laravel

```php
<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;

class TimetableService
{
    protected string $baseUrl;
    protected ?string $apiKey;

    public function __construct()
    {
        $this->baseUrl = config('services.timetable.url', 'http://localhost:5000/api/v1');
        $this->apiKey = config('services.timetable.key');
    }

    public function getStudentTimetable(int $studentId): array
    {
        $response = Http::withHeaders([
            'X-API-Key' => $this->apiKey,
        ])->get("{$this->baseUrl}/portal/student/{$studentId}");

        if ($response->successful()) {
            return $response->json();
        }

        throw new \Exception("Failed to fetch student timetable: " . $response->body());
    }

    public function bookCoCurricularVenue(string $society, string $roomCode, string $day, string $start, string $end, ?string $date = null)
    {
        return Http::withHeaders([
            'X-API-Key' => $this->apiKey,
        ])->post("{$this->baseUrl}/timetable/manual", [
            'allocation_category' => 'CLUB_EXTRACURRICULAR',
            'room_code' => $roomCode,
            'day_of_week' => $day,
            'start_time' => $start,
            'end_time' => $end,
            'validity_type' => $date ? 'DATED' : 'LIFETIME',
            'effective_from' => $date,
            'effective_to' => $date,
            'reason' => $society,
        ]);
    }
}
```

---

### 5.4 Frontend Direct Call (Vanilla JS / React / Angular)

```javascript
async function checkRoomStatus(day, shift, slot) {
  const res = await fetch(
    `http://localhost:5000/api/v1/rooms/availability?day=${day}&shift=${shift}&slot_index=${slot}`,
    {
      headers: {
        'Accept': 'application/json',
      }
    }
  );
  const data = await res.json();
  
  // Find which rooms are free
  const freeRooms = data.rooms.filter(r => r.availability === 'FREE');
  console.log(`Available rooms for Slot ${slot}:`, freeRooms.map(r => r.room_code));
  return freeRooms;
}
```

---

## ⚠️ 6. Error Handling & Conflict Resolution Contract

When an allotment cannot be made due to a conflict or clause violation, the API responds with **`HTTP 409 Conflict`** and a structured JSON payload:

```json
{
  "error": "Human-readable explanation of why the action failed",
  "conflicts": [
    "Specific clause 1 detail",
    "Specific clause 2 detail"
  ]
}
```

### Common Conflict Scenarios
| Clause | Cause | Solution for Calling System |
|---|---|---|
| **Room Double-Booking** | The room is already occupied during that time slot or date. | Query `/api/v1/rooms/availability` to choose another free room. |
| **Holiday / Exam Clause** | Allotment date falls inside an academic event (`HOLIDAY` or `EXAM`). | Pick a non-holiday date or reschedule outside the exam window. |
| **Teacher Unavailability** | Faculty member has an approved leave window recorded. | Assign an alternate qualified teacher or choose another slot. |
| **Teacher Repeat Clause** | The same teacher is assigned to the same class in adjacent back-to-back slots. | Insert a break or swap with another subject. |
| **Teacher Qualification Lock** | Faculty member is not registered in `teacher_subjects` for that subject. | Call `/api/v1/teacher-subjects` to map qualification or choose an assigned teacher. |
| **Lab Requirement** | Subject requires a computer lab, but room type is `CLASSROOM`. | Pick room `G04`, `104`, or `107` (`COMPUTER_LAB`). |
| **Co-Curricular Venue Lock** | Regular course attempted to book `AMPHITHEATER` or `AUDITORIUM`. | Use standard classrooms for courses; reserve amphitheater/auditorium for co-curricular events. |

---

## ⚙️ 7. Environment Variables & Production Deployment

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | Port on which the Flask microservice listens. |
| `ERP_API_KEY` | *(empty / disabled)* | If set, enforces `X-API-Key` or `Authorization: Bearer <key>` on all API endpoints. |
| `FLASK_ENV` | `production` | Set to `development` for local debug reload, `production` for production servers. |

### Running as a Background Microservice (Gunicorn / Systemd / Docker)

**Gunicorn (Linux / macOS / Production)**:
```bash
pip install gunicorn
ERP_API_KEY="your-strong-production-key" gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

**Docker / Container**:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
ENV PORT=5000
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```
