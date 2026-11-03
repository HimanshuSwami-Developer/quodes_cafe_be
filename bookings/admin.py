from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.enums import ActionVariant

from . import services
from .models import Booking


class AwaitingFilter(admin.SimpleListFilter):
    title = "queue"
    parameter_name = "queue"

    def lookups(self, request, model_admin):
        return [("verify", "Needs team verification")]

    def queryset(self, request, qs):
        if self.value() == "verify":
            return qs.filter(status=Booking.Status.PENDING_HUMAN).order_by("verify_deadline")
        return qs


@admin.register(Booking)
class BookingAdmin(ModelAdmin):
    list_display = ["code", "user", "game", "station_type", "date", "time", "amount", "utr",
                    "status", "deadline"]
    list_filter = [AwaitingFilter, "status", "station_type", "date"]
    search_fields = ["code", "utr", "user__email", "user__gamertag", "user__phone"]
    date_hierarchy = "date"
    readonly_fields = ["code", "user", "game", "station_type", "seat_list", "date", "start_hour",
                       "duration_hours", "rate", "total", "credit_applied", "created_at", "lock_expires_at",
                       "submitted_at", "ai_checked_at", "verify_deadline", "confirmed_at", "released_at",
                       "proof", "utr", "checks", "ai_message", "ai_raw", "reviewed_by", "rebooked_from"]
    exclude = ["seats", "screenshot", "ai_checks"]
    actions = ["approve_payment", "reject_payment"]
    actions_detail = ["approve_one", "reject_one"]

    def has_add_permission(self, request):
        return False  # bookings come from the app

    def _one(self, request, object_id, fn, ok):
        b = Booking.objects.get(pk=object_id)
        try:
            fn(b)
            self.message_user(request, f"{b.code}: {ok}", messages.SUCCESS)
        except services.BookingError as e:
            self.message_user(request, f"{b.code}: {e}", messages.WARNING)
        return redirect(reverse("admin:bookings_booking_change", args=[object_id]))

    @action(description="Approve payment", icon="check_circle", variant=ActionVariant.SUCCESS,
            permissions=["change"])
    def approve_one(self, request, object_id):
        return self._one(request, object_id, lambda b: services.approve(b, request.user), "confirmed.")

    @action(description="Reject payment", icon="cancel", variant=ActionVariant.DANGER, permissions=["change"])
    def reject_one(self, request, object_id):
        return self._one(request, object_id,
                         lambda b: services.reject(b, request.user, "Payment not found in bank records"),
                         "rejected, seats freed.")

    def get_queryset(self, request):
        services.sweep()
        return super().get_queryset(request).select_related("user", "game", "station_type")

    @admin.display(description="Time")
    def time(self, b):
        return b.time_label

    @admin.display(description="Amount")
    def amount(self, b):
        return f"₹{b.amount_due:,.0f}"

    @admin.display(description="Verify by")
    def deadline(self, b):
        if b.status != Booking.Status.PENDING_HUMAN or not b.verify_deadline:
            return "—"
        mins = int((b.verify_deadline - timezone.now()).total_seconds() // 60)
        return f"{timezone.localtime(b.verify_deadline):%I:%M %p} ({mins} min left)"

    @admin.display(description="Seats")
    def seat_list(self, b):
        return ", ".join(s.code for s in b.seats.all())

    @admin.display(description="Screenshot")
    def proof(self, b):
        if not b.screenshot:
            return "—"
        return format_html('<a href="{0}" target="_blank"><img src="{0}" style="max-height:480px"></a>',
                           b.screenshot.url)

    @admin.display(description="AI checks")
    def checks(self, b):
        icon = {"pass": "✅", "fail": "❌", "pending": "⏳"}
        return format_html("<br>".join(
            f"{icon.get(c['status'], '?')} <b>{c['label']}</b> — {c['detail']}" for c in b.ai_checks)) \
            if b.ai_checks else "—"

    @admin.action(description="Approve payment (confirm session)")
    def approve_payment(self, request, qs):
        done = 0
        for b in qs:
            try:
                services.approve(b, request.user)
                done += 1
            except services.BookingError as e:
                self.message_user(request, f"{b.code}: {e}", messages.WARNING)
        self.message_user(request, f"Confirmed {done} booking(s).")

    @admin.action(description="Reject payment (free the seats)")
    def reject_payment(self, request, qs):
        done = 0
        for b in qs:
            try:
                services.reject(b, request.user, "Payment not found in bank records")
                done += 1
            except services.BookingError as e:
                self.message_user(request, f"{b.code}: {e}", messages.WARNING)
        self.message_user(request, f"Rejected {done} booking(s).")
