"""Booking state machine: lock → pay → AI scan → human verification → confirmed."""
import logging
import threading
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from catalog.models import CafeSettings, Seat

from . import notify
from .models import Booking, SeatHour

log = logging.getLogger(__name__)
S = Booking.Status
MAX_PLAYERS = 4
MAX_HOURS = 4


class BookingError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---- holds -----------------------------------------------------------------

def _free_hold(booking):
    booking.seat_hours.all().delete()


def _take_hold(booking, seats):
    rows = [SeatHour(booking=booking, seat=s, date=booking.date, hour=h)
            for s in seats for h in booking.hours]
    try:
        with transaction.atomic():
            SeatHour.objects.bulk_create(rows)
    except IntegrityError:
        raise BookingError("Someone just grabbed one of those seats. Pick another time or seat.", 409)


def sweep(now=None):
    """Expire stale locks and release unverified bookings. Cheap; called on every
    booking/availability request and by `manage.py sweep_bookings`."""
    now = now or timezone.now()
    for b in Booking.objects.filter(status__in=[S.LOCKED, S.AI_FAILED], lock_expires_at__lt=now):
        with transaction.atomic():
            _free_hold(b)
            b.status = S.EXPIRED
            b.save(update_fields=["status"])
            notify.expired(b)
    # A scan that never finished (crashed worker) falls through to the team.
    stuck = now - timedelta(minutes=5)
    for b in Booking.objects.filter(status=S.SCANNING, submitted_at__lt=stuck):
        _to_human(b, "AI scan timed out, our team will check it.")
    for b in Booking.objects.filter(status=S.PENDING_HUMAN, verify_deadline__lt=now):
        release(b, now)


def release(booking, now=None):
    """Team didn't verify in time: free the seats, keep the money as credit."""
    with transaction.atomic():
        _free_hold(booking)
        booking.status = S.RELEASED
        booking.released_at = now or timezone.now()
        booking.save(update_fields=["status", "released_at"])
        paid = booking.amount_due
        if paid > 0:
            type(booking.user).objects.filter(pk=booking.user_id).update(credit=F("credit") + paid)
        notify.released(booking)


# ---- create ------------------------------------------------------------------

def validate_request(cafe, seats, date, start_hour, duration):
    if not seats:
        raise BookingError("Pick at least one seat.")
    if len(seats) > MAX_PLAYERS:
        raise BookingError(f"Max {MAX_PLAYERS} players per booking.")
    if len({s.station.type_id for s in seats}) != 1:
        raise BookingError("All seats must be on the same station type.")
    if not 1 <= duration <= MAX_HOURS:
        raise BookingError(f"Sessions are 1–{MAX_HOURS} hours.")
    today = timezone.localdate()
    if date < today or date > today + timedelta(days=cafe.booking_days_ahead - 1):
        raise BookingError("That date isn't open for booking.")
    if start_hour < cafe.open_hour or start_hour + duration > cafe.close_hour:
        raise BookingError("Session runs past closing time.")
    if date == today and start_hour <= timezone.localtime().hour - 1:
        raise BookingError("That time has already passed.")


def create_booking(user, game, seat_ids, date, start_hour, duration):
    cafe = CafeSettings.get()
    sweep()
    seats = list(Seat.objects.select_related("station__type").filter(id__in=seat_ids, station__is_active=True))
    if len(seats) != len(set(seat_ids)):
        raise BookingError("One of those seats doesn't exist.")
    validate_request(cafe, seats, date, start_hour, duration)
    stype = seats[0].station.type
    if not game.platforms.filter(pk=stype.pk).exists():
        raise BookingError(f"{game.name} isn't available on {stype.name}.")
    if len(seats) > game.max_players:
        raise BookingError(f"{game.name} supports up to {game.max_players} players.")
    if Booking.objects.filter(user=user, status__in=Booking.TENTATIVE).count() >= 2:
        raise BookingError("You already have unpaid locks. Pay or unlock them first.", 409)

    total = stype.hourly_rate * len(seats) * duration
    with transaction.atomic():
        b = Booking.objects.create(
            user=user, game=game, station_type=stype, date=date, start_hour=start_hour,
            duration_hours=duration, rate=stype.hourly_rate, total=total,
            lock_expires_at=timezone.now() + timedelta(minutes=cafe.lock_minutes))
        b.seats.set(seats)
        _take_hold(b, seats)
        notify.locked(b)
    return b


def cancel(booking):
    if booking.status not in (S.LOCKED, S.AI_FAILED):
        raise BookingError("This booking can't be unlocked any more.")
    with transaction.atomic():
        _free_hold(booking)
        booking.status = S.CANCELLED
        booking.save(update_fields=["status"])


