const state = {
  courses: [],
  sections: [],
  rooms: [],
  faculty: [],
  subjects: [],
  teacher_subjects: [],
  teacher_availability: [],
  academic_events: [],
  weekdays: [],
  slots: { MORNING: [], AFTERNOON: [] },
  allEntries: [],
  roomMatrix: [],
};

const $ = (id) => document.getElementById(id);

function showAlert(msg, type = "success") {
  const el = $("alert-banner");
  el.textContent = msg;
  el.className = `alert ${type}`;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (type === "success") {
    setTimeout(() => el.classList.add("hidden"), 5000);
  }
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function getSelectedCourse() {
  const cid = Number($("sel-course").value);
  return state.courses.find((c) => c.id === cid);
}

function getSelectedSection() {
  const sid = Number($("sel-section").value);
  return state.sections.find((s) => s.id === sid);
}

function formatValidity(entry) {
  if (entry.validity_type === "LIFETIME") return "Lifetime";
  if (entry.effective_from === entry.effective_to) return entry.effective_from || "Dated";
  return `${entry.effective_from} → ${entry.effective_to}`;
}

async function loadAll() {
  const [boot, tt] = await Promise.all([
    api("/api/v1/bootstrap"),
    api("/api/v1/timetable"),
  ]);
  Object.assign(state, boot);
  state.allEntries = tt.entries;
  populateStaticDropdowns();
  onCourseChange();
  renderMasterTable();
  renderRoomsTable();
  renderSubjectsTable();
  renderClausesTab();
  await refreshRoomInspector();
  await refreshCoCurricularRoomAvailability();
  await loadTeacherPortal();
  onStudentCourseChange();
}

function populateStaticDropdowns() {
  const prevCourse = $("sel-course").value;
  $("sel-course").innerHTML = state.courses
    .map((c) => `<option value="${c.id}">${c.code} — ${c.name}</option>`)
    .join("");
  if (prevCourse && state.courses.some((c) => String(c.id) === prevCourse)) {
    $("sel-course").value = prevCourse;
  }

  const dayOpts = state.weekdays.map((d) => `<option value="${d}">${d}</option>`).join("");
  $("man-day").innerHTML = dayOpts;
  $("insp-day").innerHTML = dayOpts;
  $("co-day").innerHTML = dayOpts;

  const facOpts =
    `<option value="">-- Unassigned --</option>` +
    state.faculty
      .map((f) => `<option value="${f.id}">${f.faculty_code} — ${f.full_name}</option>`)
      .join("");
  $("man-faculty").innerHTML = facOpts;
  $("sub-faculty").innerHTML = facOpts;
  $("co-faculty").innerHTML =
    `<option value="">-- Optional Teacher In-Charge --</option>` +
    state.faculty
      .map((f) => `<option value="${f.id}">${f.faculty_code} — ${f.full_name}</option>`)
      .join("");

  const facReqOpts = state.faculty
    .map((f) => `<option value="${f.id}">${f.faculty_code} — ${f.full_name}</option>`)
    .join("");
  $("unav-faculty").innerHTML = facReqOpts;
  $("qual-faculty").innerHTML = facReqOpts;
  $("tp-faculty").innerHTML = facReqOpts;

  const prevSpCourse = $("sp-course").value;
  $("sp-course").innerHTML = state.courses
    .map((c) => `<option value="${c.id}">${c.code} — ${c.name}</option>`)
    .join("");
  if (prevSpCourse && state.courses.some((c) => String(c.id) === prevSpCourse)) {
    $("sp-course").value = prevSpCourse;
  }

  $("qual-subject").innerHTML = state.subjects
    .map((s) => `<option value="${s.id}">${s.course_code} Y${s.year_number} • ${s.subject_code} — ${s.subject_name}</option>`)
    .join("");

  const activeRooms = state.rooms.filter((r) => r.status === "ACTIVE");
  $("sel-primary-room").innerHTML =
    `<option value="">-- None (Auto pick room) --</option>` +
    activeRooms
      .map((r) => `<option value="${r.id}">${r.room_code} (${r.room_type}, ${r.floor}, Cap ${r.capacity})</option>`)
      .join("");

  $("filter-course").innerHTML =
    `<option value="">All Courses &amp; Clubs</option>` +
    `<option value="CLUB_EXTRACURRICULAR">Clubs &amp; Extracurricular</option>` +
    state.courses.map((c) => `<option value="${c.code}">${c.code}</option>`).join("");
  $("filter-room").innerHTML =
    `<option value="">All Rooms</option>` +
    state.rooms.map((r) => `<option value="${r.room_code}">${r.room_code}</option>`).join("");

  const currCourseOpts = state.courses
    .map((c) => `<option value="${c.id}">${c.code} — ${c.name}</option>`)
    .join("");
  $("sub-course").innerHTML = currCourseOpts;
  $("curr-filter-course").innerHTML = `<option value="">All Courses</option>` + currCourseOpts;
  updateCurriculumYearDropdown("sub-course", "sub-year", false);
  updateCurriculumYearDropdown("curr-filter-course", "curr-filter-year", true);
}

function updateCurriculumYearDropdown(courseSelectId, yearSelectId, includeAll) {
  const cid = Number($(courseSelectId).value);
  const course = state.courses.find((c) => c.id === cid);
  const maxYears = course ? course.duration_years : 5;
  let html = includeAll ? `<option value="">All Years</option>` : "";
  for (let y = 1; y <= maxYears; y++) {
    html += `<option value="${y}">Year ${y}</option>`;
  }
  $(yearSelectId).innerHTML = html;
}

function onCourseChange() {
  const course = getSelectedCourse();
  if (!course) return;

  const prevYear = $("sel-year").value;
  let yearHtml = "";
  for (let y = 1; y <= course.duration_years; y++) {
    yearHtml += `<option value="${y}">Year ${y}</option>`;
  }
  $("sel-year").innerHTML = yearHtml;
  if (prevYear && Number(prevYear) <= course.duration_years) {
    $("sel-year").value = prevYear;
  }

  const shifts = course.shifts.split(",");
  const prevShift = $("sel-shift").value;
  $("sel-shift").innerHTML = shifts.map((sh) => `<option value="${sh}">${sh}</option>`).join("");
  if (prevShift && shifts.includes(prevShift)) {
    $("sel-shift").value = prevShift;
  }

  onYearOrShiftChange();
}

function onYearOrShiftChange() {
  const course = getSelectedCourse();
  const year = Number($("sel-year").value);
  const shift = $("sel-shift").value;
  if (!course) return;

  const matchingSections = state.sections.filter(
    (s) => s.course_id === course.id && s.year_number === year && s.shift === shift
  );

  const isGradeWise =
    matchingSections.length === 1 && matchingSections[0].section_code === "Grade-Wise";
  $("field-section").classList.toggle("hidden", isGradeWise);

  const prevSec = $("sel-section").value;
  $("sel-section").innerHTML = matchingSections
    .map((s) => `<option value="${s.id}">Section ${s.section_code}</option>`)
    .join("");
  if (prevSec && matchingSections.some((s) => String(s.id) === prevSec)) {
    $("sel-section").value = prevSec;
  }

  const matchingSubjects = state.subjects.filter(
    (sub) => sub.course_id === course.id && sub.year_number === year
  );
  $("man-subject").innerHTML = matchingSubjects.length
    ? matchingSubjects
        .map(
          (sub) =>
            `<option value="${sub.id}" data-faculty="${sub.faculty_id || ""}">
              ${sub.subject_code} — ${sub.subject_name}${sub.requires_lab ? " [LAB]" : ""}
            </option>`
        )
        .join("")
    : `<option value="">No subjects for this year</option>`;

  syncSubjectFaculty();
  onSectionChange();
}

function isComputerSubject(sub, courseCode) {
  if (sub.requires_lab) return true;
  if (courseCode !== "BCA") return false;
  const name = (sub.subject_name || "").toLowerCase();
  const code = (sub.subject_code || "").toLowerCase();
  const nonComp = ["statistics", "stat", "management", "sum", "yoga", "digital electronics", "environmental", "economics"];
  return !nonComp.some((k) => name.includes(k) || code.includes(k));
}

function isMootCourtSubject(sub, courseCode) {
  if (courseCode !== "LLB") return false;
  const name = (sub.subject_name || "").toLowerCase();
  return name.includes("moot") || name.includes("trial advocacy") || name.includes("drafting");
}

function syncSubjectFaculty() {
  const sel = $("man-subject");
  const opt = sel.options[sel.selectedIndex];
  if (opt && opt.dataset.faculty) {
    $("man-faculty").value = opt.dataset.faculty;
  }
  const subId = Number(sel.value);
  const sub = state.subjects.find((s) => s.id === subId);
  const sec = getSelectedSection();
  const course = getSelectedCourse();
  if (sub && state.roomMatrix && state.roomMatrix.length) {
    const cCode = course ? course.code : "";
    if (isMootCourtSubject(sub, cCode)) {
      const mootRoom = state.roomMatrix.find((r) => r.room_type === "MOOT_COURT" && r.availability === "FREE")
        || state.roomMatrix.find((r) => r.room_type === "MOOT_COURT");
      if (mootRoom) {
        $("man-room").value = String(mootRoom.id);
      }
    } else if (isComputerSubject(sub, cCode)) {
      const primLab = (sec && sec.primary_room_id)
        ? state.roomMatrix.find((r) => r.id === sec.primary_room_id && r.room_type === "COMPUTER_LAB" && r.availability === "FREE")
        : null;
      const freeLab = state.roomMatrix.find((r) => r.room_type === "COMPUTER_LAB" && r.availability === "FREE");
      const anyLab = state.roomMatrix.find((r) => r.room_type === "COMPUTER_LAB");
      const targetLab = primLab || freeLab || anyLab;
      if (targetLab) {
        $("man-room").value = String(targetLab.id);
      }
    } else {
      const primCls = (sec && sec.primary_room_id)
        ? state.roomMatrix.find((r) => r.id === sec.primary_room_id && r.room_type === "CLASSROOM" && r.availability === "FREE")
        : null;
      const freeCls = state.roomMatrix.find((r) => r.room_type === "CLASSROOM" && r.availability === "FREE");
      const anyCls = state.roomMatrix.find((r) => r.room_type === "CLASSROOM");
      const targetCls = primCls || freeCls || anyCls;
      if (targetCls) {
        $("man-room").value = String(targetCls.id);
      }
    }
    updateRoomStatusHint();
  }
}

async function onSectionChange() {
  const sec = getSelectedSection();
  const course = getSelectedCourse();
  if (!sec || !course) return;

  $("sel-primary-room").value = sec.primary_room_id ? String(sec.primary_room_id) : "";

  const shiftSlots = state.slots[sec.shift] || [];
  $("man-slot").innerHTML = shiftSlots
    .map((sl) => `<option value="${sl.slot_index}">Slot ${sl.slot_index} (${sl.start_time}–${sl.end_time})</option>`)
    .join("");

  const subCount = state.subjects.filter(
    (s) => s.course_id === course.id && s.year_number === sec.year_number
  ).length;
  const secLabel = sec.section_code === "Grade-Wise" ? "" : ` • Sec ${sec.section_code}`;
  const secTitle = sec.section_code === "Grade-Wise" ? "" : ` • Section ${sec.section_code}`;
  $("course-meta-strip").innerHTML = `
    <span><strong>Course:</strong> ${course.name} (${course.duration_years} Yr)</span>
    <span><strong>Shifts:</strong> ${course.shifts.replace(",", " & ")}</span>
    <span><strong>Selected:</strong> Year ${sec.year_number} • ${sec.shift}${secLabel}</span>
    <span><strong>Primary Class:</strong> ${sec.primary_room_code || "Not Set"}</span>
    <span><strong>Subjects Configured:</strong> ${subCount}</span>
  `;

  $("grid-title").textContent = `${course.code} — Year ${sec.year_number} (${sec.shift})${secTitle}`;
  $("grid-subtitle").textContent = sec.primary_room_code
    ? `Primary Class: Room ${sec.primary_room_code}`
    : "No Primary Class set yet (automation picks any free compatible room)";

  renderTimetableGrid();
  await refreshManualRoomAvailability();
}

function getManualShift() {
  const sec = getSelectedSection();
  return sec ? sec.shift : "MORNING";
}

function populateManualSlots() {
  const shift = getManualShift();
  const shiftSlots = state.slots[shift] || [];
  const prev = $("man-slot").value;
  $("man-slot").innerHTML = shiftSlots
    .map((sl) => `<option value="${sl.slot_index}">Slot ${sl.slot_index} (${sl.start_time}–${sl.end_time})</option>`)
    .join("");
  if (prev && shiftSlots.some((s) => String(s.slot_index) === prev)) {
    $("man-slot").value = prev;
  }
}

async function refreshManualRoomAvailability() {
  const shift = getManualShift();
  const sec = getSelectedSection();
  const day = $("man-day").value;
  const slot = $("man-slot").value || 1;
  const targetDate = $("man-validity").value === "DATED" ? $("man-from").value : "";
  const url =
    `/api/v1/rooms/availability?day=${encodeURIComponent(day)}&shift=${encodeURIComponent(shift)}&slot_index=${slot}` +
    (targetDate ? `&target_date=${encodeURIComponent(targetDate)}` : "");
  const data = await api(url);
  // Include all rooms (Classroom, Computer Lab, Moot Court, Auditorium, Amphitheater)
  state.roomMatrix = data.rooms;

  const prevRoom = $("man-room").value;
  $("man-room").innerHTML = state.roomMatrix
    .map((r) => {
      let tag = "FREE";
      if (r.availability === "BOOKED") {
        const b = r.booking;
        const val = b.validity_type === "LIFETIME" ? "Lifetime" : `${b.effective_from}..${b.effective_to}`;
        const owner =
          b.allocation_category === "CLUB_EXTRACURRICULAR"
            ? `Co-Curricular: ${b.custom_title}`
            : `${b.course_code} Y${b.year_number}-${b.section_code}`;
        tag = `BOOKED by ${owner} [${val}]`;
      } else if (r.availability === "MAINTENANCE") {
        tag = "MAINTENANCE";
      } else if (r.primary_for) {
        const p = r.primary_for;
        tag = `FREE (Primary: ${p.course_code} Y${p.year_number}-${p.section_code})`;
      }
      return `<option value="${r.id}">${r.room_code} (${r.room_type}) — ${tag}</option>`;
    })
    .join("");

  if (prevRoom && state.roomMatrix.some((r) => String(r.id) === prevRoom)) {
    $("man-room").value = prevRoom;
  } else if (sec && sec.primary_room_id) {
    $("man-room").value = String(sec.primary_room_id);
  }
  updateRoomStatusHint();
}

let coRoomMatrix = [];
async function refreshCoCurricularRoomAvailability() {
  const day = $("co-day").value || "Monday";
  const startTime = $("co-start").value || "09:00";
  const endTime = $("co-end").value || "10:00";
  const targetDate = $("co-validity").value === "DATED" ? $("co-from").value : "";
  const url =
    `/api/v1/rooms/availability?day=${encodeURIComponent(day)}&start_time=${encodeURIComponent(startTime)}&end_time=${encodeURIComponent(endTime)}` +
    (targetDate ? `&target_date=${encodeURIComponent(targetDate)}` : "");
  const data = await api(url);
  // Put Amphitheater & Auditorium first
  coRoomMatrix = [...data.rooms].sort((a, b) => {
    const aEvent = a.room_type === "AMPHITHEATER" || a.room_type === "AUDITORIUM" ? 0 : 1;
    const bEvent = b.room_type === "AMPHITHEATER" || b.room_type === "AUDITORIUM" ? 0 : 1;
    if (aEvent !== bEvent) return aEvent - bEvent;
    return a.room_code.localeCompare(b.room_code);
  });

  const prev = $("co-room").value;
  $("co-room").innerHTML = coRoomMatrix
    .map((r) => {
      let tag = "FREE";
      if (r.availability === "BOOKED") {
        const b = r.booking;
        const owner =
          b.allocation_category === "CLUB_EXTRACURRICULAR"
            ? b.custom_title
            : `${b.course_code} Y${b.year_number}`;
        tag = `BOOKED (${owner})`;
      } else if (r.availability === "MAINTENANCE") {
        tag = "MAINTENANCE";
      }
      return `<option value="${r.id}">${r.room_code} (${r.room_type}, Cap ${r.capacity}) — ${tag}</option>`;
    })
    .join("");
  if (prev && coRoomMatrix.some((r) => String(r.id) === prev)) {
    $("co-room").value = prev;
  }
  updateCoRoomHint();
}

function updateCoRoomHint() {
  const rid = Number($("co-room").value);
  const rm = coRoomMatrix.find((r) => r.id === rid);
  const hint = $("co-room-hint");
  if (!rm) {
    hint.textContent = "";
    hint.className = "room-hint";
    return;
  }
  if (rm.availability === "BOOKED") {
    const b = rm.booking;
    hint.className = "room-hint booked";
    hint.textContent = `Blocked: ${rm.room_code} is already booked (${b.start_time}–${b.end_time})${b.reason ? ` — ${b.reason}` : ""}.`;
  } else if (rm.availability === "MAINTENANCE") {
    hint.className = "room-hint booked";
    hint.textContent = `Unavailable: ${rm.room_code} is under MAINTENANCE.`;
  } else {
    hint.className = "room-hint free";
    hint.textContent = `Available: ${rm.room_code} (${rm.building}, Cap ${rm.capacity}) is FREE for this timing.`;
  }
}

function updateRoomStatusHint() {
  const rid = Number($("man-room").value);
  const rm = state.roomMatrix.find((r) => r.id === rid);
  const hint = $("room-status-hint");
  if (!rm) {
    hint.textContent = "";
    hint.className = "room-hint";
    return;
  }
  const subId = Number($("man-subject").value);
  const sub = state.subjects.find((s) => s.id === subId);
  const sec = getSelectedSection();
  const course = getSelectedCourse();
  const cCode = course ? course.code : "";

  if (rm.availability === "BOOKED") {
    const b = rm.booking;
    const owner =
      b.allocation_category === "CLUB_EXTRACURRICULAR"
        ? `Club/Extracurricular '${b.custom_title}'`
        : `${b.course_code} Year ${b.year_number} Sec ${b.section_code} (${b.subject_name})`;
    hint.className = "room-hint booked";
    hint.textContent = `Blocked: ${rm.room_code} is booked by ${owner}${b.reason ? ` — Reason: ${b.reason}` : ""}.`;
  } else if (rm.availability === "MAINTENANCE") {
    hint.className = "room-hint booked";
    hint.textContent = `Unavailable: ${rm.room_code} is under MAINTENANCE.`;
  } else {
    const isPrimary = sec && sec.primary_room_id === rm.id;
    let badge = "";
    if (isPrimary) {
      badge = " [Dedicated Primary Room]";
    } else if (sub && isMootCourtSubject(sub, cCode) && rm.room_type === "MOOT_COURT") {
      badge = " [Dedicated Moot Court]";
    } else if (sub && isComputerSubject(sub, cCode) && rm.room_type === "COMPUTER_LAB") {
      badge = " [Computer Lab for IT/CS Subject]";
    } else if (rm.room_type === "AUDITORIUM" || rm.room_type === "AMPHITHEATER") {
      badge = " [Auditorium / Amphitheater]";
    }
    hint.className = "room-hint free";
    hint.textContent = `Available: Room ${rm.room_code} (${rm.room_type}, ${rm.floor}, Cap ${rm.capacity}) is FREE${badge}.`;
  }
}

function renderTimetableGrid() {
  const sec = getSelectedSection();
  if (!sec) return;
  const days = state.weekdays.slice(0, 6);
  const slots = state.slots[sec.shift] || [];
  const filterDate = $("grid-date-filter").value;

  const entries = state.allEntries.filter((e) => {
    if (e.section_id !== sec.id) return false;
    if (!filterDate) return true;
    if (e.validity_type === "LIFETIME") return true;
    return e.effective_from <= filterDate && filterDate <= e.effective_to;
  });

  const thead = $("timetable-grid").querySelector("thead");
  thead.innerHTML = `<tr><th>Time / Slot</th>${days.map((d) => `<th>${d}</th>`).join("")}</tr>`;

  const tbody = $("timetable-grid").querySelector("tbody");
  let html = "";

  for (const sl of slots) {
    html += `<tr><td class="time-col">Slot ${sl.slot_index}<br><span class="muted">${sl.start_time}–${sl.end_time}</span></td>`;
    for (const day of days) {
      const cellEntries = entries.filter((e) => e.day_of_week === day && e.slot_index === sl.slot_index);
      if (cellEntries.length) {
        html += `<td class="slot-cell">`;
        for (const entry of cellEntries) {
          const modeCls = entry.assignment_mode === "MANUAL" ? "manual" : "auto";
          const badgeCls = entry.assignment_mode === "MANUAL" ? "badge-manual" : "badge-auto";
          const modeTxt = entry.assignment_mode === "MANUAL" ? "Self" : "Auto";
          const valBadge = entry.validity_type === "LIFETIME" ? "badge-lifetime" : "badge-dated";
          html += `
            <div class="slot-card ${modeCls}" style="margin-bottom:4px;">
              <div class="slot-card-top">
                <div>
                  <span class="badge ${badgeCls}">${modeTxt}</span>
                  <span class="badge ${valBadge}">${formatValidity(entry)}</span>
                </div>
                <div class="slot-actions">
                  <button class="btn-reallocate" data-reallocate-entry="${entry.id}" title="Dynamic Reallocation (No generic substitute)">&#8635;</button>
                  <button class="btn-release" data-delete-entry="${entry.id}" title="Release this slot">&times;</button>
                </div>
              </div>
              <div class="slot-sub">${entry.subject_code} — ${entry.subject_name}</div>
              <div class="slot-meta">Room: <strong>${entry.room_code}</strong> • ${entry.faculty_code || "TBA"}</div>
              ${entry.reason ? `<div class="slot-reason">${entry.reason}</div>` : ""}
            </div>`;
        }
        html += `</td>`;
      } else {
        html += `
          <td class="slot-cell">
            <div class="slot-empty">
              <button class="btn-slot-add" data-pick-day="${day}" data-pick-slot="${sl.slot_index}">+ Allot</button>
            </div>
          </td>`;
      }
    }
    html += "</tr>";
    if (sl.slot_index === 2) {
      html += `<tr class="break-row"><td colspan="${days.length + 1}">SHORT BREAK</td></tr>`;
    }
  }
  tbody.innerHTML = html;
}

function renderMasterTable() {
  const cFilter = $("filter-course").value;
  const rFilter = $("filter-room").value;
  const mFilter = $("filter-mode").value;
  const vFilter = $("filter-validity").value;
  const search = $("filter-search").value.trim().toLowerCase();

  const rows = state.allEntries.filter((e) => {
    if (cFilter === "CLUB_EXTRACURRICULAR") {
      if (e.allocation_category !== "CLUB_EXTRACURRICULAR") return false;
    } else if (cFilter && e.course_code !== cFilter) {
      return false;
    }
    if (rFilter && e.room_code !== rFilter) return false;
    if (mFilter && e.assignment_mode !== mFilter) return false;
    if (vFilter && e.validity_type !== vFilter) return false;
    if (search) {
      const hay = `${e.course_code || ""} ${e.custom_title || ""} ${e.subject_code || ""} ${e.subject_name || ""} ${e.faculty_name || ""} ${e.room_code} ${e.reason}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  const tbody = $("master-table").querySelector("tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="13" class="muted" style="text-align:center;padding:20px;">No timetable allotments found matching your filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map(
      (e) => {
        const isClub = e.allocation_category === "CLUB_EXTRACURRICULAR";
        const courseCol = isClub
          ? `<span class="badge badge-manual">CLUB / SOC</span>`
          : `<strong>${e.course_code}</strong>`;
        const yearCol = isClub ? "—" : `Y${e.year_number}`;
        const secCol = isClub || e.section_code === "Grade-Wise" ? "—" : e.section_code;
        const subCol = isClub ? `<strong>${e.custom_title}</strong>` : `${e.subject_code} — ${e.subject_name}`;
        const slotTxt = e.slot_index === 0 ? `Custom (${e.start_time}–${e.end_time})` : `Slot ${e.slot_index} (${e.start_time}–${e.end_time})`;
        return `
      <tr>
        <td>${courseCol}</td>
        <td>${yearCol}</td>
        <td>${e.shift}</td>
        <td>${secCol}</td>
        <td>${e.day_of_week}</td>
        <td>${slotTxt}</td>
        <td><span class="badge ${e.validity_type === "LIFETIME" ? "badge-lifetime" : "badge-dated"}">${formatValidity(e)}</span></td>
        <td>${subCol}</td>
        <td>${e.faculty_code ? `${e.faculty_code} (${e.faculty_name})` : "—"}</td>
        <td><strong>${e.room_code}</strong></td>
        <td><span class="badge ${e.assignment_mode === "MANUAL" ? "badge-manual" : "badge-auto"}">${e.assignment_mode === "MANUAL" ? "Self-Assigned" : "Automated"}</span></td>
        <td>${e.reason || "—"}</td>
        <td>
          ${isClub ? "" : `<button class="btn btn-secondary btn-sm" data-reallocate-entry="${e.id}" title="Reallocate">Realloc</button>`}
          <button class="btn btn-danger-outline btn-sm" data-delete-entry="${e.id}">Release</button>
        </td>
      </tr>`;
      }
    )
    .join("");
}

function renderRoomsTable() {
  const tbody = $("rooms-table").querySelector("tbody");
  tbody.innerHTML = state.rooms
    .map(
      (r) => `
      <tr>
        <td><strong>${r.room_code}</strong></td>
        <td>${r.building}</td>
        <td>${r.floor}</td>
        <td>${r.room_type}</td>
        <td>${r.capacity}</td>
        <td><span class="badge ${r.status === "ACTIVE" ? "badge-free" : "badge-booked"}">${r.status}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" data-toggle-room="${r.id}" data-next-status="${r.status === "ACTIVE" ? "MAINTENANCE" : "ACTIVE"}">
            ${r.status === "ACTIVE" ? "Set Maintenance" : "Set Active"}
          </button>
          <button class="btn btn-danger-outline btn-sm" data-delete-room="${r.id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");
}

async function refreshRoomInspector() {
  const day = $("insp-day").value || "Monday";
  const shift = $("insp-shift").value || "MORNING";
  const slot = $("insp-slot").value || "1";
  const targetDate = $("insp-date").value || "";
  const url =
    `/api/v1/rooms/availability?day=${encodeURIComponent(day)}&shift=${encodeURIComponent(shift)}&slot_index=${slot}` +
    (targetDate ? `&target_date=${encodeURIComponent(targetDate)}` : "");
  const data = await api(url);
  $("room-inspector-grid").innerHTML = data.rooms
    .map((r) => {
      let detail = `${r.building} • Cap ${r.capacity}`;
      if (r.availability === "BOOKED") {
        const b = r.booking;
        detail =
          b.allocation_category === "CLUB_EXTRACURRICULAR"
            ? `Booked: Club (${b.custom_title})`
            : `Booked: ${b.course_code} Y${b.year_number} ${b.section_code} (${b.subject_code})`;
      } else if (r.availability === "MAINTENANCE") {
        detail = "Under Maintenance";
      }
      return `
        <div class="room-pill ${r.availability}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <strong>${r.room_code}</strong>
            <span class="badge ${r.availability === "FREE" ? "badge-free" : "badge-booked"}">${r.availability}</span>
          </div>
          <div>${detail}</div>
        </div>`;
    })
    .join("");
}

function renderSubjectsTable() {
  const cid = $("curr-filter-course").value;
  const yr = $("curr-filter-year").value;
  const rows = state.subjects.filter((s) => {
    if (cid && String(s.course_id) !== cid) return false;
    if (yr && String(s.year_number) !== yr) return false;
    return true;
  });

  const tbody = $("subjects-table").querySelector("tbody");
  tbody.innerHTML = rows
    .map(
      (s) => `
      <tr>
        <td><strong>${s.course_code}</strong></td>
        <td>Year ${s.year_number}</td>
        <td>${s.subject_code}</td>
        <td>${s.subject_name}</td>
        <td>${s.requires_lab ? "Lab (Computer)" : "Theory"}</td>
        <td>${s.lectures_per_week}</td>
        <td>${s.faculty_code ? `${s.faculty_code} — ${s.faculty_name}` : "Unassigned"}</td>
        <td><button class="btn btn-danger-outline btn-sm" data-delete-subject="${s.id}">Remove</button></td>
      </tr>`
    )
    .join("");
}

function renderClausesTab() {
  $("unavail-table").querySelector("tbody").innerHTML = state.teacher_availability.length
    ? state.teacher_availability
        .map(
          (u) => `
        <tr>
          <td><strong>${u.faculty_code}</strong> — ${u.faculty_name}</td>
          <td>${u.start_date} → ${u.end_date}</td>
          <td>${u.shift}</td>
          <td>${u.reason}</td>
          <td><button class="btn btn-danger-outline btn-sm" data-delete-unavail="${u.id}">Clear</button></td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="5" class="muted">No teacher unavailability windows set.</td></tr>`;

  $("events-table").querySelector("tbody").innerHTML = state.academic_events.length
    ? state.academic_events
        .map(
          (ev) => `
        <tr>
          <td><span class="badge ${ev.event_type === "EXAM" ? "badge-booked" : "badge-manual"}">${ev.event_type}</span></td>
          <td>${ev.title}</td>
          <td>${ev.start_date} → ${ev.end_date}</td>
          <td><button class="btn btn-danger-outline btn-sm" data-delete-event="${ev.id}">Remove</button></td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="4" class="muted">No holiday/exam events configured.</td></tr>`;

  $("qual-table").querySelector("tbody").innerHTML = state.teacher_subjects
    .map(
      (q) => `
      <tr>
        <td><strong>${q.faculty_code}</strong> — ${q.faculty_name}</td>
        <td>${q.course_code} Year ${q.year_number}</td>
        <td>${q.subject_code}</td>
        <td>${q.subject_name}</td>
        <td><button class="btn btn-danger-outline btn-sm" data-delete-qual="${q.id}">Revoke</button></td>
      </tr>`
    )
    .join("");
}

// Event Wiring
document.querySelectorAll(".nav-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab).classList.add("active");
  });
});

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    $("manual-form").classList.toggle("hidden", mode !== "manual");
    $("auto-form").classList.toggle("hidden", mode !== "auto");
    $("cocurricular-form").classList.toggle("hidden", mode !== "cocurr");
    if (mode === "cocurr") refreshCoCurricularRoomAvailability();
  });
});

