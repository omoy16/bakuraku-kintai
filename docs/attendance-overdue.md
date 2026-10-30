# WBS 1.6 — 長時間未退勤判定

Issue: https://github.com/omoy16/bakuraku-kintai/issues/13

## Rules
- An active shift is overdue from exactly 16 hours after `clock_in_at`. Night shifts stay active across calendar days.
- Acknowledgement suppresses a new confirmation request for **1 hour**, provisionally. Constant: `CONFIRMATION_SNOOZE`.
- No automatic clock-out. The old `working` / `not_working` API contract is unchanged.
- `still_working`: resume work, snooze. `forgot_clock_out`: snooze and set `requires_correction=true`. Manual correction belongs to WBS 1.7; the confirmation modal belongs to WBS 2.3.
- Confirmation timestamp and choice persist on the shift. The notification-only `reminder_sent_at` is unaffected.
- User identity and server time come from dependencies, not client parameters.
- Repeating the same confirmation inside 1 hour is idempotent. A conflicting choice during the cooldown is HTTP 409.

## Endpoints
GET `/api/attendance/overdue` returns `record_id`, `overdue_at`, `requires_confirmation`, `suppressed_until`, and `last_choice`. When no shift is active, timestamps, record_id and last_choice are null and requires_confirmation is false.

POST `/api/attendance/overdue/confirm` accepts:
```json
{ "choice": "still_working" }
```
Also accepts `forgot_clock_out`. Returns record_id, choice, requires_correction, suppressed_until. Invalid choices return 422. No active shift or premature confirmation returns 409. Database errors retain 503.

## Database and verification
`0002_overdue_confirmation` adds nullable timestamptz `overdue_confirmed_at` and varchar(32) `overdue_confirmed_choice` to `attendance_records`, plus two CHECK constraints. Existing records start with both fields null.

```powershell
python -m pip install -r backend/requirements-dev.txt
python dev.py init-db
# For integration tests set BAKURAKU_TEST_DATABASE_URL to a dedicated test DB.
python dev.py test
```

CI uses PostgreSQL 16; tests cover exact 16-hour and 1-hour boundaries, persistence, choices, duplicate actions, concurrency, per-user isolation and no auto clock-out. Never run tests against production.
