from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.widgets import UnfoldAdminColorInputWidget

from .models import CafeSettings, Game, Seat, Station, StationType


@admin.register(CafeSettings)
class CafeSettingsAdmin(ModelAdmin):
    fieldsets = (
        ("Café", {"fields": ("name", "open_hour", "close_hour", "booking_days_ahead")}),
        ("UPI payments", {"fields": ("upi_id", "upi_payee"),
                          "description": "Players pay this UPI ID. The AI check rejects payments to any other ID."}),
        ("Timers", {"fields": ("lock_minutes", "verify_hours")}),
        ("Support", {"fields": ("support_phone", "maps_url", "reply_minutes")}),
    )

    def changelist_view(self, request, extra_context=None):
        CafeSettings.get()
        return redirect(reverse("admin:catalog_cafesettings_change", args=[1]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StationInline(TabularInline):
    model = Station
    extra = 0
    fields = ["number", "is_active"]


@admin.register(StationType)
class StationTypeAdmin(ModelAdmin):
    list_display = ["code", "name", "spec", "seats_per_station", "hourly_rate", "station_count", "sort"]
    list_editable = ["hourly_rate", "sort"]
    fields = ["code", "name", "spec", "seats_per_station", "hourly_rate", "seat_prefix", "grid_cols", "sort"]
    inlines = [StationInline]

    @admin.display(description="Stations")
    def station_count(self, obj):
        return obj.stations.filter(is_active=True).count()

    def save_formset(self, request, form, formset, change):
        # Saving each station individually makes sure its seats are created.
        for st in formset.save(commit=False):
            st.save()
        for st in formset.deleted_objects:
            st.delete()


class SeatInline(TabularInline):
    model = Seat
    extra = 0
    fields = ["index"]


@admin.register(Station)
class StationAdmin(ModelAdmin):
    list_display = ["__str__", "type", "number", "seat_count", "is_active"]
    list_filter = ["type", "is_active"]
    list_editable = ["is_active"]
    inlines = [SeatInline]

    @admin.display(description="Seats")
    def seat_count(self, obj):
        return obj.seats.count()


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = "__all__"
        widgets = {"hue": UnfoldAdminColorInputWidget, "deep": UnfoldAdminColorInputWidget,
                   "platforms": forms.CheckboxSelectMultiple}


@admin.register(Game)
class GameAdmin(ModelAdmin):
    form = GameForm
    list_display = ["tile", "name", "genre", "platform_list", "max_players", "is_active", "sort"]
    list_display_links = ["tile", "name"]
    list_editable = ["is_active", "sort"]
    list_filter = ["genre", "platforms", "is_active"]
    search_fields = ["name", "mono"]
    fieldsets = (
        (None, {"fields": ("name", "genre", "platforms", "max_players", "is_active", "sort")}),
        ("Tile look", {"fields": ("mono", "hue", "deep"),
                       "description": "Short label and two colours used for the game tile in the app."}),
    )

    @admin.display(description="Tile")
    def tile(self, g):
        return format_html('<span style="display:inline-flex;align-items:center;justify-content:center;'
                           'width:48px;height:32px;border-radius:6px;background:{};color:{};font-weight:800;'
                           'border:2px solid {}">{}</span>', g.deep, g.hue, g.hue, g.mono)

    @admin.display(description="Platforms")
    def platform_list(self, g):
        return " · ".join(p.code for p in g.platforms.all())
