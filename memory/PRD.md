# HRMIS Platform — PRD

## Original Problem Statement
A Human Resource Management Information System (HRMIS) web platform for companies to manage employees, attendance, leave, work-from-home requests, meetings, internal communication, and core HR operations. Two main sides: Admin/HR dashboard and Employee dashboard. Roles: super_admin, hr, manager, employee.

## User Choices (from initial ask_human)
- Responsive web app (no React Native build in this env)
- JWT-based custom auth with bcrypt + role-based access
- Real email via **Resend** (key provided, sender `onboarding@resend.dev`)
- Skip file uploads in MVP
- Modern enterprise clean design (Outfit + Manrope fonts)

## Architecture
- **Backend**: FastAPI on `:8001` behind `/api/*` ingress prefix. JWT Bearer tokens (24h). Resend for transactional emails.
- **Frontend**: React 19 + Tailwind + shadcn/ui, hosted on `:3000`. Axios with token interceptor. React Router 7.
- **Database**: MongoDB. Collections: users, employees, departments, attendance, leave_requests, leave_balances, wfh_requests, meetings, chat_messages, announcements, notifications, login_attempts, password_reset_tokens.

## User Personas
- **Super Admin / HR** (`admin@acme.com`, `jordan@acme.com`): full visibility, employee CRUD, policy config, approvals, announcements.
- **Manager** (`alex@acme.com` etc.): team approvals + admin views (no employee creation).
- **Employee** (`maya@acme.com` etc.): check-in/out, status, leave/WFH apply, chat, meetings, profile.

## What's Implemented (Feb 2026)
### Backend
- JWT auth (login, /me, logout, register-by-admin, forgot/reset password) with bcrypt + brute force lockout
- Resend email service with branded HTML wrapper
- Employees CRUD + filters (department/status/search) + admin-only create with welcome email
- Departments CRUD
- Attendance: check-in/out, status updates, history, admin monitor view
- Leave: apply, list mine/all, approve/reject, balances, calendar — with email + in-app notifications
- WFH: same pattern + "who's remote today" feed
- Meetings: create, list (scope=mine/all), cancel, with email invites to attendees
- Chat: 1:1 messages, contacts list with presence + unread counts
- Announcements: post + optional email broadcast to all employees
- Notifications: list, mark read, mark all read
- Dashboard: admin overview KPIs + 7-day trend + dept counts + pending queues; employee daily view

### Frontend
- Split-screen Login with demo-account chip auto-fill
- Admin layout: dark sidebar, header w/ notif bell + user menu
- Employee layout: spacious top-nav with mobile-friendly nav, notif bell
- Admin pages: Overview (KPIs + bar chart + pending approvals + dept breakdown), Employees (table + add dialog), Attendance monitor, Leave & WFH approval queues, Meetings, Chat, Announcements, Reports (CSV export), Settings (departments + leave policy display)
- Employee pages: Today (hero check-in/out card with live duration + status dropdown), MyLeave, MyWFH, Meetings, Chat, Profile (30-day attendance heatmap)
- Outfit + Manrope fonts; color-coded status pills exactly as design guidelines.

## Backlog
- P1: Leave calendar visualisation (currently API exists; UI shows list)
- P1: Group/team chat (only 1:1 currently)
- P1: File/document uploads (skipped per user choice)
- P2: Real-time chat via WebSocket (currently polling every 4s)
- P2: Manager-scoped team views (currently all admins see all)
- P2: Payroll, recruitment, performance reviews (out of MVP per problem statement)
- P2: Mobile React Native build (unsupported in this env)
- P2: Calendar grid view for meetings (currently card list)

## Test Credentials
See `/app/memory/test_credentials.md`.

## 2026-06-30 — WhatsApp Business Cloud API Integration
- Added per-tenant WhatsApp config (`whatsapp_configs` collection) + outbox audit (`whatsapp_outbox`)
- New service files: `backend/whatsapp_service.py`, `backend/notification_service.py`
- New admin API: `GET/PUT /api/whatsapp/config`, `POST /api/whatsapp/test`, `GET /api/whatsapp/outbox`, `GET /api/whatsapp/templates`
- Hooked notifications into 5 trigger events (status change, leave apply, WFH apply, meeting scheduled, check-in/out)
- Per-event toggle + per-status filter (skip Active/Offline by default)
- New admin page: `/admin/whatsapp` with Configuration / Event triggers / Templates / Outbox / Setup guide tabs
- 5 Meta-approval template specs delivered to customer for submission to WhatsApp Manager (UTILITY, en_US)
- All notification calls are fire-and-forget safe — HR flows never break on WA failures
- Token is stored encrypted-at-rest only via mongo (masked on every API response)

