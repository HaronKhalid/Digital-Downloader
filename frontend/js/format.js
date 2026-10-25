// Pure formatting helpers (no DOM access).

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Unknown";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const two = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

export function formatSize(bytes, approximate = false) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "Unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text = `${unit === 0 ? value : value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
  return approximate ? `about ${text}` : text;
}

export function formatSpeed(bytesPerSecond) {
  return Number.isFinite(bytesPerSecond) && bytesPerSecond > 0 ? `${formatSize(bytesPerSecond)}/s` : "—";
}

export function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h} h ${String(m).padStart(2, "0")} min`;
  return `${m} min ${String(s).padStart(2, "0")} s`;
}