def rebook_with_credit(booking):
    """From a released booking: re-take the same seats/time paid from credit."""
    if booking.status != S.RELEASED:
        raise BookingError("Only released bookings can be rebooked with credit.")
    user = type(booking.user).objects.get(pk=booking.user_id)
    if user.credit < booking.total:
        raise BookingError("Not enough credit for this session.")
    if booking.starts_at < timezone.now() - timedelta(minutes=30):
        raise BookingError("That session time has passed. Pick another slot.", 409)
    cafe = CafeSettings.get()
    seats = list(booking.seats.all())
    with transaction.atomic():
        nb = Booking.objects.create(
            user=user, game=booking.game, station_type=booking.station_type, date=booking.date,
            start_hour=booking.start_hour, duration_hours=booking.duration_hours, rate=booking.rate,
            total=booking.total, credit_applied=booking.total, status=S.CONFIRMED,
            lock_expires_at=timezone.now() + timedelta(minutes=cafe.lock_minutes),
            confirmed_at=timezone.now(), rebooked_from=booking, utr=booking.utr,
            ai_message="Paid with game credit")
        nb.seats.set(seats)
        _take_hold(nb, seats)
        type(user).objects.filter(pk=user.pk).update(credit=F("credit") - booking.total)
        notify.confirmed(nb)
    return nb


# ---- payment proof -------------------------------------------------------------

PENDING_CHECKS = [
    ("read", "Reading screenshot", "Text and amounts extracted"),
    ("amount", "Amount matches", ""),
    ("payee", "Payee UPI ID matches", ""),
    ("utr", "UTR not used before", "Duplicate-proof check"),
    ("time", "Paid within lock window", "Timestamp vs. slot lock"),
]


def pending_checks(booking):
    cafe = CafeSettings.get()
    detail = {"amount": f"₹{booking.amount_due:,.0f}", "payee": cafe.upi_id}
    return [{"key": k, "label": l, "detail": detail.get(k, d), "status": "pending"}
            for k, l, d in PENDING_CHECKS]


def submit_proof(booking, screenshot, utr=""):
    if booking.status not in (S.LOCKED, S.AI_FAILED):
        raise BookingError("This booking isn't waiting for payment.")
    if booking.lock_expires_at < timezone.now():
        raise BookingError("Your lock ran out. Contact support if you already paid.", 409)
    utr = (utr or "").strip()
    if utr and Booking.objects.filter(utr=utr).exclude(pk=booking.pk).exclude(
            status__in=[S.CANCELLED, S.EXPIRED]).exists():
        raise BookingError("That UTR was already used for another booking.", 409)
    booking.screenshot = screenshot
    booking.utr = utr
    booking.status = S.SCANNING
    booking.submitted_at = timezone.now()
    booking.ai_checks = pending_checks(booking)
    booking.ai_message = ""
    booking.save()

    if settings.AI_VERIFY_ASYNC:
        threading.Thread(target=_scan_in_thread, args=(booking.pk,), daemon=True).start()
    else:
        run_scan(booking.pk)


def _scan_in_thread(pk):
    try:
        run_scan(pk)
    finally:
        close_old_connections()


def _to_human(booking, message, checks=None):
    cafe = CafeSettings.get()
    now = timezone.now()
    booking.status = S.PENDING_HUMAN
    booking.ai_checked_at = now
    booking.verify_deadline = now + timedelta(hours=cafe.verify_hours)
    booking.ai_message = message
    if checks is not None:
        booking.ai_checks = checks
    booking.save()
    notify.pending(booking)


def run_scan(pk):
    from .ai import scan_payment  # lazy: keeps the SDK import off the request path

    booking = Booking.objects.select_related("user").get(pk=pk)
    if booking.status != S.SCANNING:
        return
    try:
        result = scan_payment(booking)
    except Exception:  # never strand a paid player because the AI step broke
        log.exception("AI scan crashed for %s", booking.code)
        result = None

    if result is None:
        checks = [{**c, "status": "pending", "detail": "Our team will check this"} for c in pending_checks(booking)]
        _to_human(booking, "Auto-check unavailable, our team will verify your payment.", checks)
        return

    checks, extracted = result
    booking.ai_raw = extracted
    if not booking.utr and extracted.get("utr"):
        booking.utr = extracted["utr"][:32]
    if all(c["status"] == "pass" for c in checks):
        _to_human(booking, "AI check passed. Our team confirms it in bank records.", checks)
    else:
        booking.status = S.AI_FAILED
        booking.ai_checks = checks
        booking.ai_checked_at = timezone.now()
        booking.ai_message = next(c["detail"] for c in checks if c["status"] == "fail")
        booking.save()
        notify.ai_failed(booking)


def request_manual_review(booking):
    if booking.status != S.AI_FAILED:
        raise BookingError("Manual review is only for failed scans.")
    _to_human(booking, "Sent for manual review. Our team responds within "
              f"{CafeSettings.get().verify_hours} hours.")


# ---- staff ------------------------------------------------------------------

def approve(booking, staff):
    if booking.status not in (S.PENDING_HUMAN, S.AI_FAILED, S.SCANNING):
        raise BookingError(f"Can't approve a booking that is {booking.get_status_display().lower()}.")
    booking.status = S.CONFIRMED
    booking.confirmed_at = timezone.now()
    booking.reviewed_by = staff
    booking.save()
    notify.confirmed(booking)


def reject(booking, staff, note=""):
    if booking.status not in (S.PENDING_HUMAN, S.AI_FAILED, S.SCANNING):
        raise BookingError("Only bookings waiting for verification can be rejected.")
    with transaction.atomic():
        _free_hold(booking)
        booking.status = S.REJECTED
        booking.reviewed_by = staff
        booking.staff_note = note[:300]
        booking.save()
        notify.rejected(booking)
