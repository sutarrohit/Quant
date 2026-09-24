import { RiCheckboxCircleLine, RiPulseLine } from '@remixicon/react';

// Illustrative numbers for the hero mock, not a real run.
const EQUITY = [
  100, 101.2, 100.6, 102.9, 104.1, 103.2, 105.8, 107.4, 106.1, 108.9, 111.2, 110.4, 113.7, 112.5, 115.9, 118.3, 117.1,
  120.6, 123.4, 121.8, 125.2, 127.9, 126.6, 130.4,
];

const TILES = [
  { label: 'Total return', value: '+30.4%', tone: 'text-emerald-500' },
  { label: 'Sharpe', value: '1.82', tone: '' },
  { label: 'Max drawdown', value: '-4.9%', tone: 'text-red-500' },
  { label: 'Trades', value: '47', tone: '' },
];

const SPEC = `{
  "spec_version": "1",
  "symbol": "BTCUSDT",
  "bar_interval": "1h",
  "indicators": {
    "fast_period": 20,
    "slow_period": 50
  },
  "entry": { "rule": "fast_crosses_above_slow" },
  "exit": { "rule": "fast_crosses_below_slow" },
  "sizing": { "trade_size": "0.01" }
}`;

function equityPath(width: number, height: number) {
  const min = Math.min(...EQUITY);
  const max = Math.max(...EQUITY);
  const step = width / (EQUITY.length - 1);
  const pts = EQUITY.map((v, i) => [i * step, height - ((v - min) / (max - min)) * height]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x!.toFixed(1)},${y!.toFixed(1)}`).join(' ');
  return { line, area: `${line} L${width},${height} L0,${height} Z`, end: pts.at(-1)! };
}

export function HeroPreview() {
  const { line, area, end } = equityPath(560, 160);

  return (
    <div className="bg-card/70 relative grid gap-px overflow-hidden rounded-2xl border shadow-2xl shadow-emerald-500/5 backdrop-blur md:grid-cols-[5fr_7fr]">
      <div className="bg-card flex flex-col gap-3 p-5">
        <div className="text-muted-foreground flex items-center justify-between text-xs">
          <span>strategy-spec.json</span>
          <span className="flex items-center gap-1 text-emerald-500">
            <RiCheckboxCircleLine className="size-3.5" /> valid
          </span>
        </div>
        <pre className="text-muted-foreground overflow-x-auto text-[11px] leading-relaxed">
          <code>{SPEC}</code>
        </pre>
      </div>

      <div className="bg-card flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">BTCUSDT · SMA 20/50 · 1h</span>
          <span className="text-muted-foreground flex items-center gap-1">
            <RiPulseLine className="size-3.5" /> example backtest
          </span>
        </div>
        <div className="relative h-40">
          <svg viewBox="0 0 560 160" className="h-full w-full" preserveAspectRatio="none" aria-hidden>
            <defs>
              <linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="rgb(16 185 129)" stopOpacity="0.35" />
                <stop offset="100%" stopColor="rgb(16 185 129)" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path
              d={area}
              fill="url(#equity-fill)"
              className="motion-safe:animate-in motion-safe:fade-in fill-mode-both delay-[1800ms] duration-1000"
            />
            <path
              d={line}
              pathLength={1}
              fill="none"
              stroke="rgb(16 185 129)"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
              className="animate-draw"
            />
          </svg>
          {/* HTML dot so preserveAspectRatio="none" can't squash it into an ellipse. */}
          <span
            className="motion-safe:animate-in motion-safe:zoom-in fill-mode-both absolute size-2.5 -translate-1/2 delay-[2700ms]"
            style={{ left: `${(end[0]! / 560) * 100}%`, top: `${(end[1]! / 160) * 100}%` }}
          >
            <span className="absolute inset-0 animate-ping rounded-full bg-emerald-500/60" />
            <span className="absolute inset-0 rounded-full bg-emerald-500" />
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {TILES.map((t) => (
            <div key={t.label} className="bg-muted/50 rounded-lg px-3 py-2">
              <div className="text-muted-foreground text-[10px] uppercase tracking-wide">{t.label}</div>
              <div className={`text-sm font-semibold ${t.tone}`}>{t.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
