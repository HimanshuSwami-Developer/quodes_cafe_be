"""All outgoing email goes through `send()`.

Each email has a template pair: templates/emails/<name>.txt (plain text) and
templates/emails/<name>.html (the HTML part, which extends emails/base.html).
Mail is sent after the current DB transaction commits, in a background thread so a
slow SMTP server never blocks an API request (EMAIL_ASYNC=False sends inline).
"""
import logging
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string

log = logging.getLogger(__name__)


def _deliver(msg):
    try:
        msg.send()
    except Exception:
        log.exception("Email to %s failed: %s", msg.to, msg.subject)


def send(to, subject, template, context=None, now=False):
    to = [t for t in ([to] if isinstance(to, str) else list(to)) if t]
    if not to:
        return
    from catalog.models import CafeSettings
    cafe = CafeSettings.get()
    ctx = {"cafe": cafe, "subject": subject, "app_name": cafe.name, **(context or {})}
    text = render_to_string(f"emails/{template}.txt", ctx)
    html = render_to_string(f"emails/{template}.html", ctx)
    msg = EmailMultiAlternatives(f"{subject} · {cafe.name}", text, settings.DEFAULT_FROM_EMAIL, to,
                                 reply_to=[settings.EMAIL_REPLY_TO] if settings.EMAIL_REPLY_TO else None)
    msg.attach_alternative(html, "text/html")

    def go():
        if settings.EMAIL_ASYNC and not now:
            threading.Thread(target=_deliver, args=(msg,), daemon=True).start()
        else:
            _deliver(msg)

    transaction.on_commit(go)


def staff(subject, template, context=None):
    """Alert the desk team (STAFF_ALERT_EMAILS, else every active staff member)."""
    to = settings.STAFF_ALERT_EMAILS
    if not to:
        from accounts.models import User
        to = list(User.objects.filter(is_staff=True, is_active=True).values_list("email", flat=True))
    send(to, subject, template, context)
