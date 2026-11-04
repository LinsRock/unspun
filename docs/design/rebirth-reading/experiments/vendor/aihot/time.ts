// Beijing (Asia/Shanghai, fixed UTC+8, no DST) calendar helpers shared by web and backend.

const OFFSET_MS = 8 * 3600 * 1000;

/** YYYY-MM-DD of the instant in Beijing time. */
export function beijingDate(instant: Date | string | number): string {
  const d = new Date(new Date(instant).getTime() + OFFSET_MS);
  return d.toISOString().slice(0, 10);
}

/** HH:mm of the instant in Beijing time. */
export function beijingTime(instant: Date | string | number): string {
  const d = new Date(new Date(instant).getTime() + OFFSET_MS);
  return d.toISOString().slice(11, 16);
}
