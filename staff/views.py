"""Staff-only REST API behind the Flutter web admin panel (/admin in the app).
Every endpoint requires a logged-in user with is_staff."""
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from accounts.models import User
from bookings import services
from bookings.models import Booking
from catalog.models import CafeSettings, Game, Station, StationType
from support import notify as ticket_notify
from support.models import FAQ, Policy, Ticket

from .serializers import (CafeSettingsSerializer, FAQAdminSerializer, GameAdminSerializer,
                          PolicyAdminSerializer, RejectSerializer, StaffBookingSerializer,
                          StationAdminSerializer, StationTypeAdminSerializer, TicketAdminSerializer,
                          UserAdminSerializer)

S = Booking.Status
staff_only = [permissions.IsAdminUser]


def _bookings_qs():
    return Booking.objects.select_related("user", "game", "station_type", "reviewed_by") \
        .prefetch_related("seats__station__type", "game__platforms")


@api_view(["GET"])
@permission_classes(staff_only)
def dashboard(request):
    services.sweep()
    today = timezone.localdate()
    queue = list(_bookings_qs().filter(status=S.PENDING_HUMAN).order_by("verify_deadline")[:20])
    todays = list(_bookings_qs().filter(date=today, status__in=[S.CONFIRMED, S.PENDING_HUMAN])
                  .order_by("start_hour"))
    revenue = Booking.objects.filter(status=S.CONFIRMED, confirmed_at__date=today) \
        .aggregate(t=Sum("total"))["t"] or Decimal("0")
    ctx = {"request": request}
    return Response({
        "kpis": {
            "to_verify": Booking.objects.filter(status=S.PENDING_HUMAN).count(),
            "sessions_today": len(todays),
            "revenue_today": str(revenue),
            "live_locks": Booking.objects.filter(status__in=Booking.TENTATIVE).count(),
            "open_tickets": Ticket.objects.exclude(status=Ticket.Status.RESOLVED).count(),
            "players": User.objects.filter(is_staff=False).count(),
        },
        "queue": StaffBookingSerializer(queue, many=True, context=ctx).data,
        "today": StaffBookingSerializer(todays, many=True, context=ctx).data,
        "server_time": timezone.now().isoformat(),
    })


class BookingAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """?status=pending_human&date=YYYY-MM-DD&q=code/utr/email&queue=verify"""
    permission_classes = staff_only
    serializer_class = StaffBookingSerializer

    def get_queryset(self):
        services.sweep()
        qs = _bookings_qs()
        p = self.request.query_params
        if p.get("queue") == "verify":
            return qs.filter(status=S.PENDING_HUMAN).order_by("verify_deadline")
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("date"):
            qs = qs.filter(date=p["date"])
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(Q(code__icontains=q) | Q(utr__icontains=q) | Q(user__email__icontains=q)
                           | Q(user__gamertag__icontains=q) | Q(user__phone__icontains=q))
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()[:200]
        return Response(self.get_serializer(qs, many=True).data)

    def _act(self, request, fn):
        b = self.get_object()
        try:
            fn(b)
        except services.BookingError as e:
            return Response({"detail": str(e)}, status=e.status)
        b.refresh_from_db()
        return Response(self.get_serializer(b).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._act(request, lambda b: services.approve(b, request.user))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        s = RejectSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        note = s.validated_data.get("note") or "Payment not found in bank records"
        return self._act(request, lambda b: services.reject(b, request.user, note))


class GameAdminViewSet(viewsets.ModelViewSet):
    permission_classes = staff_only
    serializer_class = GameAdminSerializer
    queryset = Game.objects.prefetch_related("platforms").order_by("sort", "name")


class StationTypeAdminViewSet(viewsets.ModelViewSet):
    permission_classes = staff_only
    serializer_class = StationTypeAdminSerializer
    queryset = StationType.objects.prefetch_related("stations").all()


class StationAdminViewSet(viewsets.ModelViewSet):
    """Creating a station also creates its seats (one per player slot)."""
    permission_classes = staff_only
    serializer_class = StationAdminSerializer

    def get_queryset(self):
        qs = Station.objects.select_related("type").prefetch_related("seats")
        if self.request.query_params.get("type"):
            qs = qs.filter(type__code=self.request.query_params["type"])
        return qs


class FAQAdminViewSet(viewsets.ModelViewSet):
    permission_classes = staff_only
    serializer_class = FAQAdminSerializer
    queryset = FAQ.objects.all()


class PolicyAdminViewSet(viewsets.ModelViewSet):
    permission_classes = staff_only
    serializer_class = PolicyAdminSerializer
    queryset = Policy.objects.prefetch_related("sections")


class TicketAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                         viewsets.GenericViewSet):
    """PATCH status / staff_reply; the player gets an email when either changes."""
    permission_classes = staff_only
    serializer_class = TicketAdminSerializer

    def get_queryset(self):
        qs = Ticket.objects.select_related("user")
        st = self.request.query_params.get("status")
        if st == "open":
            qs = qs.exclude(status=Ticket.Status.RESOLVED)
        elif st:
            qs = qs.filter(status=st)
        return qs

    def perform_update(self, serializer):
        before = (serializer.instance.status, serializer.instance.staff_reply)
        t = serializer.save()
        if (t.status, t.staff_reply) != before:
            ticket_notify.updated(t)


class UserAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                       viewsets.GenericViewSet):
    """?q=email/gamertag/phone&staff=1. PATCH credit / is_active / is_staff / email_verified."""
    permission_classes = staff_only
    serializer_class = UserAdminSerializer

    def get_queryset(self):
        qs = User.objects.order_by("-date_joined")
        p = self.request.query_params
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(email__icontains=q) | Q(gamertag__icontains=q) | Q(phone__icontains=q)
                           | Q(full_name__icontains=q))
        if p.get("staff") == "1":
            qs = qs.filter(is_staff=True)
        return qs

    def list(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_queryset()[:200], many=True).data)

    def perform_update(self, serializer):
        u = self.request.user
        target = serializer.instance
        # Only superusers may grant/revoke staff, and nobody can lock themselves out.
        if "is_staff" in serializer.validated_data and not u.is_superuser:
            serializer.validated_data.pop("is_staff")
        if target.pk == u.pk:
            serializer.validated_data.pop("is_staff", None)
            serializer.validated_data.pop("is_active", None)
        serializer.save()


@api_view(["GET", "PATCH"])
@permission_classes(staff_only)
def cafe_settings(request):
    obj = CafeSettings.get()
    if request.method == "PATCH":
        s = CafeSettingsSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
    return Response(CafeSettingsSerializer(obj).data)
