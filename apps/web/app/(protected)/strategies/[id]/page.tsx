'use client';

import type { StrategySpec, StrategySpecInput } from '@quant/contracts/spec';
import type { SpecError } from '@quant/contracts/strategy';
import { RiCodeLine, RiPlayLine } from '@remixicon/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { FormFooter } from '@/components/strategies/form-footer';
import { StrategyForm } from '@/components/strategies/strategy-form';
import { VersionHistory } from '@/components/strategies/version-history';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { createVersionMutationOptions, strategyQueryOptions } from '@/lib/api/strategies/strategy-queries';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';
import { ApiError } from '@/utils/api-error';

export default function StrategyPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const { data, isPending, error } = useQuery(strategyQueryOptions(id));
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
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error || !data) {
    const missing = error instanceof ApiError && error.code === 'STRATEGY_NOT_FOUND';
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">{missing ? 'Strategy not found' : 'Could not load this strategy'}</p>
        <p className="text-sm text-muted-foreground">{missing ? 'It may have been archived.' : error?.message}</p>
        <Link href="/strategies" className="text-sm underline underline-offset-2">
          Back to strategies
        </Link>
      </div>
    );
  }

  const head = data.versions[0];
  const current = data.versions.find((v) => v.version === (pinned ?? head?.version)) ?? head;
  if (!current) return null; // A strategy is created with version 1, so this is unreachable.

  const onSubmit = async (spec: StrategySpec) => {
    try {
      const saved = await save.mutateAsync({ spec });
      discardDraft(id);
      toast.success(saved.version === head?.version ? 'No changes to save' : `Saved as v${saved.version}`);
    } catch (e) {
      if (e instanceof ApiError) setServerErrors(e.specErrors);
      toast.error(e instanceof Error ? e.message : 'Could not save');
    }
  };

  const openVersion = (version: number) => {
    discardDraft(id);
    selectVersion(id, version);
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{data.name}</h1>
          <p className="text-sm text-muted-foreground">
            {current.version === head?.version
              ? `Latest is v${current.version}`
              : `Viewing v${current.version} of ${head?.version}`}
            {draft && ' · unsaved changes'}
          </p>
        </div>
        <div className="flex gap-2">
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
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_14rem]">
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
        <div className="order-first xl:order-none">
          <VersionHistory
            versions={data.versions}
            current={current.version}
            hasDraft={!!draft}
            onSelect={openVersion}
          />
        </div>
      </div>
    </div>
  );
}
