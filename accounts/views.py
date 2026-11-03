from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from quodes import mailer

from .emails import send_code
from .models import OneTimeCode, User
from .serializers import (CodeSerializer, EmailSerializer, LoginSerializer, RegisterSerializer,
                          ResetSerializer, UserSerializer, tokens_for)

P = OneTimeCode.Purpose


def mask_email(email):
    name, _, domain = email.partition("@")
    return f"{name[:1]}{'•' * max(len(name) - 1, 3)}@{domain}"


def code_sent(email, detail):
    return {"detail": detail, "email": email, "masked_email": mask_email(email),
            "resend_after": int(OneTimeCode.RESEND_AFTER.total_seconds())}


def _active(email):
    return User.objects.filter(email=email.lower(), is_active=True).first()


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        if not settings.REQUIRE_EMAIL_VERIFICATION:
            user.email_verified = True
            user.save(update_fields=["email_verified"])
            mailer.send(user.email, "Welcome to Quodes", "welcome", {"user": user})
            return Response(tokens_for(user), status=status.HTTP_201_CREATED)
        send_code(user, P.VERIFY_EMAIL)
        return Response({**code_sent(user.email, "We emailed you a 6-digit code."), "verify_required": True},
                        status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        s = LoginSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        user = s.validated_data["user"]
        if settings.REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
            if not OneTimeCode.too_soon(user, P.VERIFY_EMAIL):
                send_code(user, P.VERIFY_EMAIL)
            return Response({**code_sent(user.email, "Confirm your email first. We sent you a code."),
                             "code": "email_not_verified"}, status=status.HTTP_403_FORBIDDEN)
        return Response(tokens_for(user))


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp"

    def post(self, request):
        s = CodeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = _active(s.validated_data["email"])
        otp = user and OneTimeCode.latest(user, P.VERIFY_EMAIL)
        if not otp or not otp.verify(s.validated_data["code"]):
            return Response({"detail": "That code is wrong or expired."}, status=status.HTTP_400_BAD_REQUEST)
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        mailer.send(user.email, "Welcome to Quodes", "welcome", {"user": user})
        return Response(tokens_for(user))


class ResendCodeView(APIView):
    """Resend the signup code (purpose=verify, default) or the reset code (purpose=reset)."""
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp"

    def post(self, request):
        s = EmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower()
        purpose = P.RESET_PASSWORD if request.data.get("purpose") == "reset" else P.VERIFY_EMAIL
        user = _active(email)
        if user and OneTimeCode.too_soon(user, purpose):
            return Response({"detail": "Wait a minute before asking for another code."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        if user and not (purpose == P.VERIFY_EMAIL and user.email_verified):
            send_code(user, purpose)
        return Response(code_sent(email, "If that email has an account, a new code is on its way."))


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp"

    def post(self, request):
        s = EmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower()
        user = _active(email)
        if user and not OneTimeCode.too_soon(user, P.RESET_PASSWORD):
            send_code(user, P.RESET_PASSWORD)
        # Same answer whether or not the account exists.
        return Response(code_sent(email, "If that email has an account, a code is on its way."))


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp"

    def post(self, request):
        s = ResetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        user = _active(d["email"])
        if user:
            try:
                password_validation.validate_password(d["new_password"], user)
            except DjangoValidationError as e:
                return Response({"new_password": list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
        otp = user and OneTimeCode.latest(user, P.RESET_PASSWORD)
        if not otp or not otp.verify(d["code"]):
            return Response({"detail": "That code is wrong or expired."}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(d["new_password"])
        user.email_verified = True  # they proved they own the inbox
        user.save(update_fields=["password", "email_verified"])
        mailer.send(user.email, "Your password was changed", "password_changed", {"user": user})
        return Response({"detail": "Password updated. Log in with your new password."})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
