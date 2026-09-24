const UNIT_SECONDS: Record<string, number> = { SECOND: 1, MINUTE: 60, HOUR: 3_600, DAY: 86_400 };

/** Seconds per bar: "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL" -> 900. Null if unrecognised. */
export function barSeconds(barType: string): number | null {
  const match = /-(\d+)-(SECOND|MINUTE|HOUR|DAY)-/.exec(barType);
  return match ? Number(match[1]) * (UNIT_SECONDS[match[2]!] ?? 0) : null;
}

/** A bar's close as the round time it is: Binance stamps "08:14:59.999" for the 08:15 close. */
export const barClose = (iso: string) => new Date(Math.round(Date.parse(iso) / 1000) * 1000).toISOString();
