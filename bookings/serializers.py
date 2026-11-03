from django.utils import timezone
from rest_framework import serializers

from catalog.models import CafeSettings
from catalog.serializers import GameSerializer

from .models import Booking


def upi_uri(booking, cafe):
    from urllib.parse import quote
    return (f"upi://pay?pa={quote(cafe.upi_id)}&pn={quote(cafe.upi_payee)}"
            f"&am={booking.amount_due:.2f}&cu=INR&tn={quote('Quodes ' + booking.code)}")


class BookingSerializer(serializers.ModelSerializer):
    game = GameSerializer(read_only=True)
    station_type = serializers.CharField(source="station_type.code")
    station_type_name = serializers.CharField(source="station_type.name")
    status_label = serializers.CharField(source="get_status_display")
    seats = serializers.SerializerMethodField()
    players = serializers.SerializerMethodField()
    station_label = serializers.CharField()
    date_label = serializers.CharField()
    time_label = serializers.CharField()
    subtotal = serializers.DecimalField(source="total", max_digits=10, decimal_places=2)
    amount_due = serializers.DecimalField(max_digits=10, decimal_places=2)
    upi_id = serializers.SerializerMethodField()
    upi_payee = serializers.SerializerMethodField()
    upi_uri = serializers.SerializerMethodField()
    server_time = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = ["id", "code", "status", "status_label", "game", "station_type", "station_type_name", "station_label",
                  "seats", "players", "date", "start_hour", "duration_hours", "date_label", "time_label",
                  "rate", "subtotal", "total", "credit_applied", "amount_due",
                  "upi_id", "upi_payee", "upi_uri",
                  "lock_expires_at", "verify_deadline", "created_at", "submitted_at", "ai_checked_at",
                  "confirmed_at", "released_at", "utr", "ai_checks", "ai_message", "server_time"]

    def _cafe(self):
        if not hasattr(self, "_cafe_cache"):
            self._cafe_cache = CafeSettings.get()
        return self._cafe_cache

    def get_seats(self, b):
        return [{"id": s.id, "code": s.code, "label": s.label, "station": s.station.code}
                for s in b.seats.select_related("station__type")]

    def get_players(self, b):
        return b.seats.count()

    def get_upi_id(self, b):
        return self._cafe().upi_id

    def get_upi_payee(self, b):
        return self._cafe().upi_payee

    def get_upi_uri(self, b):
        return upi_uri(b, self._cafe())

    def get_server_time(self, b):
        return timezone.now().isoformat()


class CreateBookingSerializer(serializers.Serializer):
    game = serializers.IntegerField()
    seat_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=4)
    date = serializers.DateField()
    start_hour = serializers.IntegerField(min_value=0, max_value=23)
    duration_hours = serializers.IntegerField(min_value=1, max_value=4)


class ProofSerializer(serializers.Serializer):
    screenshot = serializers.ImageField()
    utr = serializers.RegexField(r"^\d{12}$", required=False, allow_blank=True,
                                 error_messages={"invalid": "UTR is the 12-digit number in your UPI app."})

    def validate_screenshot(self, f):
        from django.conf import settings
        if f.size > settings.MAX_PROOF_BYTES:
            raise serializers.ValidationError("Screenshot must be under 5 MB.")
        fmt = getattr(getattr(f, "image", None), "format", None) or ""
        if fmt.upper() not in ("PNG", "JPEG", "WEBP"):
            raise serializers.ValidationError("Upload a PNG or JPG screenshot.")
        return f
