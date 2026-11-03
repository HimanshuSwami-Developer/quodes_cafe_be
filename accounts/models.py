import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("email_verified", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Player account. Logs in with email; `gamertag` is the public handle."""

    username = None
    email = models.EmailField(unique=True)
    gamertag = models.CharField(max_length=32, blank=True)
    full_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email_verified = models.BooleanField(default=False, help_text="Player confirmed the email code.")
    credit = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        help_text="Game credit in rupees (from released slots / goodwill).",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.gamertag or self.email

    @property
    def initials(self):
        source = self.full_name or self.gamertag or self.email
        parts = [p for p in source.replace("@", " ").replace(".", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return source[:2].upper()


class OneTimeCode(models.Model):
    """6-digit code sent by email. Only the hash is stored."""

    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "verify", "Verify email"
        RESET_PASSWORD = "reset", "Reset password"

    LIFETIME = timedelta(minutes=10)
    MAX_ATTEMPTS = 5
    RESEND_AFTER = timedelta(seconds=60)

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="codes")
    purpose = models.CharField(max_length=8, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def latest(cls, user, purpose):
        return cls.objects.filter(user=user, purpose=purpose, used=False).first()

    @classmethod
    def too_soon(cls, user, purpose):
        last = cls.objects.filter(user=user, purpose=purpose).first()
        return bool(last and timezone.now() - last.created_at < cls.RESEND_AFTER)

    @classmethod
    def issue(cls, user, purpose):
        """Invalidate older codes and return (instance, plain 6-digit code)."""
        cls.objects.filter(user=user, purpose=purpose, used=False).update(used=True)
        code = f"{secrets.randbelow(10**6):06d}"
        return cls.objects.create(user=user, purpose=purpose, code_hash=make_password(code)), code

    @property
    def expired(self):
        return timezone.now() > self.created_at + self.LIFETIME

    def verify(self, code):
        if self.used or self.expired or self.attempts >= self.MAX_ATTEMPTS:
            return False
        self.attempts += 1
        ok = check_password(code, self.code_hash)
        if ok:
            self.used = True
        self.save(update_fields=["attempts", "used"])
        return ok