$("co-validity").addEventListener("change", () => {
  const isDated = $("co-validity").value === "DATED";
  $("co-date-row").classList.toggle("hidden", !isDated);
  $("co-from").required = isDated;
  refreshCoCurricularRoomAvailability();
});

$("co-from").addEventListener("change", () => {
  if (!$("co-to").value) $("co-to").value = $("co-from").value;
  if ($("co-from").value) {
    const d = new Date($("co-from").value + "T00:00:00");
    const jsDay = d.getDay(); // 0=Sun..6=Sat
    if (jsDay >= 1 && jsDay <= 6) {
      $("co-day").value = state.weekdays[jsDay - 1];
    }
  }
  refreshCoCurricularRoomAvailability();
});

["co-day", "co-start", "co-end"].forEach((id) =>
  $(id).addEventListener("change", refreshCoCurricularRoomAvailability)
);
$("co-room").addEventListener("change", updateCoRoomHint);

document.querySelectorAll(".chip[data-co-time]").forEach((chip) => {
  chip.addEventListener("click", () => {
    const [st, en] = chip.dataset.coTime.split("|");
    $("co-start").value = st;
    $("co-end").value = en;
    refreshCoCurricularRoomAvailability();
  });
});

$("man-validity").addEventListener("change", () => {
  const isDated = $("man-validity").value === "DATED";
  $("man-date-row").classList.toggle("hidden", !isDated);
  refreshManualRoomAvailability();
});
$("man-from").addEventListener("change", () => {
  if (!$("man-to").value) $("man-to").value = $("man-from").value;
  refreshManualRoomAvailability();
});
$("auto-validity").addEventListener("change", () => {
  $("auto-date-row").classList.toggle("hidden", $("auto-validity").value !== "DATED");
});

