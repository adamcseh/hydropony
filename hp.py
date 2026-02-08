#! /usr/bin/python3
from gpio_driver import Rpi_Gpio
import time
import csv
from datetime import datetime, timedelta
from typing import List, Dict

SCHEDULE_FILE = "schedule.csv"
DISPLAY_REFRESH_SEC = 1
GPIO_LIGHT = 23
GPIO_PUMP = 24

class ScheduledAction:
    def __init__(self, device: str, timestamp: datetime, action: str):
        self.device = device
        self.timestamp = timestamp
        self.action = action
    def __str__(self):
        return str(self.device)+';'+str(self.timestamp)+';'+str(self.action)

    def __lt__(self, other):
        return self.timestamp < other.timestamp

class GpioScheduler:
    def __init__(self, schedule_file:str):
        # GPIO mapping (BCM pins)
        self.devices: Dict[str, Rpi_Gpio] = {
            "light": Rpi_Gpio(GPIO_LIGHT, "out", default_output=False),
            "pump": Rpi_Gpio(GPIO_PUMP, "out", default_output=False),
        }
        self.schedule_file = schedule_file
        self.schedule: List[ScheduledAction] = []
        self.executed_actions = []

    # -----------------------------
    # Schedule handling
    # -----------------------------

    def load_schedule(self):
        self.schedule.clear()
        self.executed_actions.clear()
        with open(self.schedule_file, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    timestamp = datetime.strptime(
                        row["timestamp"], "%Y-%m-%d-%H-%M-%S"
                    )

                    action = row["action"].lower()
                    device = row["device"].lower()

                    if device not in self.devices:
                        raise ValueError(f"Unknown device '{device}'")

                    if action not in ("on", "off"):
                        raise ValueError(f"Invalid action '{action}'")

                    self.schedule.append(
                        ScheduledAction(device, timestamp, action)
                    )

                except Exception as e:
                    print(f"[SCHEDULE ERROR] Skipping row {row}: {e}")

        self.schedule.sort()
        [print(s) for s in self.schedule]

    # -----------------------------
    # Execution
    # -----------------------------

    def execute_due_actions(self, now: datetime):
        for action in self.schedule:
            action_id = (action.device, action.timestamp, action.action)

            if action_id in self.executed_actions:
                continue

            if now >= action.timestamp:
                gpio = self.devices[action.device]

                if action.action == "on":
                    gpio.on()
                else:
                    gpio.off()

                self.executed_actions.append(action_id)

                print(
                    f"[EXECUTED] {action.device.upper()} -> {action.action.upper()} "
                    f"at {action.timestamp}"
                )

    # -----------------------------
    # Display
    # -----------------------------

    def display_status(self, now: datetime):
        upcoming = [
            a for a in self.schedule
            if (a.device, a.timestamp, a.action) not in self.executed_actions
            and a.timestamp >= now
        ][:3]

        print("\033c", end="")  # clear terminal
        print("GPIO Scheduler running")
        print("=" * 40)
        print(f"Current time: {now}")
        print("\nNext actions:")

        if not upcoming:
            print("  (no upcoming actions)")
        else:
            for action in upcoming:
                print(
                    f"  {action.timestamp} | "
                    f"{action.device.upper()} -> {action.action.upper()}"
                )

    # -----------------------------
    # Main loop
    # -----------------------------

    def run(self):
        print('what')
        self.load_schedule()
        print("Schedule loaded. Running...\n")

        try:
            while True:
                now = datetime.now()
                self.execute_due_actions(now)
                self.display_status(now)
                time.sleep(DISPLAY_REFRESH_SEC)

        except KeyboardInterrupt:
            print("\nShutting down...")

        finally:
            for gpio in self.devices.values():
                gpio.cleanup()

def generate_test_schedule(schedule_file: str):
    """
    Create a short test schedule based on the current time.
    light ON  at now + 5 seconds
    pump  ON  at now + 5 seconds
    light OFF at now + 10 seconds
    pump  OFF at now + 10 seconds
    """
    now = datetime.now()
    on_time = now + timedelta(seconds=3)
    off_time = now + timedelta(seconds=10)
    rows = [
        ("light", on_time, "on"),
        ("pump", on_time, "on"),
        ("light", off_time, "off"),
        ("pump", off_time, "off"),
    ]
    with open(schedule_file, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # header (DictReader in scheduler expects this)
        writer.writerow(["device", "timestamp", "action"])

        for device, timestamp, action in rows:
            writer.writerow([
                device,
                timestamp.strftime("%Y-%m-%d-%H-%M-%S"),
                action,
            ])
    print(f"Test schedule written to {schedule_file}")

if __name__ == "__main__":
    generate_test_schedule('test_schedule.csv')
    scheduler = GpioScheduler('test_schedule.csv')
    scheduler.run()