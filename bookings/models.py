import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from catalog.models import Game, Seat, StationType, hour_label
from quodes.storage import private_storage


def new_code():
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    return "QG-" + "".join(secrets.choice(alphabet) for _ in range(6))


def proof_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"proofs/{timezone.now():%Y/%m}/{instance.code}-{secrets.token_hex(4)}.{ext}"


class BookingQuerySet(models.QuerySet):
    def played_by(self, user):
        today = timezone.localdate()
        return self.filter(user=user, status=Booking.Status.CONFIRMED, date__lte=today)


class Booking(models.Model):
    class Status(models.TextChoices):
        LOCKED = "locked", "Slot locked"
        SCANNING = "scanning", "AI scanning"
        AI_FAILED = "ai_failed", "AI scan failed"
        PENDING_HUMAN = "pending_human", "Team verification pending"
        CONFIRMED = "confirmed", "Confirmed"
        EXPIRED = "expired", "Lock expired"
        RELEASED = "released", "Slot released"
        REJECTED = "rejected", "Payment rejected"
        CANCELLED = "cancelled", "Cancelled"

    # Statuses that hold the seats.
    HOLDING = [Status.LOCKED, Status.SCANNING, Status.AI_FAILED, Status.PENDING_HUMAN, Status.CONFIRMED]
    # Statuses where seats are held but not yet confirmed (shown as "hold" in the slot grid).
    TENTATIVE = [Status.LOCKED, Status.SCANNING, Status.AI_FAILED]

    code = models.CharField(max_length=12, unique=True, default=new_code, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    game = models.ForeignKey(Game, on_delete=models.PROTECT)
    station_type = models.ForeignKey(StationType, on_delete=models.PROTECT)
    seats = models.ManyToManyField(Seat, related_name="bookings")
    date = models.DateField()
    start_hour = models.PositiveSmallIntegerField()
    duration_hours = models.PositiveSmallIntegerField()

    rate = models.DecimalField(max_digits=8, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    credit_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.LOCKED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    lock_expires_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    ai_checked_at = models.DateTimeField(null=True, blank=True)
    verify_deadline = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    screenshot = models.ImageField(upload_to=proof_path, storage=private_storage, blank=True)
    utr = models.CharField("UTR / transaction ID", max_length=32, blank=True, db_index=True)
    ai_checks = models.JSONField(default=list, blank=True)
    ai_message = models.CharField(max_length=300, blank=True)
    ai_raw = models.JSONField(null=True, blank=True, help_text="What the AI read from the screenshot")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    staff_note = models.CharField(max_length=300, blank=True)
    rebooked_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} · {self.user} · {self.date} {self.time_label}"

    # ---- derived ---------------------------------------------------------
    @property
    def end_hour(self):
        return self.start_hour + self.duration_hours

    @property
    def hours(self):
        return range(self.start_hour, self.end_hour)

    @property
    def amount_due(self):
        return max(self.total - self.credit_applied, Decimal("0"))

    @property
    def time_label(self):
        return f"{hour_label(self.start_hour)} – {hour_label(self.end_hour)}"

    @property
    def date_label(self):
        return self.date.strftime("%a, %-d %b")

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.date, datetime.min.time())) + timedelta(hours=self.start_hour)

    @property
    def station_label(self):
        stations = sorted({s.station.number for s in self.seats.all()})
        return f"{self.station_type.name} · {', '.join(f'#{n:02d}' for n in stations)}"


class SeatHour(models.Model):
    """One row per (seat, date, hour) a live booking holds. The unique constraint is
    what stops two players from ever holding the same seat-hour."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="seat_hours")
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name="seat_hours")
    date = models.DateField()
    hour = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seat", "date", "hour"], name="one_booking_per_seat_hour")]
        indexes = [models.Index(fields=["date", "hour"])]
