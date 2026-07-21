from django.conf import settings
from django.core.management.base import BaseCommand

from apps.tenancy.demo import DemoDataService


class Command(BaseCommand):
    help = "Replace the public Finora demo tenant with known disposable sample data."

    def handle(self, *args, **options):
        tenant = DemoDataService.reset(password=settings.DEMO_USER_PASSWORD)
        self.stdout.write(self.style.SUCCESS(f"Reset public demo tenant '{tenant.slug}'."))
