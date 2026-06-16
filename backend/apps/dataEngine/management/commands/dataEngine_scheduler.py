# your_app/management/commands/run_all_schedulers.py
from django.core.management.base import BaseCommand
from ... import scheduler as dataEngine_scheduler
from ...scheduler import start
import time

class Command(BaseCommand):
    help = 'Start all background schedulers'

    def handle(self, *args, **kwargs):
        # self.stdout.write("🚀 Launching all schedulers...")
        start()
        try:
            # Keep the process alive
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("🛑 Scheduler process interrupted manually."))
