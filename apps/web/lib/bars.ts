const UNIT_SECONDS: Record<string, number> = { SECOND: 1, MINUTE: 60, HOUR: 3_600, DAY: 86_400 };

/** Seconds per bar: "SOLUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL" -> 900. Null if unrecognised. */
export function barSeconds(barType: string): number | null {
  const match = /-(\d+)-(SECOND|MINUTE|HOUR|DAY)-/.exec(barType);
  return match ? Number(match[1]) * (UNIT_SECONDS[match[2]!] ?? 0) : null;
}
