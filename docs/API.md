# Quodes Gaming API (v1)

Base URL: `http://<host>:8000/api/` · JSON everywhere (except proof/ticket uploads: multipart).
Auth: `Authorization: Bearer <access>` (SimpleJWT). Access lives 1 day, refresh 30 days.
Errors: `{"detail": "message"}` or DRF field errors `{"field": ["msg"]}`. Times are ISO-8601 with timezone (Asia/Kolkata); every booking payload carries `server_time` so the app can compute countdowns without trusting the phone clock.

## Auth
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `auth/register/` | `email, password, gamertag, full_name, phone` | 201 `{verify_required: true, email, masked_email, resend_after, detail}`, and a 6-digit code is emailed. (With `REQUIRE_EMAIL_VERIFICATION=false`: `{access, refresh, user}`.) |
| POST | `auth/email/verify/` | `email, code` | `{access, refresh, user}` and a welcome email |
| POST | `auth/email/resend/` | `email, purpose?: "verify"\|"reset"` | `{detail, masked_email, resend_after}`; 429 if asked again within 60 s |
| POST | `auth/login/` | `email, password` | `{access, refresh, user}`; **403** `{code: "email_not_verified", email, masked_email, resend_after}` if not verified (a fresh code is emailed) |
| POST | `auth/refresh/` | `refresh` | `{access}` |
| POST | `auth/password/forgot/` | `email` | `{detail, masked_email, resend_after: 60}`. Always 200, so nobody can probe which emails have accounts. The code is emailed. |
| POST | `auth/password/reset/` | `email, code, new_password` | `{detail}`. The code is 6 digits, valid 10 min, 5 attempts. Also marks the email verified and sends a "password changed" email. |
| GET/PATCH | `me/` | `gamertag, full_name, phone` | `User` |

`User`: `{id, email, email_verified, gamertag, full_name, phone, initials, credit, hours_played, sessions}` (`credit` is a decimal string, rupees).

## Café & catalog (public)
- `GET cafe/` → `{name, open_now, opens_at, closes_at, upi_id, upi_payee, lock_minutes: 10, verify_hours: 2, support_phone, maps_url, reply_minutes, open_hour, close_hour}` (`opens_at`/`closes_at` are labels like `"10 AM"`, `"12 AM"`).
- `GET games/?genre=SHOOTER&q=val` → `[Game]`; `Game = {id, name, mono, genre, hue, deep, platforms: ["PS5","PS4","PC"], max_players}`.
- `GET genres/` → `["All","Shooter","Sports",...]`.
- `GET station-types/?game=<id>` → `[{code: "PS5", name, spec, seats_per_station, hourly_rate, max_players, free_seats, total_seats, enabled}]` (`enabled` false when the game doesn't run on that platform).
- `GET seatmap/?type=PS5` → `{type, seats_per_station, cols, stations: [{id, code, seats: [{id, code, label, busy}]}]}` — `busy` = booked/locked in the current hour.
- `GET availability/?date=YYYY-MM-DD` → `{date, types: [{code, total, free_now}], hours: [{hour: 14, label: "2 PM", free: {"PS5": 3, "PS4": 2, "PC": 7}}]}` — a station counts as free in an hour when none of its seats is booked or locked.
- `GET slots/?seats=1,2&date=YYYY-MM-DD` → `{date, hours: [{hour, label, status: "open"|"hold"|"booked"|"past"}]}` for exactly those seats.
- `GET dates/` → next 7 days `[{date, dow: "FRI", num: 30, mon: "Oct"}]`.

## Bookings (auth)
`Booking`:
```
{id, code: "QG-7F3K2A", status, status_label,
 game: Game, station_type: "PS5", station_label: "PS5 · Station 04",
 seats: [{id, code: "S5-04-1", label: "P1", station: "S5-04"}], players,
 date, start_hour, duration_hours, date_label: "Sat, 31 Oct", time_label: "4 PM – 6 PM",
 rate, subtotal, total, credit_applied, amount_due,
 upi_id, upi_payee, upi_uri,
 lock_expires_at, verify_deadline, created_at, submitted_at, ai_checked_at, confirmed_at, released_at,
 utr, ai_checks: [{key, label, detail, status: "pass"|"fail"|"pending"}], ai_message,
 server_time}
```
`status`: `locked` (10-min hold, unpaid) → `scanning` (AI reading proof) → `pending_human` (provisionally booked, staff has 2 h) → `confirmed`.
Side exits: `ai_failed` (back to upload while lock still valid), `expired` (lock ran out unpaid), `released` (staff didn't verify in 2 h → amount credited), `rejected` (staff rejected), `cancelled` (user unlocked).

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `bookings/` | `game, seat_ids: [int], date, start_hour, duration_hours` | 201 `Booking` (`locked`). 409 `{detail}` if any seat/hour taken. Max 4 players, 1–4 h, seats must share one station type. |
| GET | `bookings/` | | My bookings, newest first. `?active=1` → only locked/scanning/ai_failed/pending_human/confirmed-upcoming. |
| GET | `bookings/<id>/` | | Poll this for status changes. |
| POST | `bookings/<id>/cancel/` | | Unlock (only `locked`/`ai_failed`). |
| POST | `bookings/<id>/proof/` | multipart `screenshot` (png/jpg ≤5 MB), `utr` (optional, 12 digits) | → `scanning`; AI runs in background; poll. |
| POST | `bookings/<id>/manual-review/` | | From `ai_failed` → `pending_human`. |
| POST | `bookings/<id>/rebook/` | | From `released`: re-locks same seats/time using credit if still free → `pending_human`-free path: returns new `Booking` with status `confirmed` (paid by credit). 409 if taken. |

## Support & content
- `GET tickets/` (auth) → `[{id, number, topic, booking_code, message, status: "open"|"in_review"|"resolved", status_label, updated_at}]`
- `POST tickets/` (auth, multipart or JSON) `topic` (Payment|Reschedule|Refund|Station issue|Other), `booking_code?`, `message`, `attachment?` → ticket.
- `GET faqs/` → `[{id, question, answer}]`
- `GET policies/` → `[{key: "house"|"privacy"|"refunds", title, updated: "YYYY-MM-DD", sections: [{heading, body}]}]`

## Emails sent
| When | To | Email |
|---|---|---|
| Signup / unverified login / resend | player | 6-digit verification code |
| Email verified | player | Welcome |
| Forgot password | player | 6-digit reset code |
| Password reset | player | Password changed |
| Slot locked | player | Pay ₹X to UPI ID before HH:MM |
| AI passed, or manual review requested | player + staff | Provisionally booked / Payment to verify (with admin link) |
| AI failed | player | What failed, how long the lock lasts |
| Staff approved, or rebooked with credit | player | GG! Confirmed |
| Staff rejected | player | Payment not verified |
| Not verified in time | player | Slot released, amount saved as credit |
| Lock expired with no upload | player | Lock ran out |
| Ticket created | player + staff | Ticket received / New ticket |
| Staff changed ticket status or replied | player | Ticket update |
