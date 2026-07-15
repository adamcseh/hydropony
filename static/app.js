const LIGHT_KEYS = ["light", "light_2"];
const DEFAULT_LIGHTING_EVENT = {
  start_time: "06:00",
  end_time: "18:00",
  enabled: true,
};

const state = {
  config: null,
  status: null,
  syncedServerNowMs: null,
  syncedAtMs: null,
};

const flashNode = document.getElementById("flash-message");
const lightingEventTemplate = document.getElementById("lighting-event-template");
const timelineHours = document.getElementById("timeline-hours");
const timelineNow = document.getElementById("timeline-now");
const timelineNowLabel = document.getElementById("timeline-now-label");
const deviceStatusNodes = {
  light: document.getElementById("light-status"),
  light_2: document.getElementById("light-2-status"),
  pump: document.getElementById("pump-status"),
};
const lightingSections = {
  light: {
    eventsContainer: document.getElementById("lighting-light-events"),
    addButton: document.getElementById("add-lighting-light-event"),
    timelineLane: document.getElementById("timeline-lighting-light"),
    countNode: document.getElementById("lighting-light-count"),
    pinInput: document.getElementById("light-pin"),
    activeLowInput: document.getElementById("light-active-low"),
    variant: "primary",
  },
  light_2: {
    eventsContainer: document.getElementById("lighting-light-2-events"),
    addButton: document.getElementById("add-lighting-light-2-event"),
    timelineLane: document.getElementById("timeline-lighting-light-2"),
    countNode: document.getElementById("lighting-light-2-count"),
    pinInput: document.getElementById("light-2-pin"),
    activeLowInput: document.getElementById("light-2-active-low"),
    variant: "secondary",
  },
};
const timelineIrrigation = document.getElementById("timeline-irrigation");

