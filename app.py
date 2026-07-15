#!/usr/bin/env python3
import argparse
import json
import logging
import signal
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "runtime_state.json"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
LIGHT_DEVICE_NAMES = ("light", "light_2")
DEVICE_NAMES = LIGHT_DEVICE_NAMES + ("pump",)


def default_lighting_events(enabled: bool = True) -> List[Dict[str, Any]]:
    return [
        {
            "start_time": "06:00",
            "end_time": "18:00",
            "enabled": enabled,
        }
    ]


def default_lighting_schedule(enabled: bool) -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "events": default_lighting_events(enabled),
    }


def device_label(device_name: str) -> str:
    labels = {
        "light": "Grow Light 1",
        "light_2": "Grow Light 2",
        "pump": "Irrigation Pump",
    }
    return labels.get(device_name, device_name.replace("_", " ").title())


DEFAULT_CONFIG: Dict[str, Any] = {
    "timezone": "Europe/Budapest",
    "server": {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
    },
    "devices": {
        "light": {
            "pin": 23,
            "active_low": False,
            "name": "Grow Light 1",
        },
        "light_2": {
            "pin": 25,
            "active_low": False,
            "name": "Grow Light 2",
        },
        "pump": {
            "pin": 24,
            "active_low": False,
            "name": "Irrigation Pump",
        },
    },
    "lighting": {
        "light": default_lighting_schedule(True),
        "light_2": default_lighting_schedule(False),
    },
    "irrigation": {
        "enabled": False,
        "interval_minutes": 720,
        "duration_seconds": 60,
    },
}


try:
    import RPi.GPIO as GPIO  # type: ignore
except ImportError:  # pragma: no cover
    GPIO = None


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json_file(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return deepcopy(fallback)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json_file(path: Path, data: Dict[str, Any]) -> None:
    ensure_parent(path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")
    temp_path.replace(path)


def parse_time_value(value: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError("Time must be a string in HH:MM format.")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time '{value}'. Use HH:MM.")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid time '{value}'. Use HH:MM.")
    return hour, minute


def time_to_minutes(value: str) -> int:
    hour, minute = parse_time_value(value)
    return hour * 60 + minute


def time_in_window(current_minutes: int, start_minutes: int, end_minutes: int) -> bool:
    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes < end_minutes
    return current_minutes >= start_minutes or current_minutes < end_minutes


def validate_lighting_schedule(
    schedule_config: Dict[str, Any],
    default_schedule: Dict[str, Any],
    schedule_label: str,
) -> Dict[str, Any]:
    validated_schedule = deepcopy(default_schedule)

    raw_events = schedule_config.get("events")
    if raw_events is None:
        default_event = default_schedule["events"][0]
        raw_events = [
            {
                "start_time": str(
                    schedule_config.get("start_time", default_event["start_time"])
                ).strip(),
                "end_time": str(schedule_config.get("end_time", default_event["end_time"])).strip(),
                "enabled": bool(schedule_config.get("enabled", True)),
            }
        ]

    if not isinstance(raw_events, list):
        raise ValueError(f"{schedule_label} events must be a list.")

    validated_events: List[Dict[str, Any]] = []
    for index, event in enumerate(raw_events):
        if not isinstance(event, dict):
            raise ValueError(f"{schedule_label} event #{index + 1} must be an object.")
        start_time = str(event.get("start_time", "")).strip()
        end_time = str(event.get("end_time", "")).strip()
        parse_time_value(start_time)
        parse_time_value(end_time)
        if start_time == end_time:
            raise ValueError(
                f"{schedule_label} event #{index + 1} start and end time cannot be the same."
            )
        validated_events.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "enabled": bool(event.get("enabled", True)),
            }
        )

    validated_schedule["events"] = validated_events
    validated_schedule["enabled"] = any(event["enabled"] for event in validated_events)
    return validated_schedule


