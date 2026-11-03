import re
import io
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User
from catalog.models import CafeSettings, Game, Seat

from .ai import PaymentScreenshot
from .models import Booking
from .services import sweep


def png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 80), "white").save(buf, "PNG")
    buf.seek(0)
    buf.name = "shot.png"
    return buf


@override_settings(AI_VERIFY_ASYNC=False, MEDIA_ROOT="/tmp/quodes-test-media")
class FlowTests(TestCase):
    def setUp(self):
        call_command("seed", verbosity=0)
        self.user = User.objects.create_user("p@x.com", "Str0ng!pass", gamertag="p1")
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.game = Game.objects.get(mono="FC25")
        self.seats = list(Seat.objects.filter(station__type__code="PS5", station__number=4))
        self.tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()

    def lock(self, **kw):
        body = {"game": self.game.id, "seat_ids": [s.id for s in self.seats], "date": self.tomorrow,
                "start_hour": 16, "duration_hours": 2, **kw}
        return self.api.post("/api/bookings/", body, format="json")

    def good_read(self, b):
        return PaymentScreenshot(is_payment_screenshot=True, success=True, amount=f"{b.amount_due}",
                                 payee_upi_id=CafeSettings.get().upi_id, payee_name="Quodes",
                                 utr="123456789012", paid_at=timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                                 notes="")

    def test_lock_prices_and_blocks_double_booking(self):
        r = self.lock()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "locked")
        self.assertEqual(r.data["total"], "600.00")  # 150 × 2 seats × 2 h
        self.assertEqual(r.data["station_label"], "Station 5 · #04")
        self.assertTrue(r.data["upi_uri"].startswith("upi://pay?pa="))
        other = User.objects.create_user("o@x.com", "Str0ng!pass")
        api2 = APIClient()
        api2.force_authenticate(other)
        r2 = api2.post("/api/bookings/", {"game": self.game.id, "seat_ids": [self.seats[0].id],
                                          "date": self.tomorrow, "start_hour": 17, "duration_hours": 1},
                       format="json")
        self.assertEqual(r2.status_code, 409)
        slots = self.api.get(f"/api/slots/?seats={self.seats[0].id}&date={self.tomorrow}").data["hours"]
        self.assertEqual({h["hour"]: h["status"] for h in slots}[16], "hold")

    def test_happy_path_ai_then_staff(self):
        bid = self.lock().data["id"]
        b = Booking.objects.get(pk=bid)
        with mock.patch("bookings.ai.extract", return_value=self.good_read(b)):
            r = self.api.post(f"/api/bookings/{bid}/proof/", {"screenshot": png()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "pending_human")
        self.assertTrue(all(c["status"] == "pass" for c in r.data["ai_checks"]))
        self.assertEqual(r.data["utr"], "123456789012")
        from .services import approve
        approve(Booking.objects.get(pk=bid), None)
        self.assertEqual(self.api.get(f"/api/bookings/{bid}/").data["status"], "confirmed")

    def test_wrong_amount_fails_then_manual_review(self):
        bid = self.lock().data["id"]
        b = Booking.objects.get(pk=bid)
        bad = self.good_read(b).model_copy(update={"amount": "500"})
        with mock.patch("bookings.ai.extract", return_value=bad):
            r = self.api.post(f"/api/bookings/{bid}/proof/", {"screenshot": png()}, format="multipart")
        self.assertEqual(r.data["status"], "ai_failed")
        self.assertIn("Expected ₹600", r.data["ai_message"])
        r = self.api.post(f"/api/bookings/{bid}/manual-review/")
        self.assertEqual(r.data["status"], "pending_human")

    def test_no_ai_goes_to_human(self):
        bid = self.lock().data["id"]
        with mock.patch("bookings.ai.extract", return_value=None):
            r = self.api.post(f"/api/bookings/{bid}/proof/", {"screenshot": png(), "utr": "999988887777"},
                              format="multipart")
        self.assertEqual(r.data["status"], "pending_human")

    def test_lock_expires_and_frees_seats(self):
        bid = self.lock().data["id"]
        Booking.objects.filter(pk=bid).update(lock_expires_at=timezone.now() - timedelta(seconds=1))
        sweep()
        self.assertEqual(Booking.objects.get(pk=bid).status, "expired")
        self.assertEqual(self.lock().status_code, 201)

    def test_release_credits_and_rebook(self):
        bid = self.lock().data["id"]
        with mock.patch("bookings.ai.extract", return_value=None):
            self.api.post(f"/api/bookings/{bid}/proof/", {"screenshot": png()}, format="multipart")
        Booking.objects.filter(pk=bid).update(verify_deadline=timezone.now() - timedelta(seconds=1))
        r = self.api.get(f"/api/bookings/{bid}/")
        self.assertEqual(r.data["status"], "released")
        self.user.refresh_from_db()
        self.assertEqual(str(self.user.credit), "600.00")
        r = self.api.post(f"/api/bookings/{bid}/rebook/")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.user.refresh_from_db()
        self.assertEqual(str(self.user.credit), "0.00")

    def test_cancel_and_validation(self):
        bid = self.lock().data["id"]
        self.assertEqual(self.api.post(f"/api/bookings/{bid}/cancel/").data["status"], "cancelled")
        self.assertEqual(self.lock(start_hour=23, duration_hours=2).status_code, 400)
        mixed = [self.seats[0].id, Seat.objects.filter(station__type__code="PC").first().id]
        self.assertEqual(self.lock(seat_ids=mixed).status_code, 400)


class PublicEndpointTests(TestCase):
    def setUp(self):
        call_command("seed", verbosity=0)

    def test_catalog(self):
        c = APIClient()
        self.assertEqual(len(c.get("/api/games/").data), 8)
        self.assertEqual(len(c.get("/api/games/?genre=SHOOTER").data), 3)
        seat = c.get("/api/seatmap/?type=PS5").data
        self.assertEqual(len(seat["stations"]), 5)
        av = c.get(f"/api/availability/?date={(timezone.localdate() + timedelta(days=1)).isoformat()}").data
        self.assertEqual(av["hours"][0]["free"], {"PS5": 5, "PS4": 4, "PC": 10})
        self.assertEqual(len(c.get("/api/dates/").data), 7)
        self.assertEqual(len(c.get("/api/policies/").data), 3)


@override_settings(EMAIL_ASYNC=False)
class AuthTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # rate-limit counters live in the cache

    def code_from_last_mail(self):
        from django.core import mail
        return re.search(r"Your code: (\d{6})", mail.outbox[-1].body).group(1)

    def test_register_verify_login_reset(self):
        from django.core import mail
        c = APIClient()
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/auth/register/", {"email": "New@x.com", "password": "Str0ng!pass", "gamertag": "neo"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotIn("access", r.data)
        self.assertTrue(r.data["verify_required"])
        code = self.code_from_last_mail()
        self.assertIn("is your code", mail.outbox[-1].subject)
        self.assertTrue(mail.outbox[-1].alternatives)  # HTML part

        # Unverified login is refused with a machine-readable code.
        r = c.post("/api/auth/login/", {"email": "new@x.com", "password": "Str0ng!pass"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["code"], "email_not_verified")
        self.assertEqual(c.post("/api/auth/email/resend/", {"email": "new@x.com"}).status_code, 429)

        self.assertEqual(c.post("/api/auth/email/verify/", {"email": "new@x.com", "code": "000000" if code != "000000" else "111111"}).status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/auth/email/verify/", {"email": "new@x.com", "code": code})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertTrue(r.data["user"]["email_verified"])
        self.assertIn("Welcome", mail.outbox[-1].subject)
        self.assertEqual(c.post("/api/auth/login/", {"email": "new@x.com", "password": "nope"}).status_code, 400)

        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/auth/password/forgot/", {"email": "new@x.com"})
        self.assertEqual(r.data["masked_email"], "n•••@x.com")
        code = self.code_from_last_mail()
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post("/api/auth/password/reset/", {"email": "new@x.com", "code": code, "new_password": "An0ther!pass"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("password was changed", mail.outbox[-1].subject)
        r = c.post("/api/auth/login/", {"email": "new@x.com", "password": "An0ther!pass"})
        self.assertEqual(r.status_code, 200)
        c.credentials(HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        self.assertEqual(c.get("/api/me/").data["gamertag"], "neo")

    def test_unknown_email_is_not_revealed(self):
        from django.core import mail
        c = APIClient()
        r = c.post("/api/auth/password/forgot/", {"email": "ghost@x.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(AI_VERIFY_ASYNC=False, EMAIL_ASYNC=False, MEDIA_ROOT="/tmp/quodes-test-media",
                   STAFF_ALERT_EMAILS=["desk@quodes.gg"])
class NotificationEmailTests(TestCase):
    def setUp(self):
        call_command("seed", verbosity=0)
        self.user = User.objects.create_user("p@x.com", "Str0ng!pass", gamertag="p1", email_verified=True)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_booking_and_ticket_emails(self):
        from django.core import mail
        seat = Seat.objects.filter(station__type__code="PS5").first()
        with self.captureOnCommitCallbacks(execute=True):
            bid = self.api.post("/api/bookings/", {
                "game": Game.objects.get(mono="FC25").id, "seat_ids": [seat.id],
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "start_hour": 12, "duration_hours": 1}, format="json").data["id"]
        self.assertIn("Slot locked", mail.outbox[-1].subject)
        self.assertIn("quodes@upi", mail.outbox[-1].body)
        with self.captureOnCommitCallbacks(execute=True), mock.patch("bookings.ai.extract", return_value=None):
            self.api.post(f"/api/bookings/{bid}/proof/", {"screenshot": png()}, format="multipart")
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any("Payment received" in s for s in subjects))
        staff_mail = next(m for m in mail.outbox if m.to == ["desk@quodes.gg"])
        self.assertIn(f"/admin/bookings/booking/{bid}/change/", staff_mail.body)
        from .services import approve
        with self.captureOnCommitCallbacks(execute=True):
            approve(Booking.objects.get(pk=bid), None)
        self.assertIn("Confirmed", mail.outbox[-1].subject)
        self.assertEqual(mail.outbox[-1].to, ["p@x.com"])

        n = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.api.post("/api/tickets/", {"topic": "Payment", "message": "Paid twice"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        new = mail.outbox[n:]
        self.assertEqual({tuple(m.to) for m in new}, {("p@x.com",), ("desk@quodes.gg",)})


@override_settings(AI_VERIFY_ASYNC=False, MEDIA_ROOT="/tmp/quodes-test-media")
class AdminPanelTests(TestCase):
    def setUp(self):
        call_command("seed", verbosity=0)
        self.boss = User.objects.create_superuser("boss@x.com", "Str0ng!pass")
        self.client.force_login(self.boss)
        player = User.objects.create_user("p@x.com", "Str0ng!pass", gamertag="p1")
        api = APIClient()
        api.force_authenticate(player)
        seat = Seat.objects.filter(station__type__code="PC").first()
        r = api.post("/api/bookings/", {"game": Game.objects.get(mono="VAL").id, "seat_ids": [seat.id],
                                        "date": timezone.localdate().isoformat(), "start_hour": 23,
                                        "duration_hours": 1}, format="json")
        self.bid = r.data["id"]
        with mock.patch("bookings.ai.extract", return_value=None):
            api.post(f"/api/bookings/{self.bid}/proof/", {"screenshot": png()}, format="multipart")

    def test_every_page_loads(self):
        pages = ["/admin/", "/admin/bookings/booking/", "/admin/bookings/booking/?queue=verify",
                 f"/admin/bookings/booking/{self.bid}/change/", "/admin/catalog/game/", "/admin/catalog/game/add/",
                 "/admin/catalog/game/1/change/", "/admin/catalog/stationtype/", "/admin/catalog/stationtype/add/",
                 "/admin/catalog/stationtype/1/change/", "/admin/catalog/station/", "/admin/catalog/station/add/",
                 "/admin/catalog/cafesettings/1/change/", "/admin/support/ticket/", "/admin/support/faq/add/",
                 "/admin/support/policy/", "/admin/support/policy/add/", "/admin/support/policy/1/change/",
                 "/admin/accounts/user/", "/admin/accounts/user/add/", "/admin/auth/group/"]
        for url in pages:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertRedirects(self.client.get("/admin/catalog/cafesettings/"), "/admin/catalog/cafesettings/1/change/")
        dash = self.client.get("/admin/").content.decode()
        self.assertIn("Payments waiting for team verification", dash)
        self.assertIn(Booking.objects.get(pk=self.bid).code, dash)

    def test_detail_approve_button(self):
        r = self.client.get(f"/admin/bookings/booking/{self.bid}/approve_one/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Booking.objects.get(pk=self.bid).status, "confirmed")

    def test_add_station_creates_seats(self):
        from catalog.models import StationType
        ps5 = StationType.objects.get(code="PS5")
        r = self.client.post("/admin/catalog/station/add/", {
            "type": ps5.id, "number": 6, "is_active": "on",
            "seats-TOTAL_FORMS": 0, "seats-INITIAL_FORMS": 0, "seats-MIN_NUM_FORMS": 0, "seats-MAX_NUM_FORMS": 1000})
        self.assertEqual(r.status_code, 302, r.content[:500])
        self.assertEqual(Seat.objects.filter(station__type=ps5, station__number=6).count(), 2)


class GroqExtractTests(TestCase):
    @override_settings(AI_VERIFY_ENABLED=True)
    def test_parses_strict_json(self):
        import json as _json
        import os
        import tempfile
        from . import ai
        payload = {"is_payment_screenshot": True, "success": True, "amount": "600.00",
                   "payee_upi_id": "quodes@upi", "payee_name": "Quodes", "utr": "123456789012",
                   "paid_at": "2026-11-03T16:02", "notes": ""}
        fake = mock.MagicMock()
        fake.chat.completions.create.return_value.choices = [
            mock.MagicMock(message=mock.MagicMock(content=_json.dumps(payload)))]
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            Image.new("RGB", (40, 80), "white").save(f.name)
            with override_settings(GROQ_API_KEY="test"), \
                    mock.patch("bookings.ai.groq.Groq", return_value=fake):
                out = ai.extract(f.name)
        self.assertEqual(out.amount, "600.00")
        kwargs = fake.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"]["json_schema"]["strict"], True)
        self.assertTrue(kwargs["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_no_key_skips_ai(self):
        import os
        from . import ai
        with override_settings(GROQ_API_KEY=""):
            self.assertIsNone(ai.extract("/nonexistent.png"))
