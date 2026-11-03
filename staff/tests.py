from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from bookings.models import Booking
from bookings.tests import png
from catalog.models import Game, Seat, Station, StationType


@override_settings(AI_VERIFY_ASYNC=False, EMAIL_ASYNC=False, MEDIA_ROOT="/tmp/quodes-test-media")
class StaffApiTests(TestCase):
    def setUp(self):
        call_command("seed", verbosity=0)
        self.staff = User.objects.create_user("desk@x.com", "Str0ng!pass", is_staff=True, email_verified=True)
        self.player = User.objects.create_user("p@x.com", "Str0ng!pass", email_verified=True)
        self.api = APIClient()
        self.api.force_authenticate(self.staff)

    def _pending_booking(self):
        papi = APIClient()
        papi.force_authenticate(self.player)
        seat = Seat.objects.filter(station__type__code="PS5").first()
        bid = papi.post("/api/bookings/", {"game": Game.objects.get(mono="FC25").id, "seat_ids": [seat.id],
                                           "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                                           "start_hour": 14, "duration_hours": 1}, format="json").data["id"]
        with mock.patch("bookings.ai.extract", return_value=None):
            papi.post(f"/api/bookings/{bid}/proof/", {"screenshot": png()}, format="multipart")
        return bid

    def test_players_are_refused(self):
        papi = APIClient()
        papi.force_authenticate(self.player)
        for url in ["/api/admin/dashboard/", "/api/admin/bookings/", "/api/admin/games/", "/api/admin/cafe/"]:
            self.assertEqual(papi.get(url).status_code, 403, url)
        self.assertEqual(APIClient().get("/api/admin/dashboard/").status_code, 401)

    def test_verify_queue_and_approve(self):
        bid = self._pending_booking()
        dash = self.api.get("/api/admin/dashboard/").data
        self.assertEqual(dash["kpis"]["to_verify"], 1)
        self.assertEqual(dash["queue"][0]["player"]["email"], "p@x.com")
        self.assertTrue(dash["queue"][0]["screenshot_url"].startswith("http://testserver/media/"))
        q = self.api.get("/api/admin/bookings/?queue=verify").data
        self.assertEqual([b["id"] for b in q], [bid])
        r = self.api.post(f"/api/admin/bookings/{bid}/approve/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(self.api.post(f"/api/admin/bookings/{bid}/reject/").status_code, 400)

    def test_reject_with_note(self):
        bid = self._pending_booking()
        r = self.api.post(f"/api/admin/bookings/{bid}/reject/", {"note": "No such UTR"}, format="json")
        self.assertEqual(r.data["status"], "rejected")
        self.assertEqual(Booking.objects.get(pk=bid).staff_note, "No such UTR")

    def test_catalog_crud(self):
        r = self.api.post("/api/admin/games/", {"name": "Fortnite", "mono": "FN", "genre": "SHOOTER",
                                                 "hue": "#ff00aa", "deep": "#111111", "platforms": ["PS5", "PC"],
                                                 "max_players": 4}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["hue"], "#FF00AA")
        self.assertEqual(self.api.post("/api/admin/games/", {"name": "X", "mono": "X", "genre": "SHOOTER",
                                                              "hue": "red", "deep": "#111111", "platforms": []},
                                       format="json").status_code, 400)
        ps5 = StationType.objects.get(code="PS5")
        r = self.api.post("/api/admin/stations/", {"type": ps5.id, "number": 9, "is_active": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["seat_count"], 2)
        self.assertEqual(r.data["code"], "S5-09")
        r = self.api.patch(f"/api/admin/station-types/{ps5.id}/", {"hourly_rate": "175.00"}, format="json")
        self.assertEqual(r.data["hourly_rate"], "175.00")
        r = self.api.patch("/api/admin/cafe/", {"upi_id": "desk@okaxis"}, format="json")
        self.assertEqual(r.data["upi_id"], "desk@okaxis")

    def test_policy_sections_and_ticket_reply(self):
        r = self.api.post("/api/admin/policies/", {"key": "food", "title": "Food", "sections": [
            {"heading": "Snacks", "body": "Lounge only"}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["sections"]), 1)
        papi = APIClient()
        papi.force_authenticate(self.player)
        tid = papi.post("/api/tickets/", {"topic": "Refund", "message": "Pls"}, format="json").data["id"]
        from django.core import mail
        n = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.api.patch(f"/api/admin/tickets/{tid}/", {"status": "resolved", "staff_reply": "Done"},
                               format="json")
        self.assertEqual(r.data["status"], "resolved")
        self.assertEqual(len(mail.outbox), n + 1)

    def test_staff_cannot_lock_self_out(self):
        r = self.api.patch(f"/api/admin/users/{self.staff.id}/", {"is_active": False, "is_staff": False},
                           format="json")
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active and self.staff.is_staff)
        r = self.api.patch(f"/api/admin/users/{self.player.id}/", {"credit": "250.00"}, format="json")
        self.assertEqual(r.data["credit"], "250.00")