class MockGPIO:  # pragma: no cover
    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    @staticmethod
    def setmode(mode: str) -> None:
        logging.info("Mock GPIO mode=%s", mode)

    @staticmethod
    def setwarnings(flag: bool) -> None:
        logging.info("Mock GPIO warnings=%s", flag)

    @staticmethod
    def setup(pin: int, direction: str) -> None:
        logging.info("Mock GPIO setup pin=%s direction=%s", pin, direction)

    @staticmethod
    def output(pin: int, value: int) -> None:
        logging.info("Mock GPIO output pin=%s value=%s", pin, value)

    @staticmethod
    def cleanup(pin: Optional[int] = None) -> None:
        logging.info("Mock GPIO cleanup pin=%s", pin)


GPIO_BACKEND = GPIO or MockGPIO


class RelayDevice:
    def __init__(self, name: str, pin: int, active_low: bool):
        self.name = name
        self.pin = pin
        self.active_low = active_low
        self.is_on = False
        GPIO_BACKEND.setup(self.pin, GPIO_BACKEND.OUT)
        self.set_state(False)

    def set_state(self, logical_on: bool) -> None:
        physical_on = GPIO_BACKEND.LOW if self.active_low else GPIO_BACKEND.HIGH
        physical_off = GPIO_BACKEND.HIGH if self.active_low else GPIO_BACKEND.LOW
        GPIO_BACKEND.output(self.pin, physical_on if logical_on else physical_off)
        self.is_on = logical_on

    def cleanup(self) -> None:
        try:
            self.set_state(False)
        finally:
            GPIO_BACKEND.cleanup(self.pin)


@dataclass
class OverrideState:
    mode: Optional[str] = None
    until: Optional[datetime] = None
    reason: str = ""

    def active(self, current_time: datetime) -> bool:
        if self.mode is None:
            return False
        if self.until is None:
            return True
        return current_time < self.until

    def label(self) -> str:
        if self.mode is None:
            return "auto"
        return self.mode


