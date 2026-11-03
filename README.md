# Quodes Gaming

A booking app for a gaming café, built from the "Quodes Gaming" design canvas (19 screens).

```
backend/   Django 5.2 + DRF API, admin panel (/admin), Groq payment-screenshot check
mobile/    Flutter app (Android + iOS)
docs/API.md  API contract shared by both
```

## How a booking moves through the system
1. A player picks a game, a station type and seats (max 4), a date, a start time and a duration (1–4 h).
2. **LOCK SLOT** creates a `locked` booking. The seats are held for **10 min** using one `SeatHour` row per seat-hour with a unique constraint, so two players can never hold the same seat-hour.
3. The player pays the UPI QR (`upi://pay?...`, exact amount), then uploads a screenshot and, optionally, the UTR.
4. **AI scan** (`scanning`): a Groq vision model reads the screenshot and returns structured fields. Python code then checks: success screen, amount, payee UPI ID, UTR not reused (and matches the typed UTR), and payment time inside the lock window.
   - All checks pass → `pending_human`. The booking is provisionally held and staff have **2 h** to confirm it.
   - Any check fails → `ai_failed`. The player can re-upload while the lock lasts, or ask for manual review.
   - No API key, or the AI errors → straight to `pending_human` (no player gets stuck).
5. Staff open **Verify payments** in the admin panel, check the bank app, and press **Approve payment** (→ `confirmed`) or **Reject payment** on the booking.
6. If staff don't confirm within 2 h, the booking becomes `released`, the seats are freed and the amount is added to the player's **game credit**. **Rebook with credit** re-takes the same slot if it's still free.

Expiry is applied lazily on every booking or availability request, and by `python manage.py sweep_bookings`. In production, run that command every minute from cron.

