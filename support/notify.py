from django.conf import settings
from django.urls import reverse

from quodes import mailer


def created(t):
    mailer.send(t.user.email, f"Ticket #{t.number} received", "ticket", {
        "t": t, "heading": f"We got your ticket #{t.number}",
        "lead": f"The desk usually replies within {t._cafe.reply_minutes} minutes during opening hours."})
    mailer.staff(f"New {t.topic} ticket #{t.number}", "ticket", {
        "t": t, "heading": f"New ticket from {t.user}",
        "lead": f"{t.user.email}{' · booking ' + t.booking_code if t.booking_code else ''}",
        "staff_link": settings.SITE_URL + reverse("admin:support_ticket_change", args=[t.pk])})


def updated(t):
    mailer.send(t.user.email, f"Update on ticket #{t.number}", "ticket", {
        "t": t, "heading": f"Ticket #{t.number}: {t.get_status_display()}",
        "lead": "The desk updated your ticket."})
