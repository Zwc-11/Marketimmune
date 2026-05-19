import time

from django.core.management.base import BaseCommand

from dashboard.demo_data import create_demo_tick, ensure_demo_seed


class Command(BaseCommand):
    help = "Run the MarketImmune live demo simulator and store one row per second"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ticks",
            type=int,
            default=0,
            help="Number of ticks to generate. Default 0 runs until Ctrl+C.",
        )
        parser.add_argument(
            "--symbol",
            default="BTCUSDT",
            help="Symbol to show in the live demo.",
        )

    def handle(self, *args, **options):
        ensure_demo_seed()
        ticks = options["ticks"]
        symbol = options["symbol"]
        count = 0
        self.stdout.write(
            self.style.SUCCESS("Starting live MarketImmune demo. Press Ctrl+C to stop.")
        )
        try:
            while ticks == 0 or count < ticks:
                tick = create_demo_tick(symbol=symbol)
                alert = tick.alert.message if tick.alert else "no alert"
                self.stdout.write(
                    f"{tick.market_event.timestamp:%Y-%m-%d %H:%M:%S} "
                    f"{tick.market_event.symbol} mid={tick.market_event.mid_price:.2f} "
                    f"risk={tick.prediction.risk_score:.3f} "
                    f"label={tick.prediction.risk_label} alert={alert}"
                )
                count += 1
                if ticks == 0 or count < ticks:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nStopped live demo."))
