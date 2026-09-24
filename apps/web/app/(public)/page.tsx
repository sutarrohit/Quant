import Link from 'next/link';
import { Suspense } from 'react';
import {
  RiArrowRightLine,
  RiArrowRightUpLine,
  RiChat3Line,
  RiCheckboxCircleLine,
  RiCodeSSlashLine,
  RiFlaskLine,
  RiKey2Line,
  RiLineChartLine,
  RiLockLine,
  RiRepeatLine,
  RiRobot2Line,
  RiShieldCheckLine,
} from '@remixicon/react';

import { AuthLink, LoginFromRedirect, SignInButton } from '@/components/auth/auth-link';
import { GridBeams } from '@/components/landing/grid-beams';
import { HeroPreview } from '@/components/landing/hero-preview';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const STEPS = [
  {
    icon: RiChat3Line,
    title: 'Describe',
    body: 'Build a strategy from indicators, entry and exit rules. It compiles into a versioned, validated spec.',
  },
  {
    icon: RiFlaskLine,
    title: 'Backtest',
    body: 'Run the spec on real Binance spot bars. Every run is saved with its trades, stats and equity curve.',
  },
  {
    icon: RiRepeatLine,
    title: 'Simulate',
    body: 'Paper-trade the exact same spec against live prices, warmed from past bars so it starts where the backtest left off.',
  },
];

const FEATURES = [
  {
    icon: RiCodeSSlashLine,
    title: 'Deterministic specs',
    body: 'Strategies are data, not code. Same spec plus same bars gives the same trades, every time.',
  },
  {
    icon: RiLineChartLine,
    title: 'One engine, every mode',
    body: 'Backtest, paper and live all run on NautilusTrader with identical strategy bytes. No drift between sim and reality.',
  },
  {
    icon: RiShieldCheckLine,
    title: 'Risk gate the AI can’t touch',
    body: 'Every order passes deterministic limits before it leaves. No prompt can talk its way past them.',
    soon: true,
  },
  {
    icon: RiCheckboxCircleLine,
    title: 'Copilot approvals',
    body: 'Live orders wait for your tap. You see the intent, the size and the risk check, then decide.',
    soon: true,
  },
];

const PROMPTS = [
  'Buy BTC when the 20h SMA crosses above the 50h, exit on the cross back',
  'How did an ETH mean-reversion strategy hold up through the last drawdown?',
  'Trade 0.01 BTC per entry and never hold more than one position',
  'Compare my SOL breakout spec on 1h versus 4h bars',
];

const CAN = [
  'Research markets and summarise evidence',
  'Draft and explain strategy specs',
  'Suggest parameter changes to test',
];

const CANNOT = [
  'Read or store your exchange keys',
  'Submit, modify or cancel orders',
  'Override a risk limit or skip your approval',
];

function Nav() {
  return (
    <header className="bg-background/70 sticky top-0 z-50 border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="flex size-7 items-center justify-center rounded-md bg-emerald-500 text-black">
            <RiLineChartLine className="size-4" />
          </span>
          Quant
        </Link>
        <nav className="text-muted-foreground hidden items-center gap-6 text-sm md:flex">
          <a href="#how" className="hover:text-foreground">
            How it works
          </a>
          <a href="#features" className="hover:text-foreground">
            Features
          </a>
          <a href="#safety" className="hover:text-foreground">
            Safety
          </a>
        </nav>
        <div className="flex items-center gap-2">
          <SignInButton className={buttonVariants({ variant: 'ghost' })} />
          <AuthLink href="/dashboard" className={buttonVariants()}>
            Open app
          </AuthLink>
        </div>
      </div>
    </header>
  );
}