## 2026-07-17 — Room Availability Calendar Grid
- New `GET /api/rooms/day-schedule?date=YYYY-MM-DD` — returns every active room + its bookings for the day, sorted by start time. Overlap query keeps midnight-spanning meetings visible on both days. Strict date validation via `datetime.strptime`.
- New `/admin/rooms` & `/employee/rooms` route (RoomAvailability.jsx) — horizontal Gantt-style grid: rooms as rows, 08:00-20:00 axis in half-hour columns.
- Booking blocks render indigo for confirmed / amber for pending-approval — non-clickable so users can't accidentally rebook.
- Empty half-hour slots (48 per row) are clickable → deep-link to `/admin/meetings?new=1&room_id=&start=&end=` which auto-opens the Schedule dialog with the room, start & end pre-filled and the "Room is available" green hint.
- Rose "now" line + dot rendered only when viewing today; date picker + Prev/Next/Today buttons + weekend badge.
- Sidebar "Rooms" link (MapPin icon) added to both AdminLayout and EmployeeLayout.
- Iteration 17 report: 12/13 backend (initial lax-date validation fixed same session) + 9/9 frontend flows pass.

## 2026-07-17 — Meeting-Room Booking + Approval Flow
### Rooms (fully manageable from day 1)
- New `meeting_rooms` collection auto-seeded with 2 defaults per company (Conference Room A · 8 seats, Conference Room B · 4 seats). Idempotent — `ensure_default_rooms` no-ops when any room exists.
- Full CRUD (`/api/rooms`) — super_admin & HR can add / edit / delete / reactivate. Features: TV, Whiteboard, Video conference, Projector, Phone, Wi-Fi. Location text field. Soft-delete via `active:false` so historic bookings still resolve the name.
- New Settings panel (`MeetingRoomsPanel.jsx`) with add/edit/delete + "Show deactivated" toggle + Reactivate button for inactive rooms.

### Booking flow (integrated into existing Meetings)
- `POST /api/meetings` now accepts `room_id`, `is_recurring`, `recurrence`. Backend computes `duration_minutes` and marks meeting `pending` if duration > 120min or recurring (super_admin/HR auto-approve their own). 
- Hard conflict block: 409 with a human-readable message ("Conference Room A is already booked from 10:00 to 10:30 for 'Standup' by Maya Patel.") — cancelled + rejected meetings are excluded.
- Live conflict check on the Meetings dialog via new `POST /api/rooms/check-conflict` — debounced 350ms; shows green "Room is available for this slot" or red "Room already booked" banner.
- HR approval flow: `GET /api/meetings/pending-approval`, `POST /:id/approve`, `POST /:id/reject`. Approve re-checks the room (returns 409 if the slot was taken meanwhile) and only THEN fires the invites/email/WhatsApp — nothing is sent while pending.
- Amber HR-approval banner appears in the create dialog whenever duration > 2h or recurring is ticked; submit button label changes to "Submit for approval".
- Recurrence UI supports daily / weekly / bi-weekly / monthly with count (backend stores the dict as-is; no re-scheduling of children yet).

### Notifications
- WhatsApp `meeting_scheduled` template + email invite continue to fire — but ONLY on the transition to approved/auto_approved so nobody gets spammed for rejected meetings.
- HR receives in-app notifications for every new pending request; organiser is pinged on approve/reject.

### Testing
- New pytest suite `/app/backend/tests/test_iter16_rooms_meetings.py` — 16/16 pass. Iteration 16 report: 100% backend + all critical frontend flows.


### Re-Check-In (P0 request)
- New endpoint `POST /api/attendance/re-check-in` — reopens today's attendance for an employee who accidentally checked out. Appends a fresh open session; the previous check_out is preserved in the audit log.
- Available to **all authenticated roles** (super_admin / hr / manager / employee) — the shared `CheckInWidget` on the Admin/HR/Manager dashboards now shows a green "Re-check in" button in the "Day complete" state alongside the "Wrapped up at HH:MM" pill.
- Kiosk (`POST /api/kiosk/check-in`) now auto-detects the same case and takes the re-check-in path instead of returning 400.
- Backwards-compatible: legacy attendance docs missing `sessions` are transparently backfilled from `check_in`/`check_out`.

