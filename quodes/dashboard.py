"""Admin dashboard (django-unfold DASHBOARD_CALLBACK) and sidebar badges."""
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from bookings.models import Booking
from bookings.services import sweep
from catalog.models import CafeSettings, Game, Station
from support.models import Ticket

S = Booking.Status


def verify_badge(request):
    n = Booking.objects.filter(status=S.PENDING_HUMAN).count()
    return n or None


def ticket_badge(request):
    n = Ticket.objects.exclude(status=Ticket.Status.RESOLVED).count()
    return n or None


def _link(b):
    return format_html('<a class="text-primary-600 font-semibold" href="{}">{}</a>',
                       reverse("admin:bookings_booking_change", args=[b.pk]), b.code)


def dashboard_callback(request, context):
    sweep()
    now = timezone.now()
    today = timezone.localdate()
    queue = list(Booking.objects.filter(status=S.PENDING_HUMAN).select_related("user", "station_type")
                 .prefetch_related("seats__station__type").order_by("verify_deadline")[:10])
    todays = list(Booking.objects.filter(date=today, status__in=[S.CONFIRMED, S.PENDING_HUMAN])
                  .select_related("user", "game", "station_type").prefetch_related("seats__station__type")
                  .order_by("start_hour"))
    revenue = Booking.objects.filter(status=S.CONFIRMED, confirmed_at__date=today) \
        .aggregate(t=Sum("total"))["t"] or Decimal("0")

    def mins_left(b):
        m = int((b.verify_deadline - now).total_seconds() // 60)
        return format_html('<span class="{}">{} min</span>', "text-red-600 font-semibold" if m < 30 else "", m)

    context.update({
        "cafe": CafeSettings.get(),
        "kpis": [
            {"title": "Payments to verify", "value": len(queue), "icon": "verified",
             "href": reverse("admin:bookings_booking_changelist") + "?queue=verify"},
            {"title": "Sessions today", "value": len(todays), "icon": "event_seat",
             "href": reverse("admin:bookings_booking_changelist") + f"?date={today.isoformat()}"},
            {"title": "Confirmed revenue today", "value": f"₹{revenue:,.0f}", "icon": "payments", "href": None},
            {"title": "Live slot locks", "value": Booking.objects.filter(status__in=Booking.TENTATIVE).count(),
             "icon": "lock_clock", "href": reverse("admin:bookings_booking_changelist") + "?status__exact=locked"},
        ],
        "queue_table": {
            "headers": ["Booking", "Player", "Slot", "Amount", "UTR", "Time left"],
            "rows": [[_link(b), str(b.user), f"{b.date_label} · {b.time_label} · {b.station_label}",
                      f"₹{b.amount_due:,.0f}", b.utr or "—", mins_left(b)] for b in queue],
        },
        "today_table": {
            "headers": ["Time", "Booking", "Player", "Game", "Seats", "Status"],
            "rows": [[b.time_label, _link(b), str(b.user), b.game.name,
                      ", ".join(s.code for s in b.seats.all()), b.get_status_display()] for b in todays],
        },
        "quick_add": [
            {"title": "Add game", "icon": "stadia_controller", "href": reverse("admin:catalog_game_add")},
            {"title": "Add station", "icon": "chair", "href": reverse("admin:catalog_station_add")},
            {"title": "Add station type", "icon": "devices", "href": reverse("admin:catalog_stationtype_add")},
            {"title": "Add FAQ", "icon": "help", "href": reverse("admin:support_faq_add")},
            {"title": "Add policy", "icon": "gavel", "href": reverse("admin:support_policy_add")},
            {"title": "Add staff / player", "icon": "person_add", "href": reverse("admin:accounts_user_add")},
            {"title": "Café settings", "icon": "storefront",
             "href": reverse("admin:catalog_cafesettings_change", args=[1])},
        ],
        "counts": {"games": Game.objects.filter(is_active=True).count(),
                   "stations": Station.objects.filter(is_active=True).count()},
    })
    return context
