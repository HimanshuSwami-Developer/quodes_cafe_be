from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts import views as acc
from bookings import views as bk
from catalog import views as cat
from support import views as sup

admin.site.site_header = "Quodes Gaming · Desk"
admin.site.site_title = "Quodes Desk"
admin.site.index_title = "Bookings, payments & players"

api = [
    path("auth/register/", acc.RegisterView.as_view()),
    path("auth/login/", acc.LoginView.as_view()),
    path("auth/refresh/", acc.RefreshView.as_view()),
    path("auth/email/verify/", acc.VerifyEmailView.as_view()),
    path("auth/email/resend/", acc.ResendCodeView.as_view()),
    path("auth/password/forgot/", acc.ForgotPasswordView.as_view()),
    path("auth/password/reset/", acc.ResetPasswordView.as_view()),
    path("me/", acc.MeView.as_view()),

    path("cafe/", cat.cafe),
    path("genres/", cat.genres),
    path("games/", cat.games),
    path("station-types/", cat.station_types),
    path("seatmap/", cat.seatmap),
    path("availability/", cat.availability),
    path("slots/", cat.slots),
    path("dates/", cat.dates),

    path("bookings/", bk.BookingListView.as_view()),
    path("bookings/<int:pk>/", bk.booking_detail),
    path("bookings/<int:pk>/cancel/", bk.booking_cancel),
    path("bookings/<int:pk>/proof/", bk.ProofView.as_view()),
    path("bookings/<int:pk>/manual-review/", bk.booking_manual_review),
    path("bookings/<int:pk>/rebook/", bk.booking_rebook),

    path("tickets/", sup.TicketListCreate.as_view()),
    path("faqs/", sup.FAQList.as_view()),
    path("policies/", sup.PolicyList.as_view()),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/admin/", include("staff.urls")),  # staff API for the Flutter web admin
    path("api/", include(api)),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