### Audit log (`attendance_events` collection)
- Every `check_in`, `check_out`, `re_check_in`, and `status_change` writes an immutable event row: `id, company_id, user_id, date, event_type, ts, via (web|kiosk|admin), actor_user_id, meta`.
- New endpoint `GET /api/attendance/events?days=N` — chronological trail for the calling user.
- Employee "Today" page renders the trail below the hero card with colored dots per event type.

### CSV Export (P0 request)
- `GET /api/attendance/export?start&end&department` — super_admin/hr only (manager gets 403). Range capped at 366 days.
- Streams a CSV with columns: **Date, Employee Code, Name, Department, Designation, Email, First Check-in, Last Check-out, Sessions, Total Hours, Late (Y/N), Late Minutes, Early Departure Minutes, Overtime Hours, Status, Notes.**
- Rows include: Present, WFH, On Leave · &lt;type&gt;, Weekly Off (Sat/Sun), Absent. Multi-session days get a "N sessions (re-check-in)" note.
- New "Export report" dialog on `/admin/attendance` with 5 presets (Today / Last 7 / This month / Last month / Last 90) + department filter.
- Frontend also shows a small `N×` pill next to Check-out for days with multiple sessions.

### Testing
- New pytest suite: `/app/backend/tests/test_iter15_attendance_recheckin.py`.
- 100% pass on iteration 15 (13/13 backend + full frontend flows).


- **Bug fix**: `PATCH /api/employees/{id}` used `model_dump(exclude_none=True)` which silently dropped `manager_id=null`, so selecting "No manager" on the Edit dialog never persisted. Switched to `exclude_unset=True` — nulls that the client explicitly sends now save through.
- **Role editing**: Added `role` field to `EmployeeUpdate`. Route now updates `users.role` (with audit fields `role_changed_by`/`role_changed_at`). Guardrails: only super_admin/hr can change roles; HR cannot promote to or modify a super_admin.
- **UI**: Edit Employee modal has a new "Role & access" section (indigo card) with Role + Status side-by-side, visible only to super_admin/hr. A confirm checkbox surfaces when the role actually changes.

## 2026-07-13 — Face-Enrollment Robustness + Kiosk QR + Expense Claims
### Face enrollment fix (P0)
- `useFaceCapture.js` now: (a) sets `backend: 'humangl'` explicitly with wasm fallback, (b) loads WASM binaries from jsdelivr CDN (fixes CompileError from HTML fallback), (c) requests camera BEFORE model download (fast fail on permission denial), (d) surfaces friendly errors for each failure mode + Retry button, (e) resets the loader promise on failure so retry works.
- `FaceEnroll.jsx` + `Scan.jsx` now render dedicated error overlays with Retry/Cancel actions.

### Kiosk shortcut on Admin dashboard
- New `KioskLinkCard.jsx` shows a tablet-scannable QR code + URL + Copy/Open/Rotate + Enable toggle at the top of the Admin overview. Uses `qrcode.react` (v4.2.0).

### Expense Claims (P1)
- Backend: `routes/expenses.py` — POST /api/expenses, GET /api/expenses/mine, /all, /summary, /:id, /:id/receipt, POST /:id/approve, /:id/reject, /:id/mark-paid, DELETE /:id. 5MB receipt limit (jpg/png/webp/heic/pdf).
- MongoDB indexes for `expense_claims` in `seed.py`.
- Employee page `/employee/expenses`: submit with receipt, 3 status summary cards, table with view-receipt + delete.
- Admin page `/admin/expenses`: 4 status summary cards, tabs (pending/approved/rejected/paid/all), approve/reject with note, super_admin/hr can mark reimbursed.
- Nav links added to both AdminLayout and EmployeeLayout.
- Notifications: pending → routed to direct manager + admin pool; decision → back to employee.

## Backlog / P1–P2 remaining
- P1: Performance review system
- P1: Asset management (laptops, phones, allocations, returns)
- P1: WhatsApp notifications for Expense events (approve/reject/paid)
- P2: Biometric/device integration
- P2: Third-party calendar sync (Google Calendar, Outlook)
- P2: Group/team chat (only 1:1 currently)
- P2: Calendar grid view for meetings