$("grid-date-filter").addEventListener("change", renderTimetableGrid);
$("btn-clear-grid-date").addEventListener("click", () => {
  $("grid-date-filter").value = "";
  renderTimetableGrid();
});

$("sel-course").addEventListener("change", onCourseChange);
$("sel-year").addEventListener("change", onYearOrShiftChange);
$("sel-shift").addEventListener("change", onYearOrShiftChange);
$("sel-section").addEventListener("change", onSectionChange);
$("man-subject").addEventListener("change", syncSubjectFaculty);
$("man-day").addEventListener("change", refreshManualRoomAvailability);
$("man-slot").addEventListener("change", refreshManualRoomAvailability);
$("man-room").addEventListener("change", updateRoomStatusHint);

document.querySelectorAll(".chip[data-reason]").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("man-reason").value = chip.dataset.reason;
  });
});

$("btn-save-primary").addEventListener("click", async () => {
  const sec = getSelectedSection();
  if (!sec) return;
  try {
    await api(`/api/v1/sections/${sec.id}/primary-room`, {
      method: "POST",
      body: JSON.stringify({ room_id: $("sel-primary-room").value || null }),
    });
    showAlert("Primary Class updated successfully.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("manual-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const sec = getSelectedSection();
  if (!sec) return;
  const validity = $("man-validity").value;
  try {
    await api("/api/v1/timetable/manual", {
      method: "POST",
      body: JSON.stringify({
        allocation_category: "COURSE",
        section_id: sec.id,
        day_of_week: $("man-day").value,
        slot_index: Number($("man-slot").value),
        subject_id: Number($("man-subject").value),
        faculty_id: $("man-faculty").value ? Number($("man-faculty").value) : null,
        room_id: Number($("man-room").value),
        validity_type: validity,
        effective_from: validity === "DATED" ? $("man-from").value : null,
        effective_to: validity === "DATED" ? ($("man-to").value || $("man-from").value) : null,
        reason: $("man-reason").value.trim(),
      }),
    });
    showAlert("Slot allotted (Self-Assigned) successfully!");
    $("man-reason").value = "";
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("cocurricular-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const validity = $("co-validity").value;
  try {
    await api("/api/v1/timetable/manual", {
      method: "POST",
      body: JSON.stringify({
        allocation_category: "CLUB_EXTRACURRICULAR",
        day_of_week: $("co-day").value,
        start_time: $("co-start").value,
        end_time: $("co-end").value,
        room_id: Number($("co-room").value),
        faculty_id: $("co-faculty").value ? Number($("co-faculty").value) : null,
        validity_type: validity,
        effective_from: validity === "DATED" ? $("co-from").value : null,
        effective_to: validity === "DATED" ? ($("co-to").value || $("co-from").value) : null,
        reason: $("co-reason").value.trim(),
        custom_title: $("co-reason").value.trim(),
      }),
    });
    showAlert("Co-Curricular venue booked successfully!");
    $("co-reason").value = "";
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

function getAutomationScopeSectionIds() {
  const course = getSelectedCourse();
  const sec = getSelectedSection();
  const year = Number($("sel-year").value);
  const scope = $("auto-scope").value;

  if (scope === "all") {
    return state.sections.map((s) => s.id);
  }
  if (scope === "section" && sec) {
    return [sec.id];
  }
  if (scope === "year" && course) {
    return state.sections
      .filter((s) => s.course_id === course.id && s.year_number === year)
      .map((s) => s.id);
  }
  if (scope === "course" && course) {
    return state.sections
      .filter((s) => s.course_id === course.id)
      .map((s) => s.id);
  }
  return [];
}

$("auto-scope").addEventListener("change", () => {
  const scope = $("auto-scope").value;
  const hintEl = $("auto-scope-hint");
  if (!hintEl) return;
  if (scope === "all") {
    hintEl.textContent = "Cohesive Multi-Department Mode: Interleaves BCA, BBA, MBA, LLB together slot-by-slot, rotating computer labs fairly and keeping theory classes in dedicated primary classrooms.";
  } else if (scope === "course") {
    hintEl.textContent = "Generates timetable for all years & shifts of the selected course.";
  } else if (scope === "year") {
    hintEl.textContent = "Generates timetable for all sections of the selected course & year.";
  } else {
    hintEl.textContent = "Generates timetable for the selected section only.";
  }
});

$("auto-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const sectionIds = getAutomationScopeSectionIds();

  const weekdays = Array.from(document.querySelectorAll('input[name="auto-day"]:checked')).map(
    (cb) => cb.value
  );
  if (!weekdays.length) {
    showAlert("Select at least one working day.", "error");
    return;
  }

  const validity = $("auto-validity").value;
  try {
    const res = await api("/api/v1/timetable/automate", {
      method: "POST",
      body: JSON.stringify({
        section_ids: sectionIds,
        weekdays,
        overwrite_auto: $("auto-overwrite").checked,
        validity_type: validity,
        effective_from: validity === "DATED" ? $("auto-from").value : null,
        effective_to: validity === "DATED" ? ($("auto-to").value || $("auto-from").value) : null,
        shift_config: {
          MORNING: {
            start: $("auto-m-start").value,
            lecture_minutes: Number($("auto-m-dur").value),
            break_minutes: 10,
            break_after_slot: 2,
          },
          AFTERNOON: {
            start: $("auto-a-start").value,
            lecture_minutes: Number($("auto-a-dur").value),
            break_minutes: 5,
            break_after_slot: 2,
          },
        },
      }),
    });
    const box = $("auto-result");
    box.classList.remove("hidden");
    let extra = "";
    if (res.skipped_slots.length) {
      extra += `<br><span class="muted">${res.skipped_slots.length} slot(s) skipped due to room/teacher clauses.</span>`;
    }
    if (res.excluded_events && res.excluded_events.length) {
      extra += `<br><span class="muted">Calendar note: overlaps ${res.excluded_events.map((ev) => `${ev.event_type}: ${ev.title}`).join(", ")}.</span>`;
    }
    box.innerHTML = `<strong>Automation Complete:</strong> Created <strong>${res.created_count}</strong> conflict-free slots across ${res.section_summaries.length} section(s).${extra}`;
    showAlert(`Generated ${res.created_count} automated timetable slots!`);
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("btn-reset-auto").addEventListener("click", async () => {
  const sectionIds = getAutomationScopeSectionIds();
  if (!sectionIds.length) return;
  try {
    const res = await api("/api/v1/timetable/clear", {
      method: "POST",
      body: JSON.stringify({ section_ids: sectionIds, mode: "AUTO" }),
    });
    $("auto-result").classList.add("hidden");
    showAlert(`Reset ${res.deleted_count ?? 0} auto-generated slot(s) in selected scope (Self-Assigned slots kept).`);
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

async function resetAllAutoTimetables() {
  try {
    const res = await api("/api/v1/timetable/clear", {
      method: "POST",
      body: JSON.stringify({ mode: "AUTO" }),
    });
    $("auto-result").classList.add("hidden");
    showAlert(`Reset all ${res.deleted_count ?? 0} auto-generated timetable slot(s) across all courses.`);
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
}

$("btn-reset-all-auto").addEventListener("click", resetAllAutoTimetables);
$("btn-master-reset-auto").addEventListener("click", resetAllAutoTimetables);

$("btn-grid-reset-auto").addEventListener("click", async () => {
  const sec = getSelectedSection();
  if (!sec) return;
  try {
    const res = await api("/api/v1/timetable/clear", {
      method: "POST",
      body: JSON.stringify({ section_id: sec.id, mode: "AUTO" }),
    });
    $("auto-result").classList.add("hidden");
    showAlert(`Removed ${res.deleted_count ?? 0} auto-generated slot(s) for this section.`);
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("btn-clear-section").addEventListener("click", async () => {
  const sec = getSelectedSection();
  if (!sec) return;
  await api("/api/v1/timetable/clear", {
    method: "POST",
    body: JSON.stringify({ section_id: sec.id, mode: "ALL" }),
  });
  $("auto-result").classList.add("hidden");
  showAlert("Section timetable cleared.");
  await loadAll();
});

document.body.addEventListener("click", async (e) => {
  const pickBtn = e.target.closest("[data-pick-day]");
  if (pickBtn) {
    $("mode-manual-btn").click();
    $("man-day").value = pickBtn.dataset.pickDay;
    $("man-slot").value = pickBtn.dataset.pickSlot;
    await refreshManualRoomAvailability();
    $("man-reason").focus();
    return;
  }

  const reallocBtn = e.target.closest("[data-reallocate-entry]");
  if (reallocBtn) {
    try {
      const res = await api(`/api/v1/timetable/${reallocBtn.dataset.reallocateEntry}/reallocate`, {
        method: "POST",
      });
      showAlert(res.message);
      await loadAll();
    } catch (err) {
      showAlert(err.message, "error");
    }
    return;
  }

  const delEntry = e.target.closest("[data-delete-entry]");
  if (delEntry) {
    await api(`/api/v1/timetable/${delEntry.dataset.deleteEntry}`, { method: "DELETE" });
    showAlert("Allotment released.");
    await loadAll();
    return;
  }

  const togRoom = e.target.closest("[data-toggle-room]");
  if (togRoom) {
    await api(`/api/v1/rooms/${togRoom.dataset.toggleRoom}`, {
      method: "PATCH",
      body: JSON.stringify({ status: togRoom.dataset.nextStatus }),
    });
    showAlert("Room status updated.");
    await loadAll();
    return;
  }

  const delRoom = e.target.closest("[data-delete-room]");
  if (delRoom) {
    await api(`/api/v1/rooms/${delRoom.dataset.deleteRoom}`, { method: "DELETE" });
    showAlert("Room removed.");
    await loadAll();
    return;
  }

  const delSub = e.target.closest("[data-delete-subject]");
  if (delSub) {
    await api(`/api/v1/subjects/${delSub.dataset.deleteSubject}`, { method: "DELETE" });
    showAlert("Subject removed.");
    await loadAll();
    return;
  }

  const delUnav = e.target.closest("[data-delete-unavail]");
  if (delUnav) {
    await api(`/api/v1/teacher-availability/${delUnav.dataset.deleteUnavail}`, { method: "DELETE" });
    showAlert("Teacher unavailability cleared.");
    await loadAll();
    return;
  }

  const delEv = e.target.closest("[data-delete-event]");
  if (delEv) {
    await api(`/api/v1/academic-events/${delEv.dataset.deleteEvent}`, { method: "DELETE" });
    showAlert("Calendar event removed.");
    await loadAll();
    return;
  }

  const delQual = e.target.closest("[data-delete-qual]");
  if (delQual) {
    await api(`/api/v1/teacher-subjects/${delQual.dataset.deleteQual}`, { method: "DELETE" });
    showAlert("Qualification mapping removed.");
    await loadAll();
  }
});

["filter-course", "filter-room", "filter-mode", "filter-validity"].forEach((id) =>
  $(id).addEventListener("change", renderMasterTable)
);
$("filter-search").addEventListener("input", renderMasterTable);

["insp-day", "insp-shift", "insp-slot", "insp-date"].forEach((id) =>
  $(id).addEventListener("change", refreshRoomInspector)
);

$("add-room-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/v1/rooms", {
      method: "POST",
      body: JSON.stringify({
        room_code: $("rm-code").value,
        room_type: $("rm-type").value,
        building: $("rm-building").value,
        floor: $("rm-floor").value,
        capacity: Number($("rm-cap").value),
      }),
    });
    e.target.reset();
    showAlert("Room added to Building Master.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("add-unavail-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/v1/teacher-availability", {
      method: "POST",
      body: JSON.stringify({
        faculty_id: Number($("unav-faculty").value),
        shift: $("unav-shift").value,
        start_date: $("unav-from").value,
        end_date: $("unav-to").value,
        reason: $("unav-reason").value,
      }),
    });
    e.target.reset();
    showAlert("Teacher unavailability window saved.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("add-event-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/v1/academic-events", {
      method: "POST",
      body: JSON.stringify({
        event_type: $("ev-type").value,
        title: $("ev-title").value,
        start_date: $("ev-from").value,
        end_date: $("ev-to").value,
      }),
    });
    e.target.reset();
    showAlert("Academic calendar event added.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("add-qual-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/v1/teacher-subjects", {
      method: "POST",
      body: JSON.stringify({
        faculty_id: Number($("qual-faculty").value),
        subject_id: Number($("qual-subject").value),
      }),
    });
    showAlert("Teacher qualification mapped.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("sub-course").addEventListener("change", () =>
  updateCurriculumYearDropdown("sub-course", "sub-year", false)
);
$("curr-filter-course").addEventListener("change", () => {
  updateCurriculumYearDropdown("curr-filter-course", "curr-filter-year", true);
  renderSubjectsTable();
});
$("curr-filter-year").addEventListener("change", renderSubjectsTable);

$("add-subject-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/v1/subjects", {
      method: "POST",
      body: JSON.stringify({
        course_id: Number($("sub-course").value),
        year_number: Number($("sub-year").value),
        subject_code: $("sub-code").value,
        subject_name: $("sub-name").value,
        faculty_id: $("sub-faculty").value ? Number($("sub-faculty").value) : null,
        lectures_per_week: Number($("sub-lpw").value),
        requires_lab: $("sub-lab").checked,
      }),
    });
    $("sub-code").value = "";
    $("sub-name").value = "";
    showAlert("Subject added to curriculum.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

$("add-faculty-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/v1/faculty", {
      method: "POST",
      body: JSON.stringify({
        faculty_code: $("fac-code").value,
        full_name: $("fac-name").value,
        department: $("fac-dept").value,
        max_lectures_per_day: Number($("fac-max").value),
      }),
    });
    e.target.reset();
    showAlert("Faculty member added.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

loadAll().catch((err) => showAlert(err.message, "error"));

// =========================================================================
// ROLE SWITCHER, TEACHER PANEL & STUDENT PANEL
// =========================================================================

document.querySelectorAll(".role-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    document.querySelectorAll(".role-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const role = btn.dataset.role;
    $("admin-panel").classList.toggle("hidden", role !== "admin");
    $("admin-subnav").classList.toggle("hidden", role !== "admin");
    $("teacher-panel").classList.toggle("hidden", role !== "teacher");
    $("student-panel").classList.toggle("hidden", role !== "student");
    if (role === "teacher") await loadTeacherPortal();
    if (role === "student") await loadStudentPortal();
  });
});

async function loadTeacherPortal() {
  const fid = $("tp-faculty").value;
  if (!fid) return;
  const data = await api(`/api/v1/portal/teacher/${fid}`);
  const fac = data.faculty;
  const entries = data.entries;

  $("tp-title").textContent = `${fac.full_name} (${fac.faculty_code}) — Weekly Schedule`;
  $("tp-meta-strip").innerHTML = `
    <span><strong>Department:</strong> ${fac.department}</span>
    <span><strong>Max Lectures/Day:</strong> ${fac.max_lectures_per_day}</span>
    <span><strong>Qualified Subjects:</strong> ${data.qualifications.length}</span>
    <span><strong>Assigned Slots:</strong> ${entries.length}</span>
  `;

  const days = state.weekdays.slice(0, 6);
  const allSlots = [
    ...state.slots.MORNING.map((s) => ({ ...s, shift: "MORNING" })),
    ...state.slots.AFTERNOON.map((s) => ({ ...s, shift: "AFTERNOON" })),
  ];
  const thead = $("tp-grid").querySelector("thead");
  thead.innerHTML = `<tr><th>Shift / Slot</th>${days.map((d) => `<th>${d}</th>`).join("")}</tr>`;
  const tbody = $("tp-grid").querySelector("tbody");

  let gridHtml = "";
  for (const sl of allSlots) {
    gridHtml += `<tr><td class="time-col">${sl.shift}<br>Slot ${sl.slot_index}<br><span class="muted">${sl.start_time}–${sl.end_time}</span></td>`;
    for (const day of days) {
      const matches = entries.filter(
        (e) => e.day_of_week === day && e.shift === sl.shift && e.slot_index === sl.slot_index
      );
      if (matches.length) {
        gridHtml += `<td class="slot-cell">`;
        for (const e of matches) {
          const isClub = e.allocation_category === "CLUB_EXTRACURRICULAR";
          const clsLabel = isClub
            ? `Club: ${e.custom_title}`
            : `${e.course_code} Y${e.year_number}${e.section_code === "Grade-Wise" ? "" : `-${e.section_code}`}`;
          gridHtml += `
            <div class="slot-card ${e.assignment_mode === "MANUAL" ? "manual" : "auto"}" style="margin-bottom:4px;">
              <div class="slot-card-top">
                <span class="badge ${e.validity_type === "LIFETIME" ? "badge-lifetime" : "badge-dated"}">${formatValidity(e)}</span>
              </div>
              <div class="slot-sub">${isClub ? e.custom_title : `${e.subject_code} — ${e.subject_name}`}</div>
              <div class="slot-meta">${clsLabel} • Room <strong>${e.room_code}</strong></div>
              ${e.reason ? `<div class="slot-reason">${e.reason}</div>` : ""}
            </div>`;
        }
        gridHtml += `</td>`;
      } else {
        gridHtml += `<td class="slot-cell"><div class="slot-empty muted">Free</div></td>`;
      }
    }
    gridHtml += `</tr>`;
  }
  tbody.innerHTML = gridHtml;

  const tTable = $("tp-table").querySelector("tbody");
  tTable.innerHTML = entries.length
    ? entries
        .map((e) => {
          const isClub = e.allocation_category === "CLUB_EXTRACURRICULAR";
          const clsLabel = isClub
            ? `Club / Extracurricular`
            : `${e.course_code} Y${e.year_number}${e.section_code === "Grade-Wise" ? "" : ` Sec ${e.section_code}`}`;
          return `
            <tr>
              <td>${e.day_of_week}</td>
              <td>${e.shift} Slot ${e.slot_index} (${e.start_time}–${e.end_time})</td>
              <td>${clsLabel}</td>
              <td>${isClub ? `<strong>${e.custom_title}</strong>` : `${e.subject_code} — ${e.subject_name}`}</td>
              <td><strong>${e.room_code}</strong></td>
              <td><span class="badge ${e.validity_type === "LIFETIME" ? "badge-lifetime" : "badge-dated"}">${formatValidity(e)}</span></td>
              <td>${e.reason || "—"}</td>
            </tr>`;
        })
        .join("")
    : `<tr><td colspan="7" class="muted" style="text-align:center;padding:16px;">No classes assigned yet.</td></tr>`;
}

$("tp-faculty").addEventListener("change", loadTeacherPortal);

$("tp-unavail-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fid = $("tp-faculty").value;
  if (!fid) return;
  try {
    await api("/api/v1/teacher-availability", {
      method: "POST",
      body: JSON.stringify({
        faculty_id: Number(fid),
        start_date: $("tp-unav-from").value,
        end_date: $("tp-unav-to").value,
        shift: $("tp-unav-shift").value,
        reason: $("tp-unav-reason").value,
      }),
    });
    e.target.reset();
    showAlert("Unavailability submitted successfully.");
    await loadAll();
  } catch (err) {
    showAlert(err.message, "error");
  }
});

function onStudentCourseChange() {
  const cid = Number($("sp-course").value);
  const course = state.courses.find((c) => c.id === cid);
  if (!course) return;
  let yHtml = "";
  for (let y = 1; y <= course.duration_years; y++) {
    yHtml += `<option value="${y}">Year ${y}</option>`;
  }
  $("sp-year").innerHTML = yHtml;
  const shifts = course.shifts.split(",");
  $("sp-shift").innerHTML = shifts.map((sh) => `<option value="${sh}">${sh}</option>`).join("");
  onStudentYearOrShiftChange();
}

async function onStudentYearOrShiftChange() {
  const cid = Number($("sp-course").value);
  const yr = Number($("sp-year").value);
  const sh = $("sp-shift").value;
  const matching = state.sections.filter(
    (s) => s.course_id === cid && s.year_number === yr && s.shift === sh
  );
  const isGradeWise = matching.length === 1 && matching[0].section_code === "Grade-Wise";
  $("sp-field-section").classList.toggle("hidden", isGradeWise);
  $("sp-section").innerHTML = matching
    .map((s) => `<option value="${s.id}">Section ${s.section_code}</option>`)
    .join("");
  await onStudentSectionChange();
}

async function onStudentSectionChange() {
  const secId = $("sp-section").value;
  if (!secId) return;
  const data = await api(`/api/v1/students?section_id=${secId}`);
  $("sp-student").innerHTML = data.students
    .map((st) => `<option value="${st.id}">${st.erp_id} — ${st.full_name}</option>`)
    .join("");
  await loadStudentPortal();
}

async function loadStudentPortal() {
  const stId = $("sp-student").value;
  if (!stId) return;
  const data = await api(`/api/v1/portal/student/${stId}`);
  const st = data.student;
  const entries = data.entries;

  const secTxt = st.section_code === "Grade-Wise" ? "" : ` • Section ${st.section_code}`;
  $("sp-meta-strip").innerHTML = `
    <span><strong>Student:</strong> ${st.full_name} (${st.erp_id})</span>
    <span><strong>Class:</strong> ${st.course_code} Year ${st.year_number} • ${st.shift}${secTxt}</span>
    <span><strong>Primary Room:</strong> ${st.primary_room_code || "Not Set"}</span>
    <span><strong>Classmates:</strong> ${data.classmates.length} students</span>
  `;
  $("sp-title").textContent = `${st.course_code} Year ${st.year_number} (${st.shift})${secTxt} — Timetable`;

  const days = state.weekdays.slice(0, 6);
  const slots = state.slots[st.shift] || [];
  const thead = $("sp-grid").querySelector("thead");
  thead.innerHTML = `<tr><th>Time / Slot</th>${days.map((d) => `<th>${d}</th>`).join("")}</tr>`;

  let html = "";
  for (const sl of slots) {
    html += `<tr><td class="time-col">Slot ${sl.slot_index}<br><span class="muted">${sl.start_time}–${sl.end_time}</span></td>`;
    for (const day of days) {
      const matches = entries.filter((e) => e.day_of_week === day && e.slot_index === sl.slot_index);
      if (matches.length) {
        html += `<td class="slot-cell">`;
        for (const e of matches) {
          html += `
            <div class="slot-card ${e.assignment_mode === "MANUAL" ? "manual" : "auto"}" style="margin-bottom:4px;">
              <div class="slot-card-top">
                <span class="badge ${e.validity_type === "LIFETIME" ? "badge-lifetime" : "badge-dated"}">${formatValidity(e)}</span>
              </div>
              <div class="slot-sub">${e.subject_code} — ${e.subject_name}</div>
              <div class="slot-meta">Room: <strong>${e.room_code}</strong> • ${e.faculty_name || e.faculty_code || "TBA"}</div>
              ${e.reason ? `<div class="slot-reason">${e.reason}</div>` : ""}
            </div>`;
        }
        html += `</td>`;
      } else {
        html += `<td class="slot-cell"><div class="slot-empty muted">Free</div></td>`;
      }
    }
    html += `</tr>`;
    if (sl.slot_index === 2) {
      html += `<tr class="break-row"><td colspan="${days.length + 1}">SHORT BREAK</td></tr>`;
    }
  }
  $("sp-grid").querySelector("tbody").innerHTML = html;

  $("sp-roster-table").querySelector("tbody").innerHTML = data.classmates
    .map(
      (c) => `
      <tr style="${c.id === st.id ? "background:#eff6ff;font-weight:600;" : ""}">
        <td>${c.roll_no}</td>
        <td>${c.erp_id}</td>
        <td>${c.full_name}${c.id === st.id ? " (You)" : ""}</td>
      </tr>`
    )
    .join("");

  $("sp-clubs-table").querySelector("tbody").innerHTML = data.clubs.length
    ? data.clubs
        .map(
          (cl) => `
        <tr>
          <td><strong>${cl.custom_title}</strong></td>
          <td>${cl.day_of_week} (${cl.shift})</td>
          <td>Slot ${cl.slot_index} (${cl.start_time}–${cl.end_time})</td>
          <td><strong>${cl.room_code}</strong></td>
          <td><span class="badge ${cl.validity_type === "LIFETIME" ? "badge-lifetime" : "badge-dated"}">${formatValidity(cl)}</span></td>
        </tr>`
        )
        .join("")
    : `<tr><td colspan="5" class="muted">No club/extracurricular room bookings yet.</td></tr>`;
}

$("sp-course").addEventListener("change", onStudentCourseChange);
$("sp-year").addEventListener("change", onStudentYearOrShiftChange);
$("sp-shift").addEventListener("change", onStudentYearOrShiftChange);
$("sp-section").addEventListener("change", onStudentSectionChange);
$("sp-student").addEventListener("change", loadStudentPortal);
