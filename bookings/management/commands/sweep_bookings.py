from django.core.management.base import BaseCommand

from bookings.services import sweep


class Command(BaseCommand):
    help = "Expire stale slot locks and release bookings not verified in time. Run every minute via cron."

    def handle(self, *args, **opts):
        sweep()
        self.stdout.write(self.style.SUCCESS("Swept bookings."))
