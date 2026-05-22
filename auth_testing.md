# HRMIS Auth Testing

Auth uses JWT Bearer tokens (24h access token). Login returns `{ token, user }`.
Frontend stores token in `localStorage` and sets `Authorization: Bearer <token>` on every request.

## Seeded Admin
- Email: `admin@acme.com`
- Password: `Admin@123`
- Role: `super_admin`

## Demo Employee
- Email: `maya@acme.com`
- Password: `Demo@123`
- Role: `employee`

## Steps
```
curl -s -X POST {BACKEND}/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.com","password":"Admin@123"}'

# returns { token, user }

curl -s -H "Authorization: Bearer <token>" {BACKEND}/api/auth/me
# returns the user
```

## Indexes that must exist
- `users.email` unique
- `users.id` unique
- `employees.user_id` unique
- `attendance` compound `(user_id, date)` unique
- `password_reset_tokens.expires_at` TTL
- `login_attempts.key` unique

## Brute force
5 failed logins on same email → 15 min lockout (HTTP 429).
