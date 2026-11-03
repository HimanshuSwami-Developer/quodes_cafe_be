from django.conf import settings
from django.db import models


class Ticket(models.Model):
    TOPICS = ["Payment", "Reschedule", "Refund", "Station issue", "Other"]

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_REVIEW = "in_review", "In review"
        RESOLVED = "resolved", "Resolved"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets")
    topic = models.CharField(max_length=20, choices=[(t, t) for t in TOPICS])
    booking_code = models.CharField(max_length=12, blank=True)
    message = models.TextField(max_length=2000)
    attachment = models.FileField(upload_to="tickets/%Y/%m/", blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    staff_reply = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"#{self.number} · {self.topic}"

    @property
    def number(self):
        return f"{1000 + self.pk}"


class FAQ(models.Model):
    question = models.CharField(max_length=200)
    answer = models.TextField()
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]
        verbose_name = "FAQ"

    def __str__(self):
        return self.question


class Policy(models.Model):
    key = models.SlugField(unique=True)
    title = models.CharField(max_length=60)
    sort = models.PositiveSmallIntegerField(default=0)
    updated = models.DateField(auto_now=True)

    class Meta:
        ordering = ["sort"]
        verbose_name_plural = "policies"

    def __str__(self):
        return self.title


class PolicySection(models.Model):
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE, related_name="sections")
    heading = models.CharField(max_length=80)
    body = models.TextField()
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]