## Backend
```bash
cd backend
uv venv -p python3.13 .venv && uv pip install -r requirements.txt   # or python -m venv + pip
# backend/.env: paste your key into GROQ_API_KEY= to turn on the AI scan
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed             # stations, games, FAQs, policies from the design
.venv/bin/python manage.py createsuperuser  # staff login for /admin
.venv/bin/python manage.py runserver 0.0.0.0:8000
.venv/bin/python manage.py test
```
- In **admin panel › Café settings**, set the real UPI ID, payee name, opening hours, support phone and maps link.
- Station types carry the per-seat hourly rate (seeded as PS5 ₹150, PS4 ₹100, PC ₹120; these are placeholders).
- **Email:** every code (signup verification, password reset) and every booking/ticket update is sent by email. The full list is in `docs/API.md`. SMTP is set in `backend/.env` (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USER`/`EMAIL_HOST_USER`, `EMAIL_PASS`/`EMAIL_HOST_PASSWORD`). With Gmail use `smtp.gmail.com`, port 587 and an App Password. Leave `EMAIL_HOST` empty to print emails in the console instead. Staff alerts go to `STAFF_ALERT_EMAILS`, or to every staff user if that's empty. Check the setup with `manage.py sendtestemail you@example.com`.
- New players must enter the emailed code before they can log in (`REQUIRE_EMAIL_VERIFICATION`). Accounts that existed before this change were marked verified.
- The AI model is set by `GROQ_MODEL` (default `qwen/qwen3.8-27b`, Groq's vision model, with strict JSON-schema output). The model only extracts the fields; every pass/fail decision is made in code (`bookings/ai.py`).

### Database (Postgres) and file storage (Cloudinary)
Both are switched on from `backend/.env`. With neither set, the app runs on SQLite with uploads in `backend/media/`, as before.
- **Postgres:** set `DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DBNAME`, plus `DATABASE_SSL=true` for hosted databases (Neon, Supabase, Render, RDS). Then run `migrate` and `seed` (or move existing data, below). Local Postgres: `docker run -d --name quodes-pg -e POSTGRES_USER=quodes -e POSTGRES_PASSWORD=quodes -e POSTGRES_DB=quodes -p 5432:5432 postgres:17`, then `DATABASE_URL=postgres://quodes:quodes@localhost:5432/quodes`.
- **Moving existing SQLite data to Postgres:** with `DATABASE_URL` still empty, run `manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e admin.logentry -e sessions --indent 2 > data.json`. Set `DATABASE_URL`, run `migrate`, then `loaddata data.json`.
- **Cloudinary:** set `CLOUDINARY_URL` (Cloudinary dashboard › Settings › API Keys › "API environment variable"). Everything goes under the `CLOUDINARY_FOLDER` folder (default `quodes/`):
  | Upload | Folder | Delivery |
  |---|---|---|
  | Game covers (admin › Games, or the app's admin panel) | `quodes/games/` | Public CDN URL, resized to max 1200px wide, auto quality |
  | Payment screenshots | `quodes/proofs/YYYY/MM/` | **Private** (`authenticated`): only signed URLs work, and the API gives them only to staff |
  | Support ticket attachments | `quodes/tickets/YYYY/MM/` | **Private**, same as screenshots |

  Replacing or removing a game cover deletes the old file. Payment screenshots are never deleted automatically, so the desk keeps the evidence. The AI scan downloads the screenshot through the storage layer, so it works the same on disk and on Cloudinary. Code: `quodes/storage.py`.
- Files uploaded to `media/` before Cloudinary was switched on are not moved automatically. Upload them to the same paths under `quodes/` in Cloudinary, or re-upload the covers in admin.

## Admin panel (`/admin`)
Log in with the superuser. Built with django-unfold in the app's blue.
- **Dashboard:** payments to verify, today's sessions, today's confirmed revenue, live locks, quick-add buttons, the verification queue (shows minutes left) and today's schedule.
- **Desk:** Verify payments (the sidebar badge shows the count), All bookings (each booking has the screenshot, AI checks and Approve/Reject buttons), Support tickets (change status, write a reply).
- **Café:** Games (cover image upload, tile colour pickers, platforms as checkboxes), Station types & rates (edit rates in the list, add stations inline; seats are created automatically), Stations (switch one off for maintenance), Café settings.
- **Content:** FAQs and Policies (sections inline). The app reads these live.
- **People:** Players & staff (adjust credit; tick "staff" to give desk access) and Staff roles (limit what non-owners can do).

## Mobile
Flutter app built with BLoC (flutter_bloc), go_router and Dio.

```bash
cd mobile && flutter pub get
# local (default): Android emulator talks to your Mac at 10.0.2.2:8000
flutter run
# real phone on the same Wi-Fi: point at your Mac's LAN IP
flutter run --dart-define=API_BASE=http://<mac-ip>:8000/api/
# stage / prod
flutter run --dart-define=FLAVOR=stage
flutter build appbundle --release --dart-define=FLAVOR=prod
```
One entrypoint (`lib/main.dart`); the environment comes from `--dart-define=FLAVOR=local|stage|prod` (default local). Non-prod builds show a corner banner. Plain HTTP is allowed in Android debug builds only. Server addresses are in `lib/core/config/env.dart`; the stage and prod ones are placeholders until the servers exist. Prod turns off HTTP logging and blocks plain-HTTP traffic.

```
lib/
  main.dart   single entrypoint (FLAVOR via --dart-define) → app/bootstrap.dart
  app/        DI (composition root), MaterialApp.router, BlocObserver
  core/
    config/   Flavor + AppConfig
    network/  ApiClient (Dio) + interceptors: auth (token + single-flight refresh),
              retry (GET only, backoff), logging (redacted, off in prod), error → ApiException
    router/   routes, go_router table, auth redirect, navigation helpers
    storage/  TokenStorage (flutter_secure_storage)
  data/       models + repositories (the only code that calls the API)
  features/<feature>/{bloc,view}   one cubit per screen; AuthBloc + BookingFlowCubit are app-wide
  theme/      colours, type, shared widgets
```
`flutter analyze` and `flutter test` (36 tests: redirects, AuthBloc, cubits, interceptors) should both be clean.

## Placeholders still to fill
Things the design left as `[...]` that are now settings or data: the UPI ID, rates, support phone, the reply time, and the `[X]` values in the policies and FAQ. The policies and FAQ are editable in the admin.
