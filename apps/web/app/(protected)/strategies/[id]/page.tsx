'use client';

import { MarketSchema, type StrategySpec, type StrategySpecInput } from '@quant/contracts/spec';
import type { SpecError } from '@quant/contracts/strategy';
import { RiCodeLine, RiPlayLine, RiPulseLine } from '@remixicon/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { Pill } from '@/components/metric-card';
import { Chip, PageHeader } from '@/components/page-header';
import { FormFooter } from '@/components/strategies/form-footer';
import { LatestBacktest } from '@/components/strategies/latest-backtest';
import { StrategyForm } from '@/components/strategies/strategy-form';
import { VersionHistory } from '@/components/strategies/version-history';
import { Button, buttonVariants } from '@/components/ui/button';
import { ErrorState } from '@/components/page-states';
import { Skeleton } from '@/components/ui/skeleton';
import { createVersionMutationOptions, strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { timeAgo } from '@/lib/format';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';
import { ApiError } from '@/utils/api-error';
import { toastError } from '@/utils/toast-error';

export default function StrategyPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const { data, isPending, error, refetch } = useQuery(strategyQueryOptions(id));
  const save = useMutation(createVersionMutationOptions(client, id));
  const [serverErrors, setServerErrors] = useState<SpecError[]>([]);

  const draft = useStrategyBuilderStore((s) => s.drafts[id]);
  const pinned = useStrategyBuilderStore((s) => s.selectedVersion[id]);
  const previewOpen = useStrategyBuilderStore((s) => s.previewOpen);
  const setPreviewOpen = useStrategyBuilderStore((s) => s.setPreviewOpen);
  const discardDraft = useStrategyBuilderStore((s) => s.discardDraft);
  const selectVersion = useStrategyBuilderStore((s) => s.selectVersion);

  if (isPending) {
    return (
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-44 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <ErrorState
        error={error}
        title="Could not load this strategy"
        onRetry={() => void refetch()}
        back={{ href: '/strategies', label: 'Back to strategies' }}
        notFound={{
          code: 'STRATEGY_NOT_FOUND',
          title: 'Strategy not found',
          description: 'It may have been archived.',
        }}
      />
    );
  }

  const head = data.versions[0];
  const current = data.versions.find((v) => v.version === (pinned ?? head?.version)) ?? head;
  if (!current) return null; // A strategy is created with version 1, so this is unreachable.
  const market = MarketSchema.safeParse((current.spec as { market?: unknown } | null)?.market).data;

  const onSubmit = async (spec: StrategySpec) => {
    try {
      const saved = await save.mutateAsync({ spec });
      discardDraft(id);
      toast.success(saved.version === head?.version ? 'No changes to save' : `Saved as v${saved.version}`);
    } catch (e) {
      if (e instanceof ApiError) setServerErrors(e.specErrors);
      toastError(e, 'Could not save');
    }
  };

  const openVersion = (version: number) => {
    discardDraft(id);
    selectVersion(id, version);
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <PageHeader
        back={{ href: '/strategies', label: 'Strategies' }}
        title={data.name}
        badges={<Pill>V{current.version}</Pill>}
        chips={
          <>
            {market && (
              <Chip className="text-foreground font-medium">
                {market.symbols.join(', ')} · {market.timeframe}
              </Chip>
            )}
            <Chip>Binance · Spot</Chip>
            <Chip>Updated {timeAgo(data.updatedAt)}</Chip>
            {current.version !== head?.version && (
              <Chip className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400">
                Viewing v{current.version} of {head?.version}
              </Chip>
            )}
            {draft && (
              <Chip className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400">
                Unsaved changes
              </Chip>
            )}
          </>
        }
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => setPreviewOpen(!previewOpen)}>
              <RiCodeLine /> {previewOpen ? 'Hide JSON' : 'Show JSON'}
            </Button>
            <Link
              href={`/strategies/${id}/backtest?version=${current.id}`}
              className={buttonVariants({ size: 'sm' })}
              title={draft ? 'Runs the saved version, without your unsaved edits' : undefined}
            >
              <RiPlayLine /> Run backtest
            </Link>
            <Link
              href={`/strategies/${id}/simulate?version=${current.id}`}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
            >
              <RiPulseLine /> Paper trade
            </Link>
          </>
        }
      />

      <VersionHistory versions={data.versions} current={current.version} hasDraft={!!draft} onSelect={openVersion} />

      <LatestBacktest strategyId={id} versionId={current.id} version={current.version} />

      <StrategyForm
        key={`${id}:${current.version}`}
        defaultValues={draft ?? (current.spec as StrategySpecInput)}
        storeKey={id}
        serverErrors={serverErrors}
        onEdit={() => setServerErrors((prev) => (prev.length ? [] : prev))}
        onSubmit={onSubmit}
        footer={({ runnable, submitting }) => (
          <FormFooter runnable={runnable} submitting={submitting} label="Save as new version" />
        )}
      />
    </div>
  );
}
