from django.contrib import admin
from unfold.admin import ModelAdmin, StackedInline

from . import notify
from .models import FAQ, Policy, PolicySection, Ticket


@admin.register(Ticket)
class TicketAdmin(ModelAdmin):
    list_display = ["number", "user", "topic", "booking_code", "status", "updated_at"]
    list_filter = ["status", "topic"]
    search_fields = ["booking_code", "message", "user__email"]
    list_editable = ["status"]
    readonly_fields = ["user", "topic", "booking_code", "message", "attachment", "created_at"]
    fields = ["user", "topic", "booking_code", "message", "attachment", "created_at", "status", "staff_reply"]

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and {"status", "staff_reply"} & set(form.changed_data):
            notify.updated(obj)  # emails the player


@admin.register(FAQ)
class FAQAdmin(ModelAdmin):
    list_display = ["question", "sort"]
    list_editable = ["sort"]
    search_fields = ["question", "answer"]


class SectionInline(StackedInline):
    model = PolicySection
    extra = 1
    fields = ["heading", "body", "sort"]


@admin.register(Policy)
class PolicyAdmin(ModelAdmin):
    list_display = ["title", "key", "section_count", "updated"]
    prepopulated_fields = {"key": ["title"]}
    inlines = [SectionInline]

    @admin.display(description="Sections")
    def section_count(self, p):
        return p.sections.count()
