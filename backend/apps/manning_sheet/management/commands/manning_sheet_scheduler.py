# your_app/management/commands/run_all_schedulers.py
import time

from django.core.management.base import BaseCommand

from ...scheduler import start


class Command(BaseCommand):
    help = "Start all background schedulers"

    def handle(self, *args, **kwargs):
        # self.stdout.write("🚀 Launching all schedulers...")
        start()
        try:
            # Keep the process alive
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING("🛑 Scheduler process interrupted manually.")
            )
