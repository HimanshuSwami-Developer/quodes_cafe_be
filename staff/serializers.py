"""Serializers for the staff (admin panel) API. Separate from the player API so
staff-only fields never leak to players."""
from rest_framework import serializers

from accounts.models import User
from bookings.models import Booking
from bookings.serializers import BookingSerializer
from catalog.models import CafeSettings, Game, Station, StationType
from catalog.serializers import file_url
from support.models import FAQ, Policy, PolicySection, Ticket


class StaffBookingSerializer(BookingSerializer):
    player = serializers.SerializerMethodField()
    screenshot_url = serializers.SerializerMethodField()
    reviewed_by = serializers.CharField(source="reviewed_by.email", default=None)

    class Meta(BookingSerializer.Meta):
        fields = BookingSerializer.Meta.fields + [
            "player", "screenshot_url", "ai_raw", "staff_note", "reviewed_by", "rebooked_from"]

    def get_player(self, b):
        u = b.user
        return {"id": u.id, "email": u.email, "gamertag": u.gamertag, "full_name": u.full_name,
                "phone": u.phone, "credit": str(u.credit)}

    def get_screenshot_url(self, b):
        return file_url(b.screenshot, self.context.get("request"))


class StationTypeAdminSerializer(serializers.ModelSerializer):
    station_count = serializers.SerializerMethodField()

    class Meta:
        model = StationType
        fields = ["id", "code", "name", "spec", "seats_per_station", "hourly_rate", "seat_prefix",
                  "grid_cols", "sort", "station_count"]

    def get_station_count(self, t):
        return t.stations.filter(is_active=True).count()


class StationAdminSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    type_code = serializers.CharField(source="type.code", read_only=True)
    type_name = serializers.CharField(source="type.name", read_only=True)
    seat_count = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = ["id", "type", "type_code", "type_name", "number", "code", "is_active", "seat_count"]

    def get_seat_count(self, st):
        return st.seats.count()


class GameAdminSerializer(serializers.ModelSerializer):
    platforms = serializers.SlugRelatedField(many=True, slug_field="code", queryset=StationType.objects.all())
    cover_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ["id", "name", "mono", "genre", "hue", "deep", "platforms", "max_players", "is_active", "sort",
                  "cover_url", "banner_url"]

    def get_cover_url(self, g):
        return file_url(g.cover, self.context.get("request"))

    def get_banner_url(self, g):
        return file_url(g.banner, self.context.get("request"))

    def validate_hue(self, v):
        return _hex(v)

    def validate_deep(self, v):
        return _hex(v)


def _hex(v):
    import re
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v or ""):
        raise serializers.ValidationError("Use a colour like #2F6BFF.")
    return v.upper()


class CafeSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CafeSettings
        exclude = ["id"]


class FAQAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["id", "question", "answer", "sort"]


class SectionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicySection
        fields = ["id", "heading", "body", "sort"]


class PolicyAdminSerializer(serializers.ModelSerializer):
    sections = SectionAdminSerializer(many=True, required=False)

    class Meta:
        model = Policy
        fields = ["id", "key", "title", "sort", "updated", "sections"]
        read_only_fields = ["updated"]

    def _save_sections(self, policy, sections):
        if sections is None:
            return
        policy.sections.all().delete()
        for i, s in enumerate(sections):
            PolicySection.objects.create(policy=policy, heading=s["heading"], body=s["body"],
                                         sort=s.get("sort", i))

    def create(self, data):
        sections = data.pop("sections", [])
        p = Policy.objects.create(**data)
        self._save_sections(p, sections)
        return p

    def update(self, p, data):
        sections = data.pop("sections", None)
        for k, v in data.items():
            setattr(p, k, v)
        p.save()
        self._save_sections(p, sections)
        return p


class TicketAdminSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    player = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = ["id", "number", "player", "topic", "booking_code", "message", "attachment_url", "status",
                  "status_label", "staff_reply", "created_at", "updated_at"]
        read_only_fields = ["topic", "booking_code", "message", "created_at", "updated_at"]

    def get_player(self, t):
        return {"id": t.user_id, "email": t.user.email, "gamertag": t.user.gamertag}

    def get_attachment_url(self, t):
        return file_url(t.attachment, self.context.get("request"))


class UserAdminSerializer(serializers.ModelSerializer):
    bookings = serializers.IntegerField(source="bookings.count", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "gamertag", "full_name", "phone", "credit", "email_verified",
                  "is_active", "is_staff", "date_joined", "last_login", "bookings"]
        read_only_fields = ["email", "date_joined", "last_login"]


class CoverSerializer(serializers.Serializer):
    """Validates one uploaded game image; the field name is `cover` or `banner`."""

    def __init__(self, *args, field="cover", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[field] = serializers.ImageField(validators=[self.check_image])

    @staticmethod
    def check_image(f):
        from django.conf import settings
        if f.size > settings.MAX_COVER_BYTES:
            raise serializers.ValidationError("Image must be under 5 MB.")
        fmt = getattr(getattr(f, "image", None), "format", None) or ""
        if fmt.upper() not in ("PNG", "JPEG", "WEBP"):
            raise serializers.ValidationError("Upload a PNG, JPG or WebP image.")


class RejectSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)
