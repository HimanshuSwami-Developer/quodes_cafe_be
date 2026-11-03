from django.contrib.auth import authenticate, password_validation
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class UserSerializer(serializers.ModelSerializer):
    initials = serializers.CharField(read_only=True)
    hours_played = serializers.SerializerMethodField()
    sessions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "email_verified", "gamertag", "full_name", "phone", "initials",
                  "credit", "hours_played", "sessions", "is_staff"]
        read_only_fields = ["id", "email", "email_verified", "credit", "is_staff"]

    def _played(self, user):
        from bookings.models import Booking
        return Booking.objects.played_by(user)

    def get_hours_played(self, user):
        return sum(b.duration_hours for b in self._played(user))

    def get_sessions(self, user):
        return self._played(user).count()


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh),
            "user": UserSerializer(user).data}


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    gamertag = serializers.CharField(max_length=32)
    full_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        password_validation.validate_password(
            attrs["password"], User(email=attrs["email"], gamertag=attrs["gamertag"]))
        return attrs

    def create(self, data):
        return User.objects.create_user(**data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(self.context.get("request"),
                            email=attrs["email"].lower(), password=attrs["password"])
        if not user:
            raise serializers.ValidationError({"detail": "Wrong email or password."})
        attrs["user"] = user
        return attrs


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CodeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


class ResetSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r"^\d{6}$")
    new_password = serializers.CharField(write_only=True)
