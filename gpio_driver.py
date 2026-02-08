import RPi.GPIO as GPIO
from typing import Optional
import time

# Use BCM pin numbering (GPIO numbers, not physical pin numbers)
GPIO.setmode(GPIO.BCM)

class Rpi_Gpio:
    """
    Wrapper class for Raspberry Pi GPIO pin control with safety checks.
    """

    VALID_DIRECTIONS = ("in", "out")
    VALID_PULLS = ("up", "down", None)

    def __init__(self,
        pin: int,
        direction: str,
        *,
        default_output: bool = False,
        pull: Optional[str] = None,
        mode=GPIO.BCM,
    ):
        """
        :param pin: GPIO pin number (BCM by default)
        :param direction: 'in' or 'out'
        :param default_output: Initial state if direction is 'out'
        :param pull: 'up', 'down', or None (only for inputs)
        :param mode: GPIO.BCM or GPIO.BOARD
        """

        if direction not in self.VALID_DIRECTIONS:
            raise ValueError(f"Invalid direction '{direction}'. Use 'in' or 'out'.")

        if pull not in self.VALID_PULLS:
            raise ValueError("pull must be 'up', 'down', or None")

        if direction == "out" and pull is not None:
            raise ValueError("Pull-up/down is not valid for output pins")

        GPIO.setmode(mode)

        self.pin = pin
        self.direction = direction
        self.pull = pull
        self.state = None
        self._initialized = False

        try:
            if self.direction == "out":
                GPIO.setup(self.pin, GPIO.OUT)
                GPIO.output(self.pin, GPIO.HIGH if default_output else GPIO.LOW)
                self.state = bool(default_output)

            else:
                pud = GPIO.PUD_OFF
                if pull == "up":
                    pud = GPIO.PUD_UP
                elif pull == "down":
                    pud = GPIO.PUD_DOWN

                GPIO.setup(self.pin, GPIO.IN, pull_up_down=pud)
                self.state = GPIO.input(self.pin) == GPIO.HIGH

            self._initialized = True

        except RuntimeError as e:
            raise RuntimeError(f"GPIO setup failed for pin {self.pin}: {e}")

    # -----------------------------
    # Internal helpers
    # -----------------------------

    def _require_initialized(self):
        if not self._initialized:
            raise RuntimeError("GPIO pin not initialized")

    def _require_output(self):
        if self.direction != "out":
            raise PermissionError("Cannot write to an input GPIO pin")

    def _require_input(self):
        if self.direction != "in":
            raise PermissionError("Cannot read from an output GPIO pin")

    # -----------------------------
    # Public API
    # -----------------------------

    def read(self) -> bool:
        """
        Read GPIO pin state.
        """
        self._require_initialized()
        self._require_input()

        try:
            self.state = GPIO.input(self.pin) == GPIO.HIGH
            return self.state
        except RuntimeError as e:
            raise RuntimeError(f"Failed to read GPIO pin {self.pin}: {e}")

    def write(self, value: bool):
        """
        Set GPIO output state.
        """
        self._require_initialized()
        self._require_output()

        try:
            GPIO.output(self.pin, GPIO.HIGH if value else GPIO.LOW)
            self.state = bool(value)
        except RuntimeError as e:
            raise RuntimeError(f"Failed to write GPIO pin {self.pin}: {e}")

    def on(self):
        """Set output HIGH."""
        self.write(True)

    def off(self):
        """Set output LOW."""
        self.write(False)

    def toggle(self):
        """Toggle output state."""
        self._require_initialized()
        self._require_output()

        new_state = not self.state
        self.write(new_state)

    def get_state(self) -> bool:
        """
        Return last known state (cached).
        """
        self._require_initialized()
        return bool(self.state)

    def cleanup(self):
        """
        Clean up GPIO pin.
        """
        if self._initialized:
            GPIO.cleanup(self.pin)
            self._initialized = False