// Fade-up on load; fill-mode-both keeps delayed items hidden until their turn.
const REVEAL =
  'motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-4 duration-700 fill-mode-both';

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <GridBeams />
      <div
        aria-hidden
        className="absolute top-[-10rem] left-1/2 -z-10 h-[28rem] w-[48rem] -translate-x-1/2 rounded-full bg-emerald-500/20 blur-3xl"
      />

      <div className="mx-auto flex max-w-6xl flex-col items-center px-4 pt-20 pb-16 text-center md:pt-28">
        <span
          className={cn(
            REVEAL,
            'text-muted-foreground bg-background/60 mb-6 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs'
          )}
        >
          <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
          Paper trading on live Binance spot prices
        </span>
        <h1 className={cn(REVEAL, 'max-w-3xl text-4xl font-bold tracking-tight text-balance delay-100 sm:text-6xl')}>
          Run your own{' '}
          <span className="bg-gradient-to-r from-emerald-400 via-cyan-400 to-emerald-400 bg-[length:200%_auto] bg-clip-text text-transparent motion-safe:animate-[shimmer_6s_linear_infinite]">
            quant desk
          </span>
        </h1>
        <p className={cn(REVEAL, 'text-muted-foreground mt-6 max-w-2xl text-base text-balance delay-200 sm:text-lg')}>
          Describe a strategy, backtest it on real market data, and paper-trade the exact same spec. One engine from
          research to live, and the AI never touches your keys.
        </p>
        <div className={cn(REVEAL, 'mt-8 flex flex-wrap justify-center gap-3 delay-300')}>
          <AuthLink href="/strategies/new" className={buttonVariants({ size: 'lg', className: 'px-4' })}>
            Build a strategy <RiArrowRightLine />
          </AuthLink>
          <a href="#how" className={buttonVariants({ size: 'lg', variant: 'outline', className: 'px-4' })}>
            See how it works
          </a>
        </div>

        <div className={cn(REVEAL, 'mt-16 w-full max-w-5xl text-left delay-500 duration-1000')}>
          <HeroPreview />
        </div>
      </div>
    </section>
  );
}

