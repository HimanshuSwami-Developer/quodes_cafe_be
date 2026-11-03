from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Game

from . import services
from .models import Booking
from .serializers import BookingSerializer, CreateBookingSerializer, ProofSerializer


def _err(e: services.BookingError):
    return Response({"detail": str(e)}, status=e.status)


def _mine(request, pk):
    return get_object_or_404(
        Booking.objects.select_related("game", "station_type", "user").prefetch_related("game__platforms"),
        pk=pk, user=request.user)


def _out(b, code=200):
    b.refresh_from_db()
    return Response(BookingSerializer(b).data, status=code)


class BookingListView(APIView):
    def get(self, request):
        services.sweep()
        qs = Booking.objects.filter(user=request.user).select_related("game", "station_type") \
            .prefetch_related("game__platforms")
        if request.query_params.get("active"):
            S = Booking.Status
            qs = qs.filter(status__in=[S.LOCKED, S.SCANNING, S.AI_FAILED, S.PENDING_HUMAN, S.CONFIRMED],
                           date__gte=timezone.localdate())
        return Response(BookingSerializer(qs[:50], many=True).data)

    def post(self, request):
        s = CreateBookingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        game = get_object_or_404(Game, pk=d["game"], is_active=True)
        try:
            b = services.create_booking(request.user, game, d["seat_ids"], d["date"],
                                        d["start_hour"], d["duration_hours"])
        except services.BookingError as e:
            return _err(e)
        return _out(b, status.HTTP_201_CREATED)


@api_view(["GET"])
def booking_detail(request, pk):
    services.sweep()
    return _out(_mine(request, pk))


@api_view(["POST"])
def booking_cancel(request, pk):
    b = _mine(request, pk)
    try:
        services.cancel(b)
    except services.BookingError as e:
        return _err(e)
    return _out(b)


class ProofView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, pk):
        services.sweep()
        b = _mine(request, pk)
        s = ProofSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.submit_proof(b, s.validated_data["screenshot"], s.validated_data.get("utr", ""))
        except services.BookingError as e:
            return _err(e)
        return _out(b)


@api_view(["POST"])
def booking_manual_review(request, pk):
    b = _mine(request, pk)
    try:
        services.request_manual_review(b)
    except services.BookingError as e:
        return _err(e)
    return _out(b)


@api_view(["POST"])
def booking_rebook(request, pk):
    b = _mine(request, pk)
    try:
        nb = services.rebook_with_credit(b)
    except services.BookingError as e:
        return _err(e)
    return _out(nb, status.HTTP_201_CREATED)
