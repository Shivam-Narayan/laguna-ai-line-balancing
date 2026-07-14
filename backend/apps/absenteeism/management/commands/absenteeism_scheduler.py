import time
from typing import Any
from django.core.management.base import BaseCommand

# Use absolute imports in Django management commands to prevent ImportError crashes
from apps.absenteeism.scheduler import start

class Command(BaseCommand):
    help = 'Start all background schedulers'

    def handle(self, *args: Any, **kwargs: Any) -> None:
        # self.stdout.write("🚀 Launching all schedulers...")
        start()
        try:
            # Keep the process alive
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("🛑 Scheduler process interrupted manually."))
