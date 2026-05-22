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
