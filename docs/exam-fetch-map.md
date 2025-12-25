# Exam Fetch Implementation Map

## 1. Flow overview

| Step | Module & file | Callable | Responsibility | Next call(s) |
| --- | --- | --- | --- | --- |
| 1 | `zjuical.py` | CLI entry point | Loads config, gathers credentials/flags | `main.integration.getCalender` |
| 2 | `main/integration.py` | `getCalender(username, password, skip_verification)` | Instantiates the authenticated client and calendar builder | `zjuam.ugrs.UgrsZjuam` (constructor, `login`) |
| 3 | `zjuam/base.py` | `Zjuam.__init__` | Creates a shared `requests.Session` (`self.r`) | used by `UgrsZjuam` methods |
| 4 | `zjuam/ugrs.py` | `UgrsZjuam.login()` | Performs CAS/ZJUAM authentication and binds cookies to the session | `UgrsZjuam.getExams()` |
| 5 | `zjuam/ugrs.py` | `UgrsZjuam.getExams(count=5000)` | POSTs to the undergraduate exam endpoint and loads JSON | `exam.exam.ExamTable.fromZdbk` |
| 6 | `exam/exam.py` | `ExamTable.fromZdbk(items)` | Normalises raw rows into `Exam` instances (mid/final/no exam) | `ExamTable.toEvents` |
| 7 | `exam/exam.py` | `ExamTable.toEvents(courses)` | Creates ICS `Event` objects for exams, skipping duplicates/no-time cases | `ical.ical.Calender.addEvents` |
| 8 | `ical/ical.py` | `Calender.addEvents / getICS` | Serialises all `Event`s into the final `.ics` string | returned to CLI |

`UgrsZjuam.getCourses` (also in `zjuam/ugrs.py`) passes the same `ExamTable` into `CourseTable.communicate` so courses can display exam-derived metadata (credits). The exam pipeline above remains the source of truth for exam events.

## 2. Responsibility map by concern

### Authentication & session management
- **File**: `zjuam/base.py`
  - `class Zjuam`: constructor stores credentials and initialises `requests.Session` (`self.r`).
- **File**: `zjuam/ugrs.py`
  - `UgrsZjuam.ZDBK_LOGIN_URL`: CAS login page for the undergraduate teaching system (includes the `service` redirect).
  - `UgrsZjuam.login()`: three stages—CSRF extraction (`execution` field via regex), public key fetch (`PUBKEY_URL`), RSA encryption of the password, and final POST to `LOGIN_URL`. Explicitly guards against wrong credentials and lockouts.
  - Successful login seeds cookies into `self.r` so subsequent POSTs are authenticated.

### Exam schedule HTTP retrieval
- **File**: `zjuam/ugrs.py`
  - Constants:
    - `EXAM_URL = "https://zdbk.zju.edu.cn/jwglxt/xskscx/kscx_cxXsgrksIndex.html?doType=query&gnmkdm=N509070&su=%s"` – `su` is the username.
  - `UgrsZjuam.getExams(count=5000)`:
    - Sends a POST using the shared session with payload matching the campus portal grid (`queryModel.*` fields, timestamp `nd`, etc.).
    - Parses `res.json()` and passes `content["items"]` to `ExamTable.fromZdbk`.
    - Handles JSON failures by logging the raw HTML (often indicates re-login or IP restrictions).

### Parsing raw exam rows
- **File**: `exam/exam.py`
  - `class Exam` constructor:
    - Distinguishes exam types by presence of `kssj` (final) and `qzkssj` (mid-term). Missing both becomes `ExamType.NoExam`.
    - Normalises names (`()` → `（）`), credits, location fields, and seat numbers.
    - Calls `exam.convert.parseExamDateTime` for time strings; handles “考试第 x 天” by returning the dummy sentinel.
  - `ExamTable.fromZdbk` iterates raw items, instantiating one or two `Exam` objects per row depending on available keys.
  - `ExamTable.find(course)` allows courses to fetch their matching exams via `classId` (used in course credit enrichment).

### ICS rendering for exams
- **File**: `exam/exam.py`
  - `Exam.summary`, `locationString`, `description` expose formatted text used in ICS events.
  - `ExamTable.toEvents(courses)`:
    - Prevents duplicate events by toggling `Exam.isEventGenerated` per exam/class pairing.
    - Generates `ical.ical.Event` objects with the project’s summary/location/description conventions and attaches the course teacher information.
- **File**: `ical/ical.py`
  - `Event` dataclass holds ICS attributes and formats them (e.g., Asia/Shanghai timezone, UID hashing).
  - `Calender.addEvents` aggregates exam events; `Calender.getICS` wraps them into a complete VCALENDAR payload.

### Call hierarchy cross-reference
- `zjuical.py` → `main.integration.getCalender` → `UgrsZjuam.login()` → `UgrsZjuam.getExams()` → `ExamTable.fromZdbk()` / `Exam` → `ExamTable.toEvents()` → `Calender.addEvents()` / `Calender.getICS()`.
- The same `UgrsZjuam` instance subsequently calls `getCourses`, passing the populated `ExamTable` so course credits and exam metadata stay in sync.

## 3. Minimal reusable snippet reference
- Path: [`examples/exam_fetch_min.py`](../examples/exam_fetch_min.py)
- Contents: ~70-line standalone example that:
  1. Reproduces the CAS login handshake (CSRF extraction, RSA encryption using the public key endpoint).
  2. Fetches exams via the same POST endpoint and payload as `UgrsZjuam.getExams`.
  3. Normalises items into dictionaries mirroring the project’s `Exam` attributes (course name, class ID, credit, type, start/end, location, seat).
  4. Serialises confirmed exams into an `.ics` file using the Asia/Shanghai timezone rules.
- Usage notes: set `ZJU_USERNAME` and `ZJU_PASSWORD` environment variables; requires only the public `requests` dependency. The script writes `zju_exams.ics` to the working directory and prints the number of rows pulled.

## 4. Notes & assumptions
- **Dependencies**: the main project relies on `requests` for HTTP, `loguru` for logging, and its bundled `ical` package for ICS rendering. The standalone snippet pares this down to `requests` and standard library utilities while replicating the login/encryption logic.
- **Config interactions**: holiday tweaks (`config.tweaks`) do not alter exam events; they only affect course scheduling. Exams are generated directly from the upstream response.
- **Error handling**:
  - `UgrsZjuam.login` checks for credential and lockout messages in the CAS response.
  - `UgrsZjuam.getExams` catches `json.JSONDecodeError`, logging raw HTML when the portal returns a login page or maintenance notice instead of JSON.
  - `exam.convert.parseExamDateTime` returns a sentinel date when the university publishes relative-day descriptions (e.g., “考试第2天”), keeping the event but flagging the missing exact time.
  - `ExamTable.toEvents` skips events whose start/end remain unset (so malformed times do not break ICS generation).
- **Formats**: final exam times follow `YYYY年MM月DD日(HH:MM-HH:MM)`; the snippet and project both parse this directly. Midterm entries mirror this via `qzkssj`/`qzjsmc`/`qzzwxh` fields. Items lacking both time keys are tagged as “无考试”.
- **Authentication scope**: the undergraduate client expects usernames starting with `3`. `getCalender` enforces this unless `--skip-verification` is provided; this guard is upstream of exam fetching.

This map, together with the reusable snippet, should allow engineers to locate, understand, and replicate the exam retrieval pipeline without walking the entire repository.