class HydroController:
    def __init__(self, config_path: Path, state_path: Path):
        self.config_path = config_path
        self.state_path = state_path
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.config = self._load_config()
        self.state = self._load_state()
        self.devices = self._init_devices()
        self.overrides = {name: OverrideState() for name in self.devices}
        self.active_irrigation: Optional[Dict[str, Any]] = None
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="scheduler",
            daemon=True,
        )

    def _load_config(self) -> Dict[str, Any]:
        config = load_json_file(self.config_path, DEFAULT_CONFIG)
        return self._validate_config(config)

    def _get_timezone(self) -> ZoneInfo:
        timezone_name = self.config.get("timezone", DEFAULT_CONFIG["timezone"])
        try:
            return ZoneInfo(str(timezone_name))
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone '{timezone_name}'.") from exc

    def now_local(self) -> datetime:
        return datetime.now(self._get_timezone())

    def _load_state(self) -> Dict[str, Any]:
        fallback = {"last_irrigation_slot": None}
        state = load_json_file(self.state_path, fallback)
        if "last_irrigation_slot" not in state:
            state["last_irrigation_slot"] = None
        return state

    def _enabled_lighting_events(self, device_name: str) -> List[Dict[str, Any]]:
        return [
            event
            for event in self.config["lighting"][device_name]["events"]
            if event["enabled"]
        ]

    def _init_devices(self) -> Dict[str, RelayDevice]:
        GPIO_BACKEND.setwarnings(False)
        GPIO_BACKEND.setmode(GPIO_BACKEND.BCM)
        devices: Dict[str, RelayDevice] = {}
        for device_name, settings in self.config["devices"].items():
            devices[device_name] = RelayDevice(
                name=settings["name"],
                pin=int(settings["pin"]),
                active_low=bool(settings["active_low"]),
            )
        return devices

    def _validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(DEFAULT_CONFIG)
        merged["timezone"] = str(config.get("timezone", merged["timezone"]))
        merged["server"].update(config.get("server", {}))
        for name in DEVICE_NAMES:
            merged["devices"][name].update(config.get("devices", {}).get(name, {}))
        lighting_config = config.get("lighting", {})
        if not isinstance(lighting_config, dict):
            raise ValueError("Lighting settings must be an object.")

        has_explicit_light_schedules = any(name in lighting_config for name in LIGHT_DEVICE_NAMES)
        legacy_lighting_config = lighting_config if not has_explicit_light_schedules else None
        for device_name in LIGHT_DEVICE_NAMES:
            raw_schedule = lighting_config.get(device_name)
            if raw_schedule is None:
                if device_name == "light" and legacy_lighting_config is not None:
                    raw_schedule = legacy_lighting_config
                else:
                    raw_schedule = merged["lighting"][device_name]
            if not isinstance(raw_schedule, dict):
                raise ValueError(f"{device_label(device_name)} settings must be an object.")
            merged["lighting"][device_name] = validate_lighting_schedule(
                raw_schedule,
                merged["lighting"][device_name],
                device_label(device_name),
            )

        irrigation_config = config.get("irrigation", {})
        if not isinstance(irrigation_config, dict):
            raise ValueError("Irrigation settings must be an object.")
        merged["irrigation"]["enabled"] = bool(
            irrigation_config.get("enabled", merged["irrigation"]["enabled"])
        )

        if "interval_minutes" in irrigation_config or "duration_seconds" in irrigation_config:
            interval_minutes = int(
                irrigation_config.get("interval_minutes", merged["irrigation"]["interval_minutes"])
            )
            duration_seconds = int(
                irrigation_config.get("duration_seconds", merged["irrigation"]["duration_seconds"])
            )
        else:
            raw_events = irrigation_config.get("events", [])
            if not isinstance(raw_events, list):
                raise ValueError("Irrigation events must be a list.")
            enabled_events = []
            for index, event in enumerate(raw_events):
                if not isinstance(event, dict):
                    raise ValueError(f"Irrigation event #{index + 1} must be an object.")
                event_time = str(event.get("time", "")).strip()
                parse_time_value(event_time)
                duration_seconds = int(event.get("duration_seconds", 0))
                if duration_seconds <= 0:
                    raise ValueError(
                        f"Irrigation event #{index + 1} must have a positive duration."
                    )
                if bool(event.get("enabled", True)):
                    enabled_events.append({"time": event_time, "duration_seconds": duration_seconds})

            if len(enabled_events) >= 2:
                sorted_events = sorted(enabled_events, key=lambda event: time_to_minutes(event["time"]))
                interval_minutes = max(
                    1,
                    time_to_minutes(sorted_events[1]["time"]) - time_to_minutes(sorted_events[0]["time"]),
                )
                duration_seconds = int(sorted_events[0]["duration_seconds"])
            elif len(enabled_events) == 1:
                interval_minutes = merged["irrigation"]["interval_minutes"]
                duration_seconds = int(enabled_events[0]["duration_seconds"])
            else:
                interval_minutes = merged["irrigation"]["interval_minutes"]
                duration_seconds = merged["irrigation"]["duration_seconds"]

        if interval_minutes <= 0:
            raise ValueError("Irrigation interval must be a positive number of minutes.")
        if duration_seconds <= 0:
            raise ValueError("Irrigation duration must be a positive number of seconds.")
        if duration_seconds > interval_minutes * 60:
            raise ValueError("Irrigation duration cannot be longer than the irrigation interval.")

        merged["irrigation"]["interval_minutes"] = interval_minutes
        merged["irrigation"]["duration_seconds"] = duration_seconds

        server_port = int(merged["server"]["port"])
        if server_port < 1 or server_port > 65535:
            raise ValueError("Server port must be between 1 and 65535.")
        merged["server"]["port"] = server_port
        merged["server"]["host"] = str(merged["server"]["host"])
        try:
            ZoneInfo(merged["timezone"])
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone '{merged['timezone']}'.") from exc

        used_pins = set()
        for name in DEVICE_NAMES:
            pin = int(merged["devices"][name]["pin"])
            if pin <= 0:
                raise ValueError(f"{device_label(name)} GPIO pin must be positive.")
            if pin in used_pins:
                raise ValueError("Each device needs a unique GPIO pin.")
            used_pins.add(pin)
            merged["devices"][name]["pin"] = pin
            merged["devices"][name]["active_low"] = bool(merged["devices"][name]["active_low"])
            merged["devices"][name]["name"] = device_label(name)

        return merged

    def start(self) -> None:
        self.scheduler_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        for device in self.devices.values():
            device.cleanup()

    def save_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        validated = self._validate_config(new_config)
        with self.lock:
            current_pins = {name: self.config["devices"][name]["pin"] for name in self.devices}
            next_pins = {name: validated["devices"][name]["pin"] for name in self.devices}
            next_polarity = {
                name: validated["devices"][name]["active_low"] for name in self.devices
            }

            self.config = validated
            save_json_file(self.config_path, self.config)

            if current_pins != next_pins or any(
                self.devices[name].active_low != next_polarity[name] for name in self.devices
            ):
                for device in self.devices.values():
                    device.cleanup()
                self.devices = self._init_devices()
                self.active_irrigation = None

        return deepcopy(self.config)

    def get_config(self) -> Dict[str, Any]:
        with self.lock:
            return deepcopy(self.config)

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            current_time = self.now_local()
            devices_status = {}
            for device_name, device in self.devices.items():
                devices_status[device_name] = {
                    "is_on": device.is_on,
                    "override": self._override_snapshot(device_name, current_time),
                }
            return {
                "now": current_time.isoformat(),
                "timezone": self.config["timezone"],
                "devices": devices_status,
                "active_irrigation": deepcopy(self.active_irrigation),
                "next_irrigation": self._next_irrigation_event(current_time),
                "config": deepcopy(self.config),
            }

    def _override_snapshot(self, device_name: str, current_time: datetime) -> Dict[str, Any]:
        override = self.overrides[device_name]
        if not override.active(current_time):
            return {"mode": "auto", "reason": "", "until": None}
        return {
            "mode": override.label(),
            "reason": override.reason,
            "until": override.until.isoformat() if override.until else None,
        }

    def set_override(
        self,
        device_name: str,
        mode: str,
        duration_seconds: Optional[int] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        if device_name not in self.devices:
            raise ValueError("Unknown device.")
        if mode not in {"auto", "force_on", "force_off"}:
            raise ValueError("Override mode must be auto, force_on, or force_off.")

        with self.lock:
            if mode == "auto":
                self.overrides[device_name] = OverrideState()
            else:
                until = None
                if duration_seconds is not None:
                    if duration_seconds <= 0:
                        raise ValueError("Override duration must be positive.")
                    until = self.now_local() + timedelta(seconds=duration_seconds)
                elif device_name in LIGHT_DEVICE_NAMES:
                    until = self._next_light_transition(device_name, self.now_local())
                self.overrides[device_name] = OverrideState(
                    mode=mode,
                    until=until,
                    reason=reason,
                )
        return self.get_status()

    def _next_light_transition(
        self,
        device_name: str,
        current_time: datetime,
    ) -> Optional[datetime]:
        enabled_events = self._enabled_lighting_events(device_name)
        if not enabled_events:
            return None

        future_candidates: List[datetime] = []
        for event in enabled_events:
            start_hour, start_minute = parse_time_value(event["start_time"])
            end_hour, end_minute = parse_time_value(event["end_time"])
            candidates = [
                current_time.replace(
                    hour=start_hour,
                    minute=start_minute,
                    second=0,
                    microsecond=0,
                ),
                current_time.replace(
                    hour=end_hour,
                    minute=end_minute,
                    second=0,
                    microsecond=0,
                ),
            ]

            for candidate in candidates:
                if candidate <= current_time:
                    candidate += timedelta(days=1)
                future_candidates.append(candidate)

        if not future_candidates:
            return None
        return min(future_candidates)

    def run_pump_now(self, duration_seconds: int) -> Dict[str, Any]:
        return self.set_override(
            device_name="pump",
            mode="force_on",
            duration_seconds=duration_seconds,
            reason="Manual irrigation run",
        )

    def _scheduler_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._scheduler_tick()
            except Exception:
                logging.exception("Scheduler tick failed")
            self.stop_event.wait(1)

    def _scheduler_tick(self) -> None:
        with self.lock:
            current_time = self.now_local()
            self._expire_overrides(current_time)
            self._update_irrigation_state(current_time)
            self._apply_light_states(current_time)
            self._apply_pump_state(current_time)

    def _expire_overrides(self, current_time: datetime) -> None:
        for override in self.overrides.values():
            if override.mode and override.until and current_time >= override.until:
                override.mode = None
                override.until = None
                override.reason = ""

    def _light_target_state(self, device_name: str, current_time: datetime) -> bool:
        override = self.overrides[device_name]
        if override.active(current_time):
            return override.mode == "force_on"

        enabled_events = self._enabled_lighting_events(device_name)
        if not enabled_events:
            return False

        current_minutes = current_time.hour * 60 + current_time.minute
        return any(
            time_in_window(
                current_minutes,
                time_to_minutes(event["start_time"]),
                time_to_minutes(event["end_time"]),
            )
            for event in enabled_events
        )

    def _apply_light_states(self, current_time: datetime) -> None:
        for device_name in LIGHT_DEVICE_NAMES:
            target_on = self._light_target_state(device_name, current_time)
            if self.devices[device_name].is_on != target_on:
                self.devices[device_name].set_state(target_on)
                logging.info(
                    "%s switched %s",
                    self.config["devices"][device_name]["name"],
                    "ON" if target_on else "OFF",
                )

    def _update_irrigation_state(self, current_time: datetime) -> None:
        irrigation_config = self.config["irrigation"]
        if self.active_irrigation and current_time >= datetime.fromisoformat(self.active_irrigation["end_at"]):
            logging.info("Irrigation event finished")
            self.active_irrigation = None

        if not irrigation_config["enabled"]:
            return

        interval_minutes = int(irrigation_config["interval_minutes"])
        duration_seconds = int(irrigation_config["duration_seconds"])
        current_day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        current_minutes = current_time.hour * 60 + current_time.minute
        slot_minutes = (current_minutes // interval_minutes) * interval_minutes
        start_time = current_day_start + timedelta(minutes=slot_minutes)
        end_time = start_time + timedelta(seconds=duration_seconds)
        slot_key = f"{current_time.date().isoformat()}_{slot_minutes}"

        should_start = False
        if self.state["last_irrigation_slot"] != slot_key and start_time <= current_time < end_time:
            should_start = True
        elif (
            self.state["last_irrigation_slot"] != slot_key
            and current_time >= start_time
            and current_time < start_time + timedelta(seconds=55)
        ):
            should_start = True

        if should_start:
            slot_label = f"{start_time.strftime('%H:%M')} every {interval_minutes} min for {duration_seconds}s"
            self.active_irrigation = {
                "event_key": slot_key,
                "label": slot_label,
                "start_at": start_time.isoformat(),
                "end_at": end_time.isoformat(),
            }
            self.state["last_irrigation_slot"] = slot_key
            save_json_file(self.state_path, self.state)
            logging.info(
                "Irrigation event started at %s for %s seconds on %s-minute interval",
                start_time.strftime("%H:%M"),
                duration_seconds,
                interval_minutes,
            )

    def _apply_pump_state(self, current_time: datetime) -> None:
        override = self.overrides["pump"]
        if override.active(current_time):
            target_on = override.mode == "force_on"
        else:
            target_on = self.active_irrigation is not None

        if self.devices["pump"].is_on != target_on:
            self.devices["pump"].set_state(target_on)
            logging.info("Pump switched %s", "ON" if target_on else "OFF")

    def _next_irrigation_event(self, current_time: datetime) -> Optional[Dict[str, Any]]:
        irrigation_config = self.config["irrigation"]
        if not irrigation_config["enabled"]:
            return None
        interval_minutes = int(irrigation_config["interval_minutes"])
        duration_seconds = int(irrigation_config["duration_seconds"])
        day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        current_minutes = current_time.hour * 60 + current_time.minute
        next_slot_minutes = ((current_minutes // interval_minutes) + 1) * interval_minutes
        candidate = day_start + timedelta(minutes=next_slot_minutes)
        if candidate <= current_time:
            candidate += timedelta(minutes=interval_minutes)
        return {
            "time": candidate.strftime("%H:%M"),
            "duration_seconds": duration_seconds,
            "interval_minutes": interval_minutes,
            "starts_at": candidate.isoformat(),
        }


class HydroRequestHandler(BaseHTTPRequestHandler):
    controller: HydroController
    server_version = "HydroPi/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(TEMPLATES_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/static/"):
            relative_path = parsed.path.removeprefix("/static/")
            file_path = STATIC_DIR / relative_path
            if file_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif file_path.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            else:
                content_type = "application/octet-stream"
            self._serve_file(file_path, content_type)
            return
        if parsed.path == "/api/config":
            self._send_json(self.controller.get_config())
            return
        if parsed.path == "/api/status":
            self._send_json(self.controller.get_status())
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Route not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        payload = self._read_json_body()
        if parsed.path == "/api/config":
            try:
                config = self.controller.save_config(payload)
            except Exception as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"ok": True, "config": config})
            return
        if parsed.path == "/api/device/pump/run":
            try:
                duration_seconds = int(payload.get("duration_seconds", 60))
                status = self.controller.run_pump_now(duration_seconds)
            except Exception as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"ok": True, "status": status})
            return
        device_override_path = parsed.path.split("/")
        if (
            len(device_override_path) == 5
            and device_override_path[1] == "api"
            and device_override_path[2] == "device"
            and device_override_path[4] == "override"
        ):
            self._handle_override(device_override_path[3], payload)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Route not found")

    def _handle_override(self, device_name: str, payload: Dict[str, Any]) -> None:
        try:
            status = self.controller.set_override(
                device_name=device_name,
                mode=str(payload.get("mode", "auto")),
                duration_seconds=payload.get("duration_seconds"),
                reason=str(payload.get("reason", "")).strip(),
            )
        except Exception as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._send_json({"ok": True, "status": status})

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        return data

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def log_message(self, format: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), format % args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hydroponics scheduler web app")
    parser.add_argument("--host", default=None, help="HTTP bind host")
    parser.add_argument("--port", default=None, type=int, help="HTTP bind port")
    parser.add_argument("--check", action="store_true", help="Validate config and exit")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    parser = build_parser()
    args = parser.parse_args()

    controller = HydroController(CONFIG_PATH, STATE_PATH)
    if args.check:
        print("Configuration is valid.")
        controller.stop()
        return

    config = controller.get_config()
    host = args.host or config["server"]["host"]
    port = args.port or config["server"]["port"]

    controller.start()
    HydroRequestHandler.controller = controller
    server = ThreadingHTTPServer((host, port), HydroRequestHandler)

    def shutdown_handler(signum: int, frame: Any) -> None:
        logging.info("Received signal %s, shutting down", signum)
        threading.Thread(target=server.shutdown, name="server-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    logging.info("Starting HydroPi server on http://%s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        controller.stop()


if __name__ == "__main__":
    main()
