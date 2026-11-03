"""Emails sent as a booking moves through its states."""
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from quodes import mailer


def _t(dt):
    return timezone.localtime(dt).strftime("%-I:%M %p") if dt else ""


def _send(b, subject, heading, lead, color=None, **extra):
    mailer.send(b.user.email, subject, "booking",
                {"b": b, "heading": heading, "lead": lead, "color": color, **extra})


def locked(b):
    _send(b, f"Slot locked · pay by {_t(b.lock_expires_at)}", "Your slot is locked",
          f"We're holding your seats until {_t(b.lock_expires_at)}. Pay and upload the screenshot before then.",
          pay=True, lock_until=_t(b.lock_expires_at))


def pending(b):
    manual = any(c.get("status") != "pass" for c in b.ai_checks)
    _send(b, "Payment received · verifying", "Provisionally booked",
          (b.ai_message if manual else "Our AI check passed.") +
          f" A team member confirms your payment by {_t(b.verify_deadline)}. We'll email you when it's done.",
          notes=["If we can't verify in time, the slot is released and your payment is kept as game credit."])
    mailer.staff(f"Verify payment {b.code} by {_t(b.verify_deadline)}", "staff_verify", {
        "b": b, "deadline": _t(b.verify_deadline),
        "staff_link": settings.SITE_URL + reverse("admin:bookings_booking_change", args=[b.pk])})


def ai_failed(b):
    _send(b, "Payment check failed · action needed", "We couldn't verify your screenshot",
          f"Your seats stay locked until {_t(b.lock_expires_at)}. Fix the issue below and upload again, "
          "or ask for a manual review in the app.", color="#C2283B", checks=b.ai_checks)


def confirmed(b):
    notes = ["Arrive 10 minutes early. Show this email or your booking ID at the desk."]
    if b.credit_applied:
        notes.insert(0, f"Paid with ₹{b.credit_applied:,.0f} game credit.")
    _send(b, f"GG! Confirmed for {b.date_label}", "GG! You're in", "Your payment is verified and your session is confirmed.",
          color="#15803D", notes=notes)


def rejected(b):
    _send(b, "Payment not verified", "We couldn't find your payment",
          "Our team couldn't match your payment in our bank records, so the seats were released.",
          color="#C2283B", notes=[n for n in [f"Reason: {b.staff_note}" if b.staff_note else "",
                                  "If you did pay, raise a Payment ticket in the app with your UTR and we'll sort it out."] if n])


def released(b):
    _send(b, "Slot released · payment saved as credit", "Your slot was released",
          "We couldn't finish verifying your payment within the time limit, so the station is open to other players again.",
          notes=[f"₹{b.amount_due:,.0f} has been added to your game credit. Use “Rebook with credit” in the app, "
                 "or raise a Refund ticket to get it back to your UPI account."])


def expired(b):
    if b.submitted_at:
        return
    _send(b, "Slot lock expired", "Your lock ran out",
          "We didn't get a payment screenshot in time, so the seats were unlocked.",
          notes=["Already paid? Raise a Payment ticket in the app with your UTR and we'll help."])
