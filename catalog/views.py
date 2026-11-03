from datetime import date as Date, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from bookings.models import Booking, SeatHour
from bookings.services import sweep

from .models import CafeSettings, Game, Seat, Station, StationType, hour_label
from .serializers import GameSerializer

public = permission_classes([permissions.AllowAny])


def _date_param(request, required=False):
    raw = request.query_params.get("date")
    if not raw:
        if required:
            raise ValidationError({"date": "Required (YYYY-MM-DD)."})
        return timezone.localdate()
    try:
        return Date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({"date": "Use YYYY-MM-DD."})


def _busy_seat_ids(day, hour):
    return set(SeatHour.objects.filter(date=day, hour=hour).values_list("seat_id", flat=True))


@api_view(["GET"])
@public
def cafe(request):
    c = CafeSettings.get()
    return Response({
        "name": c.name, "open_now": c.open_now(), "open_hour": c.open_hour, "close_hour": c.close_hour,
        "opens_at": hour_label(c.open_hour), "closes_at": hour_label(c.close_hour),
        "upi_id": c.upi_id, "upi_payee": c.upi_payee, "lock_minutes": c.lock_minutes,
        "verify_hours": c.verify_hours, "support_phone": c.support_phone, "maps_url": c.maps_url,
        "reply_minutes": c.reply_minutes,
    })


@api_view(["GET"])
@public
def genres(request):
    return Response(["All"] + [g.title() if g != "OPEN WORLD" else "Open world" for g in Game.GENRES])


@api_view(["GET"])
@public
def games(request):
    qs = Game.objects.filter(is_active=True).prefetch_related("platforms")
    genre = (request.query_params.get("genre") or "").upper()
    if genre and genre != "ALL":
        qs = qs.filter(genre=genre)
    q = request.query_params.get("q")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(mono__icontains=q))
    return Response(GameSerializer(qs, many=True, context={"request": request}).data)


@api_view(["GET"])
@public
def station_types(request):
    sweep()
    now = timezone.localtime()
    busy = _busy_seat_ids(now.date(), now.hour)
    game = None
    if request.query_params.get("game"):
        game = Game.objects.filter(pk=request.query_params["game"]).first()
    allowed = set(game.platforms.values_list("pk", flat=True)) if game else None
    out = []
    for t in StationType.objects.all():
        seat_ids = list(Seat.objects.filter(station__type=t, station__is_active=True).values_list("id", flat=True))
        out.append({
            "code": t.code, "name": t.name, "spec": t.spec, "seats_per_station": t.seats_per_station,
            "hourly_rate": str(t.hourly_rate), "max_players": min(4, game.max_players) if game else 4,
            "total_seats": len(seat_ids), "free_seats": len([s for s in seat_ids if s not in busy]),
            "enabled": allowed is None or t.pk in allowed,
        })
    return Response(out)


@api_view(["GET"])
@public
def seatmap(request):
    sweep()
    t = StationType.objects.filter(code=request.query_params.get("type", "")).first()
    if not t:
        raise ValidationError({"type": "Unknown station type."})
    now = timezone.localtime()
    busy = _busy_seat_ids(now.date(), now.hour)
    stations = Station.objects.filter(type=t, is_active=True).prefetch_related("seats")
    return Response({
        "type": t.code, "seats_per_station": t.seats_per_station, "cols": t.grid_cols,
        "stations": [{"id": st.id, "code": st.code, "seats": [
            {"id": s.id, "code": s.code, "label": s.label, "busy": s.id in busy} for s in st.seats.all()
        ]} for st in stations],
    })


@api_view(["GET"])
@public
def availability(request):
    sweep()
    c = CafeSettings.get()
    day = _date_param(request)
    now = timezone.localtime()
    types = list(StationType.objects.prefetch_related("stations__seats"))
    held = {}
    for seat_id, hour in SeatHour.objects.filter(date=day).values_list("seat_id", "hour"):
        held.setdefault(hour, set()).add(seat_id)

    def free_stations(t, hour):
        busy = held.get(hour, set())
        return sum(1 for st in t.stations.all() if st.is_active and not any(s.id in busy for s in st.seats.all()))

    hours = [h for h in c.hours if not (day == now.date() and h < now.hour)]
    now_hour = now.hour if day == now.date() and c.open_now() else (hours[0] if hours else c.open_hour)
    return Response({
        "date": day.isoformat(),
        "types": [{"code": t.code, "name": t.name, "total": sum(1 for s in t.stations.all() if s.is_active),
                   "free_now": free_stations(t, now_hour)} for t in types],
        "hours": [{"hour": h, "label": hour_label(h), "free": {t.code: free_stations(t, h) for t in types}}
                  for h in hours],
    })


@api_view(["GET"])
@public
def slots(request):
    sweep()
    c = CafeSettings.get()
    day = _date_param(request, required=True)
    try:
        seat_ids = [int(x) for x in request.query_params.get("seats", "").split(",") if x]
    except ValueError:
        raise ValidationError({"seats": "Comma-separated seat ids."})
    rows = SeatHour.objects.filter(date=day, seat_id__in=seat_ids).values_list("hour", "booking__status")
    state = {}
    for hour, status in rows:
        tentative = status in Booking.TENTATIVE
        # "booked" wins over "hold" if seats disagree.
        if state.get(hour) != "booked":
            state[hour] = "hold" if tentative else "booked"
    now = timezone.localtime()
    return Response({"date": day.isoformat(), "hours": [{
        "hour": h, "label": hour_label(h),
        "status": "past" if (day < now.date() or (day == now.date() and h < now.hour)) else state.get(h, "open"),
    } for h in c.hours]})


@api_view(["GET"])
@public
def dates(request):
    c = CafeSettings.get()
    today = timezone.localdate()
    out = []
    for i in range(c.booking_days_ahead):
        d = today + timedelta(days=i)
        out.append({"date": d.isoformat(), "dow": d.strftime("%a").upper(), "num": d.day, "mon": d.strftime("%b")})
    return Response(out)