function Pillars() {
  const items = [
    ['1 spec', 'backtest, paper, live'],
    ['0', 'LLM calls on the order path'],
    ['Real', 'Binance spot market data'],
    ['Per-trade', 'human approval for live'],
  ];
  return (
    <section className="border-y">
      <div className="mx-auto grid max-w-6xl grid-cols-2 px-4 md:grid-cols-4">
        {items.map(([big, small]) => (
          <div key={small} className="border-border/60 px-4 py-8 text-center [&:not(:last-child)]:md:border-r">
            <div className="text-2xl font-bold">{big}</div>
            <div className="text-muted-foreground mt-1 text-xs">{small}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body?: string }) {
  return (
    <div className="mx-auto mb-12 max-w-2xl text-center">
      <div className="mb-3 text-xs font-medium tracking-widest text-emerald-500 uppercase">{eyebrow}</div>
      <h2 className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">{title}</h2>
      {body && <p className="text-muted-foreground mt-4 text-balance">{body}</p>}
    </div>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24">
      <SectionHeading
        eyebrow="How it works"
        title="From idea to running strategy in three steps"
        body="No notebooks to keep in sync, no rewrite between research and execution."
      />
      <div className="grid gap-4 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <div key={s.title} className="bg-card relative rounded-2xl border p-6">
            <div className="text-muted-foreground absolute top-6 right-6 text-xs">0{i + 1}</div>
            <s.icon className="mb-4 size-6 text-emerald-500" />
            <h3 className="mb-2 font-semibold">{s.title}</h3>
            <p className="text-muted-foreground text-sm leading-relaxed">{s.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="bg-muted/30 scroll-mt-20 border-y">
      <div className="mx-auto max-w-6xl px-4 py-24">
        <SectionHeading eyebrow="Features" title="Built so the backtest is the truth" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="bg-card group rounded-2xl border p-6 transition-colors hover:border-emerald-500/40"
            >
              <div className="mb-4 flex items-center justify-between">
                <f.icon className="size-6 text-emerald-500" />
                {f.soon && (
                  <span className="text-muted-foreground rounded-full border px-2 py-0.5 text-[10px]">Soon</span>
                )}
              </div>
              <h3 className="mb-2 font-semibold">{f.title}</h3>
              <p className="text-muted-foreground text-sm leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Prompts() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-24">
      <SectionHeading
        eyebrow="AI research · coming soon"
        title="Ask like a trader, get a spec back"
        body="Plain-language ideas become evidence-backed analysis and a validated strategy you can test."
      />
      <div className="grid gap-3 md:grid-cols-2">
        {PROMPTS.map((p) => (
          <div key={p} className="bg-card flex items-center justify-between gap-4 rounded-xl border px-5 py-4 text-sm">
            <span className="flex items-start gap-3">
              <RiRobot2Line className="text-muted-foreground mt-0.5 size-4 shrink-0" />
              {p}
            </span>
            <RiArrowRightUpLine className="text-muted-foreground size-4 shrink-0" />
          </div>
        ))}
      </div>
    </section>
  );
}

function Safety() {
  return (
    <section id="safety" className="scroll-mt-20 border-t">
      <div className="mx-auto max-w-6xl px-4 py-24">
        <SectionHeading
          eyebrow="Safety"
          title="The AI advises. You and the risk gate decide."
          body="Credentials and order submission live outside the model's reach, by design rather than by prompt."
        />
        <div className="grid gap-4 md:grid-cols-2">
          <div className="bg-card rounded-2xl border p-6">
            <div className="mb-4 flex items-center gap-2 font-semibold">
              <RiRobot2Line className="size-5 text-emerald-500" /> The AI can
            </div>
            <ul className="space-y-3 text-sm">
              {CAN.map((c) => (
                <li key={c} className="flex gap-2">
                  <RiCheckboxCircleLine className="size-4 shrink-0 text-emerald-500" /> {c}
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-card rounded-2xl border p-6">
            <div className="mb-4 flex items-center gap-2 font-semibold">
              <RiLockLine className="size-5 text-red-500" /> The AI can never
            </div>
            <ul className="space-y-3 text-sm">
              {CANNOT.map((c) => (
                <li key={c} className="flex gap-2">
                  <RiKey2Line className="size-4 shrink-0 text-red-500" /> {c}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="mx-auto max-w-6xl px-4 pb-24">
      <div className="relative overflow-hidden rounded-3xl border bg-gradient-to-br from-emerald-500/15 via-transparent to-cyan-500/15 px-6 py-16 text-center">
        <h2 className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">
          Test the idea before you trust it
        </h2>
        <p className="text-muted-foreground mx-auto mt-4 max-w-xl text-balance">
          Write your first strategy, run it on real data, and watch it paper-trade in minutes.
        </p>
        <AuthLink href="/strategies/new" className={cn(buttonVariants({ size: 'lg' }), 'mt-8 px-4')}>
          Get started <RiArrowRightLine />
        </AuthLink>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t">
      <div className="text-muted-foreground mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 text-xs sm:flex-row">
        <span>© {new Date().getFullYear()} Quant. Not financial advice. Trading involves risk.</span>
        <nav className="flex gap-5">
          <AuthLink href="/strategies" className="hover:text-foreground">
            Strategies
          </AuthLink>
          <AuthLink href="/backtests" className="hover:text-foreground">
            Backtests
          </AuthLink>
          <AuthLink href="/simulations" className="hover:text-foreground">
            Simulations
          </AuthLink>
        </nav>
      </div>
    </footer>
  );
}

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      {/* useSearchParams needs a Suspense boundary, or the whole route goes client-side. */}
      <Suspense fallback={null}>
        <LoginFromRedirect />
      </Suspense>
      <Nav />
      <main className="flex-1">
        <Hero />
        <Pillars />
        <HowItWorks />
        <Features />
        <Prompts />
        <Safety />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
