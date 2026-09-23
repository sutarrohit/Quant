const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 31_536_000],
  ['month', 2_592_000],
  ['week', 604_800],
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
];

/** "3 hours ago", "yesterday" -- from an ISO timestamp. */
export function timeAgo(iso: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  for (const [unit, size] of STEPS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return 'just now';
}

const num = (value: string | number) => (typeof value === 'number' ? value : Number(value));

/** "10,236.35" -- money from a decimal string. Display only; never computed with. */
export const money = (value: string | number, digits = 2) =>
  num(value).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** "+4.21%" -- the engine's percents are already ×100. */
export const percent = (value: string | number, signed = false) => {
  const n = num(value);
  return `${signed && n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

/** "3d 4h", "45m" -- a holding time in seconds. */
export function duration(seconds: number): string {
  const d = Math.floor(seconds / 86_400);
  const h = Math.floor((seconds % 86_400) / 3_600);
  const m = Math.floor((seconds % 3_600) / 60);
  if (d) return h ? `${d}d ${h}h` : `${d}d`;
  if (h) return m ? `${h}h ${m}m` : `${h}h`;
  return `${m}m`;
}

/** "1 Jan 2024" in UTC -- a backtest window is defined in UTC. */
export const utcDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

/** "1 Jan 2024, 14:15" in UTC. */
export const utcDateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  });
