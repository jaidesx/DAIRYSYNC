"""
Management command to create missing FridgeSlot records (1–6) for every
existing Fridge.  Existing slots are never duplicated thanks to
ignore_conflicts=True.

Usage:
    python manage.py create_fridge_slots
"""

from django.core.management.base import BaseCommand

from DairyApp.models import Fridge, FridgeSlot


class Command(BaseCommand):
    help = "Create missing fridge slots (1–6) for every existing fridge."

    def handle(self, *args, **options):
        fridges = Fridge.objects.all()
        slots_to_create = []

        for fridge in fridges:
            existing = set(
                FridgeSlot.objects.filter(fridge=fridge)
                .values_list("slot_number", flat=True)
            )
            for number in range(1, 7):
                if number not in existing:
                    slots_to_create.append(
                        FridgeSlot(fridge=fridge, slot_number=number)
                    )

        created = FridgeSlot.objects.bulk_create(
            slots_to_create, ignore_conflicts=True
        )

        count = len(created)
        self.stdout.write(
            self.style.SUCCESS(f"Created {count} missing slot(s).")
        )
