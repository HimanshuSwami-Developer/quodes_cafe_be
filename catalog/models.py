from decimal import Decimal

from django.db import models
from django.utils import timezone


def hour_label(h):
    h %= 24
    return f"{12 if h % 12 == 0 else h % 12} {'PM' if h >= 12 else 'AM'}"


class CafeSettings(models.Model):
    """Singleton with café-wide settings. Edit it in the admin."""

    name = models.CharField(max_length=80, default="Quodes Gaming")
    open_hour = models.PositiveSmallIntegerField(default=10, help_text="First bookable hour (0-23)")
    close_hour = models.PositiveSmallIntegerField(default=24, help_text="Closing hour (1-24, 24 = midnight)")
    upi_id = models.CharField(max_length=80, default="quodes@upi")
    upi_payee = models.CharField(max_length=80, default="Quodes Gaming")
    lock_minutes = models.PositiveSmallIntegerField(default=10)
    verify_hours = models.PositiveSmallIntegerField(default=2)
    support_phone = models.CharField(max_length=20, blank=True)
    maps_url = models.URLField(blank=True)
    reply_minutes = models.PositiveSmallIntegerField(default=10)
    booking_days_ahead = models.PositiveSmallIntegerField(default=7)

    class Meta:
        verbose_name = verbose_name_plural = "Café settings"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def hours(self):
        return list(range(self.open_hour, self.close_hour))

    def open_now(self):
        h = timezone.localtime().hour
        return self.open_hour <= h < self.close_hour


class StationType(models.Model):
    code = models.CharField(max_length=8, unique=True, help_text="Internal ID (PS5 / PS4 / PC); players see the name")
    name = models.CharField(max_length=40, help_text="Shown to players, e.g. Station 5")
    spec = models.CharField(max_length=120, blank=True)
    seats_per_station = models.PositiveSmallIntegerField(default=2)
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("100"),
                                      help_text="Price per seat per hour (₹)")
    seat_prefix = models.CharField(max_length=4, help_text="e.g. S5 → seat codes S5-04-1")
    grid_cols = models.PositiveSmallIntegerField(default=3)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "code"]

    def __str__(self):
        return self.code


class Station(models.Model):
    type = models.ForeignKey(StationType, on_delete=models.CASCADE, related_name="stations")
    number = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["type__sort", "number"]
        unique_together = [("type", "number")]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Every station gets one seat per player slot of its type.
        for i in range(1, self.type.seats_per_station + 1):
            Seat.objects.get_or_create(station=self, index=i)

    @property
    def code(self):
        return f"{self.type.seat_prefix}-{self.number:02d}"

    @property
    def label(self):
        return f"{self.type.name} · #{self.number:02d}"


class Seat(models.Model):
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="seats")
    index = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["station__type__sort", "station__number", "index"]
        unique_together = [("station", "index")]

    def __str__(self):
        return self.code

    @property
    def code(self):
        return f"{self.station.code}-{self.index}"

    @property
    def label(self):
        return f"P{self.index}"


class Game(models.Model):
    GENRES = ["SHOOTER", "SPORTS", "RACING", "FIGHTING", "OPEN WORLD", "ACTION"]

    name = models.CharField(max_length=80)
    mono = models.CharField(max_length=6, help_text="Short tile label, e.g. FC25")
    genre = models.CharField(max_length=20, choices=[(g, g.title()) for g in GENRES])
    hue = models.CharField(max_length=7, default="#2F6BFF")
    deep = models.CharField(max_length=7, default="#111C42")
    platforms = models.ManyToManyField(StationType, related_name="games")
    max_players = models.PositiveSmallIntegerField(default=4)
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name