function flash(message, kind = "ok") {
  flashNode.textContent = message;
  flashNode.dataset.kind = kind;
  window.clearTimeout(flashNode._timeout);
  flashNode._timeout = window.setTimeout(() => {
    flashNode.textContent = "";
    flashNode.dataset.kind = "";
  }, 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function getDeviceName(deviceKey) {
  const configuredName = state.config?.devices?.[deviceKey]?.name;
  if (configuredName) {
    return configuredName;
  }
  const fallbackNames = {
    light: "Grow Light 1",
    light_2: "Grow Light 2",
    pump: "Irrigation Pump",
  };
  return fallbackNames[deviceKey] || deviceKey;
}

function timeToMinutes(value) {
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
}

function minutesToPercent(minutes) {
  return (minutes / (24 * 60)) * 100;
}

function sortByTime(items, getTime) {
  return [...items].sort((a, b) => timeToMinutes(getTime(a)) - timeToMinutes(getTime(b)));
}

function getSyncedNow() {
  if (state.syncedServerNowMs === null || state.syncedAtMs === null) {
    return new Date();
  }
  return new Date(state.syncedServerNowMs + (Date.now() - state.syncedAtMs));
}

function formatClock(date) {
  return new Intl.DateTimeFormat([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDateTime(date) {
  return new Intl.DateTimeFormat([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function getLightingSchedule(config, lightKey) {
  return config?.lighting?.[lightKey] || {
    events: [{ ...DEFAULT_LIGHTING_EVENT }],
  };
}

function hasEnabledLightingEvents(events) {
  return events.some((event) => Boolean(event.enabled));
}

function renderLightingEventRow(lightKey, event = DEFAULT_LIGHTING_EVENT) {
  const section = lightingSections[lightKey];
  const fragment = lightingEventTemplate.content.cloneNode(true);
  const row = fragment.querySelector(".lighting-event-row");
  row.dataset.lightKey = lightKey;
  if (section.variant === "secondary") {
    row.classList.add("lighting-event-row-secondary");
  }
  row.querySelector(".lighting-start").value = event.start_time;
  row.querySelector(".lighting-end").value = event.end_time;
  row.querySelector(".lighting-enabled-toggle").checked = Boolean(event.enabled);
  row.querySelector(".remove-lighting-event").addEventListener("click", () => {
    row.remove();
    renderTimeline();
  });
  row.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => renderTimeline());
    input.addEventListener("change", () => renderTimeline());
  });
  section.eventsContainer.appendChild(fragment);
}

function ensureTimelineHours() {
  if (timelineHours.childElementCount > 0) {
    return;
  }
  for (let hour = 0; hour < 24; hour += 1) {
    const tick = document.createElement("div");
    tick.className = "timeline-hour";
    tick.style.left = `${minutesToPercent(hour * 60)}%`;
    tick.dataset.label = `${String(hour).padStart(2, "0")}:00`;
    timelineHours.appendChild(tick);
  }
}

function createTimelineBar({ left, width, top, tooltip, className }) {
  const bar = document.createElement("div");
  bar.className = `timeline-event ${className}`;
  bar.style.left = `${left}%`;
  bar.style.width = `${width}%`;
  bar.style.top = `${top}rem`;
  bar.dataset.tooltip = tooltip;
  bar.setAttribute("aria-label", tooltip);
  bar.tabIndex = 0;
  return bar;
}

function renderLightingTimeline(lightKey, schedule) {
  const section = lightingSections[lightKey];
  const lane = section.timelineLane;
  lane.innerHTML = "";
  lane.dataset.laneLabel = getDeviceName(lightKey);

  const sorted = sortByTime(
    schedule.events.filter((event) => event.start_time && event.end_time && event.enabled),
    (event) => event.start_time,
  );

  sorted.forEach((event, index) => {
    const startMinutes = timeToMinutes(event.start_time);
    const endMinutes = timeToMinutes(event.end_time);
    const tooltip = `${getDeviceName(lightKey)}: ${event.start_time} to ${event.end_time}`;
    const rowOffset = 1.25 + (index % 3) * 2.05;
    const variantClass =
      section.variant === "secondary" ? "timeline-lighting-event-secondary" : "";

    if (endMinutes > startMinutes) {
      lane.appendChild(
        createTimelineBar({
          left: minutesToPercent(startMinutes),
          width: minutesToPercent(endMinutes - startMinutes),
          top: rowOffset,
          tooltip,
          className: `timeline-lighting-event ${variantClass}`.trim(),
        }),
      );
      return;
    }

    lane.appendChild(
      createTimelineBar({
        left: minutesToPercent(startMinutes),
        width: minutesToPercent(24 * 60 - startMinutes),
        top: rowOffset,
        tooltip: `${getDeviceName(lightKey)}: ${event.start_time} to 24:00`,
        className: `timeline-lighting-event overnight ${variantClass}`.trim(),
      }),
    );
    lane.appendChild(
      createTimelineBar({
        left: 0,
        width: minutesToPercent(endMinutes),
        top: rowOffset,
        tooltip: `${getDeviceName(lightKey)}: 00:00 to ${event.end_time}`,
        className: `timeline-lighting-event overnight ${variantClass}`.trim(),
      }),
    );
  });
}

function buildIrrigationTimelineEvents() {
  const intervalMinutes = Number(document.getElementById("irrigation-interval").value);
  const durationSeconds = Number(document.getElementById("irrigation-duration").value);
  const enabled = document.getElementById("irrigation-enabled").checked;

  if (!enabled || !Number.isFinite(intervalMinutes) || intervalMinutes <= 0) {
    return [];
  }
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    return [];
  }

  const events = [];
  for (let minute = 0; minute < 24 * 60; minute += intervalMinutes) {
    const hour = Math.floor(minute / 60);
    const minutePart = minute % 60;
    events.push({
      time: `${String(hour).padStart(2, "0")}:${String(minutePart).padStart(2, "0")}`,
      duration_seconds: durationSeconds,
    });
  }
  return events;
}

function renderIrrigationTimeline(events) {
  timelineIrrigation.innerHTML = "";
  events.forEach((event) => {
    const startMinutes = timeToMinutes(event.time);
    const durationMinutes = Math.max(event.duration_seconds / 60, 3);
    const widthMinutes = Math.min(durationMinutes, 24 * 60 - startMinutes);
    timelineIrrigation.appendChild(
      createTimelineBar({
        left: minutesToPercent(startMinutes),
        width: minutesToPercent(widthMinutes),
        top: 1.7,
        tooltip: `Irrigation: ${event.time} for ${event.duration_seconds}s`,
        className: "timeline-irrigation-event",
      }),
    );
  });
}

function updateNowMarker() {
  const now = getSyncedNow();
  const minutes = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
  timelineNow.style.left = `${minutesToPercent(minutes)}%`;
  timelineNowLabel.textContent = formatClock(now);
  document.getElementById("current-time").textContent = formatDateTime(now);
}

function collectLightingEvents(lightKey) {
  return [...lightingSections[lightKey].eventsContainer.querySelectorAll(".lighting-event-row")].map(
    (row) => ({
      start_time: row.querySelector(".lighting-start").value,
      end_time: row.querySelector(".lighting-end").value,
      enabled: row.querySelector(".lighting-enabled-toggle").checked,
    }),
  );
}

function renderTimeline() {
  ensureTimelineHours();

  LIGHT_KEYS.forEach((lightKey) => {
    const section = lightingSections[lightKey];
    const schedule = {
      events: collectLightingEvents(lightKey),
    };
    const activeEvents = schedule.events.filter(
      (event) => event.start_time && event.end_time && event.enabled,
    );

    section.countNode.textContent = String(activeEvents.length);
    renderLightingTimeline(lightKey, schedule);
  });

  const irrigationEvents = buildIrrigationTimelineEvents();
  document.getElementById("irrigation-count").textContent = String(irrigationEvents.length);
  renderIrrigationTimeline(irrigationEvents);
  updateNowMarker();
}

function syncDeviceLabels(config) {
  ["light", "light_2", "pump"].forEach((deviceKey) => {
    document.querySelectorAll(`[data-device-name="${deviceKey}"]`).forEach((node) => {
      node.textContent = config.devices[deviceKey].name;
    });
  });
}

function renderConfig(config) {
  state.config = config;
  syncDeviceLabels(config);

  LIGHT_KEYS.forEach((lightKey) => {
    const section = lightingSections[lightKey];
    const schedule = getLightingSchedule(config, lightKey);
    section.pinInput.value = config.devices[lightKey].pin;
    section.activeLowInput.checked = config.devices[lightKey].active_low;
    section.eventsContainer.innerHTML = "";
    (schedule.events || []).forEach((event) => renderLightingEventRow(lightKey, event));
    section.timelineLane.dataset.laneLabel = config.devices[lightKey].name;
  });

  document.getElementById("irrigation-enabled").checked = config.irrigation.enabled;
  document.getElementById("irrigation-interval").value = config.irrigation.interval_minutes;
  document.getElementById("irrigation-duration").value = config.irrigation.duration_seconds;
  document.getElementById("pump-pin").value = config.devices.pump.pin;
  document.getElementById("pump-active-low").checked = config.devices.pump.active_low;

  renderTimeline();
}

function formatOverride(label, until) {
  if (!until) {
    return label;
  }
  return `${label} until ${new Date(until).toLocaleString()}`;
}

function renderStatus(status) {
  state.status = status;
  state.syncedServerNowMs = new Date(status.now).getTime();
  state.syncedAtMs = Date.now();
  document.getElementById("current-timezone").textContent = status.timezone || "Unknown";
  document.getElementById("next-irrigation").textContent = status.next_irrigation
    ? `${status.next_irrigation.time} for ${status.next_irrigation.duration_seconds}s`
    : "No irrigation events";

  ["light", "light_2", "pump"].forEach((deviceKey) => {
    const device = status.devices[deviceKey];
    const label = device.is_on ? "On" : "Off";
    const override = device.override;
    deviceStatusNodes[deviceKey].textContent =
      override.mode === "auto"
        ? `${label} · auto`
        : `${label} · ${formatOverride(override.mode, override.until)}`;
  });

  updateNowMarker();
}

function collectConfig() {
  const lighting = {};
  LIGHT_KEYS.forEach((lightKey) => {
    const section = lightingSections[lightKey];
    const events = collectLightingEvents(lightKey);
    lighting[lightKey] = {
      enabled: hasEnabledLightingEvents(events),
      events,
    };
  });

  return {
    timezone: state.config.timezone || "Europe/Budapest",
    server: state.config.server,
    devices: {
      light: {
        ...state.config.devices.light,
        pin: Number(lightingSections.light.pinInput.value),
        active_low: lightingSections.light.activeLowInput.checked,
      },
      light_2: {
        ...state.config.devices.light_2,
        pin: Number(lightingSections.light_2.pinInput.value),
        active_low: lightingSections.light_2.activeLowInput.checked,
      },
      pump: {
        ...state.config.devices.pump,
        pin: Number(document.getElementById("pump-pin").value),
        active_low: document.getElementById("pump-active-low").checked,
      },
    },
    lighting,
    irrigation: {
      enabled: document.getElementById("irrigation-enabled").checked,
      interval_minutes: Number(document.getElementById("irrigation-interval").value),
      duration_seconds: Number(document.getElementById("irrigation-duration").value),
    },
  };
}

async function refreshAll() {
  const [config, status] = await Promise.all([api("/api/config"), api("/api/status")]);
  renderConfig(config);
  renderStatus(status);
}

async function saveConfig() {
  const payload = collectConfig();
  const response = await api("/api/config", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderConfig(response.config);
  await refreshStatus();
  flash("Schedule saved.");
}

async function refreshStatus() {
  const status = await api("/api/status");
  renderStatus(status);
}

async function setOverride(device, mode) {
  await api(`/api/device/${device}/override`, {
    method: "POST",
    body: JSON.stringify({
      mode,
      reason: "Updated from browser UI",
    }),
  });
  await refreshStatus();
  flash(`${getDeviceName(device)} override updated.`);
}

async function runPumpNow() {
  await api("/api/device/pump/run", {
    method: "POST",
    body: JSON.stringify({ duration_seconds: 60 }),
  });
  await refreshStatus();
  flash(`${getDeviceName("pump")} started for 60 seconds.`);
}

LIGHT_KEYS.forEach((lightKey) => {
  const section = lightingSections[lightKey];
  section.addButton.addEventListener("click", () => {
    renderLightingEventRow(lightKey);
    renderTimeline();
  });
});

document.getElementById("irrigation-enabled").addEventListener("change", () => renderTimeline());
document.getElementById("irrigation-interval").addEventListener("input", () => renderTimeline());
document.getElementById("irrigation-duration").addEventListener("input", () => renderTimeline());
document.getElementById("save-config").addEventListener("click", async () => {
  try {
    await saveConfig();
  } catch (error) {
    flash(error.message, "error");
  }
});
document.getElementById("refresh-status").addEventListener("click", async () => {
  try {
    await refreshStatus();
  } catch (error) {
    flash(error.message, "error");
  }
});
document.getElementById("run-pump-now").addEventListener("click", async () => {
  try {
    await runPumpNow();
  } catch (error) {
    flash(error.message, "error");
  }
});

document.querySelectorAll("[data-device]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await setOverride(button.dataset.device, button.dataset.mode);
    } catch (error) {
      flash(error.message, "error");
    }
  });
});

refreshAll().catch((error) => flash(error.message, "error"));
window.setInterval(() => {
  updateNowMarker();
}, 1000);
window.setInterval(() => {
  refreshStatus().catch(() => {});
}, 10000);
