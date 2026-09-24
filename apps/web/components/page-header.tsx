import { RiArrowLeftLine } from '@remixicon/react';
import Link from 'next/link';
import type { ComponentType, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/** Small bordered chip for a fact about the page's subject, e.g. "SOLUSDT" or "fees 10/10 bps". */
export function Chip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'bg-muted/40 text-muted-foreground inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs',
        className
      )}
    >
      {children}
    </span>
  );
}

/** Title block for detail pages: back link, title with badges, fact chips, and actions on the right. */
export function PageHeader({
  back,
  title,
  badges,
  chips,
  actions,
}: {
  back?: { href: string; label: string };
  title: ReactNode;
  badges?: ReactNode;
  chips?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      {back && (
        <Link
          href={back.href}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-xs"
        >
          <RiArrowLeftLine className="size-3.5" /> {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            {badges}
          </div>
          {chips && <div className="flex flex-wrap items-center gap-1.5">{chips}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

/** Card title with a tinted icon chip in front. */
export function SectionTitle({
  icon: Icon,
  children,
  tone = 'emerald',
}: {
  icon: ComponentType<{ className?: string }>;
  children: ReactNode;
  tone?: 'emerald' | 'cyan' | 'amber' | 'red' | 'violet';
}) {
  return (
    <span className="flex items-center gap-2.5">
      <span
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-lg',
          tone === 'emerald' && 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
          tone === 'cyan' && 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400',
          tone === 'amber' && 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
          tone === 'red' && 'bg-red-500/10 text-red-600 dark:text-red-400',
          tone === 'violet' && 'bg-violet-500/10 text-violet-600 dark:text-violet-400'
        )}
      >
        <Icon className="size-4" />
      </span>
      {children}
    </span>
  );
}
