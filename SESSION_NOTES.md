# Session Notes

## Project

- Hydroponics controller app for Raspberry Pi
- Pi host: `192.168.3.14`
- password: `'lolipop'`
- Pi app directory: `/home/pi/hp`
- GPIO mapping:
  - Grow Light 1: `23`
  - Grow Light 2: `25`
  - Pump: `24`

## What Was Built

- Python browser-based control app with:
  - Timeline-based daily visual schedule overview
  - Two independently controlled grow lights
  - Multiple lighting events per light
  - Interval-based repeating irrigation schedule
  - Manual light/pump overrides
  - GPIO pin and relay polarity settings
  - Persistent JSON config

## Important Fixes Made

- Reworked the UI layout to be more responsive and stable.
- Reworked the page order so it flows as:
  - Timeline
  - Schedule settings
  - Device status
  - GPIO settings
- Unified the UI color system so:
  - Grow Light 1 uses yellow
  - Grow Light 2 uses amber
  - Irrigation uses blue
- Fixed the GPIO settings panel layout and widened the GPIO number inputs.
- Fixed the lighting override behavior:
  - `Force On` / `Force Off` for a light no longer blocks the schedule forever.
  - Light overrides now expire automatically at the next lighting transition for that same light.
- Added dual grow light support:
  - Second grow light device on GPIO `25`
  - Separate scheduling and manual override controls for each light
  - Separate grow light lanes/counts in the scheduler timeline
  - Backward-compatible migration from the old single-light config shape
- Fixed the scheduler timezone behavior:
  - Scheduling no longer depends on the Raspberry Pi system timezone.
  - The app now uses the controller timezone directly.
  - The separate schedule timezone input was removed from the UI.
- Reworked the timeline behavior:
  - Timeline events now use hover/focus tooltips instead of inline text labels.
  - Lighting tooltips can render above the bar without being clipped.
  - Each grow light now has its own lane.
  - Irrigation events render in a single row.
  - Timeline tick marks are now the alignment reference for the event bars.
  - The Day Timeline panel is now at the top of the dashboard, directly below the intro.
  - The hour grid now spans the full timeline panel background so lighting and irrigation bars align against a shared day view.
  - Hour labels render at the top of the timeline area.
  - The red current-time marker is preserved across the shared timeline background.
  - The `Save Schedule` button now lives in the top-right corner of the Day Timeline panel.
- Reworked irrigation scheduling:
  - The old per-event irrigation editor was removed.
  - Irrigation is now configured by `interval_minutes` and `duration_seconds`.
  - Irrigation repeats across the day from midnight in the controller timezone.
- Fixed the server shutdown path:
  - Signal-triggered shutdown now runs `server.shutdown()` from a background thread.
  - This avoids hanging the process during restarts/stops.

## Current Live App State On Pi

- App URL: `http://192.168.3.14:8080`
- Verified live on `2026-07-15` after redeploy
- Current configured timezone: `Europe/Budapest`
- Current grow light schedules observed on `2026-07-15`:
  - Grow Light 1:
    - Enabled
    - `06:00` to `18:00`
  - Grow Light 2:
    - Enabled
    - `06:00` to `18:00`
- Current irrigation settings observed on `2026-07-15`:
  - Automation enabled
  - Interval: `10` minutes
  - Duration: `60` seconds
- Current device state observed via `GET /api/status` on `2026-07-15 13:04 Europe/Budapest`:
  - Grow Light 1: `On`, override `auto`
  - Grow Light 2: `On`, override `auto`
  - Irrigation Pump: `Off`, override `auto`
  - Next irrigation: `13:10` for `60` seconds
- Current backend service on Pi:
  - `hp.service`
  - Enabled in `systemd` and starts automatically after reboot/power cycle
  - Active process: `/usr/bin/python3 /home/pi/hp/app.py`
- Live verification performed on `2026-07-15`:
  - `GET /api/config`
  - `GET /api/status`
  - Homepage fetch confirmed the updated dual-light UI was deployed
  - Homepage fetch confirmed the Day Timeline panel is rendered before the scheduler panels
  - Stylesheet fetch confirmed the shared full-panel timeline background and top-right `Save Schedule` button styles are deployed
  - File checksums confirmed the Pi matches local copies for:
    - `app.py`
    - `templates/index.html`
    - `static/app.js`
    - `static/styles.css`

## Files Changed Locally

- `app.py`
- `templates/index.html`
- `static/app.js`
- `static/styles.css`
- `config.json`
- `README.md`
- `SESSION_NOTES.md`
- `tests/test_app.py`

## Files Deployed To Pi

- `/home/pi/hp/app.py`
- `/home/pi/hp/config.json`
- `/home/pi/hp/templates/index.html`
- `/home/pi/hp/static/app.js`
- `/home/pi/hp/static/styles.css`
- `/home/pi/hp/README.md`
- `/home/pi/hp/SESSION_NOTES.md`

## Notes For Next Session

- If the UI looks stale, do a hard browser refresh to clear cached CSS/JS.
- The Pi app is managed by `systemd` as `hp.service`.
- Useful service commands on the Pi:
  - `sudo systemctl status hp.service --no-pager`
  - `sudo systemctl restart hp.service`
  - `sudo journalctl -u hp.service -n 100 --no-pager`
- The Pi itself still appears to have a system timezone different from the app timezone, but that no longer affects scheduling because the app now uses its own configured timezone.
- The lighting config now uses:
  - `lighting.light`
  - `lighting.light_2`
  - Each light schedule has `enabled` and `events[]`
- The irrigation config uses:
  - `irrigation.enabled`
  - `irrigation.interval_minutes`
  - `irrigation.duration_seconds`
- The dashboard now shows a day timeline with:
  - Two grow light lanes and one irrigation lane aligned against a shared full-panel 24-hour background
  - Hour labels at the top of the panel
  - A moving current-time marker
  - Hover/focus tooltips on timeline events
- The `Save Schedule` button now sits in the Day Timeline panel header instead of the footer.
- Local and remote files were re-synced on `2026-07-15`.
- `config.json` in the local workspace was updated to match the live Pi settings:
  - Both grow light schedules enabled from `06:00` to `18:00`
  - Irrigation enabled every `10` minutes for `60` seconds
