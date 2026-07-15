# HydroPi

Small browser-based automation app for a Raspberry Pi hydroponic setup.

## Features

- Two independently scheduled grow lights with overnight support.
- Interval-based irrigation scheduling with configurable run duration.
- Browser UI for editing schedules, GPIO pin settings, and manual overrides.
- Relay polarity setting for active-high or active-low modules.
- GPIO-free fallback logs when running outside a Raspberry Pi.

## Run

```bash
python3 app.py
```

Then open `http://<raspberry-pi-ip>:8080`.

## Validate config

```bash
python3 app.py --check
```

## Notes

- The default pins match this setup: grow light 1 `23`, grow light 2 `25`, pump `24`.
- If your relay board is active-low, enable that option in the UI before use.
