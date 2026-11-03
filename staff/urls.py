from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.register("bookings", views.BookingAdminViewSet, basename="admin-bookings")
router.register("games", views.GameAdminViewSet, basename="admin-games")
router.register("station-types", views.StationTypeAdminViewSet, basename="admin-station-types")
router.register("stations", views.StationAdminViewSet, basename="admin-stations")
router.register("faqs", views.FAQAdminViewSet, basename="admin-faqs")
router.register("policies", views.PolicyAdminViewSet, basename="admin-policies")
router.register("tickets", views.TicketAdminViewSet, basename="admin-tickets")
router.register("users", views.UserAdminViewSet, basename="admin-users")

urlpatterns = [
    path("dashboard/", views.dashboard),
    path("cafe/", views.cafe_settings),
] + router.urls
