'use client';

import type { StrategySpec } from '@quant/contracts/spec';
import type { SpecError } from '@quant/contracts/strategy';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { FormFooter } from '@/components/strategies/form-footer';
import { StrategyForm } from '@/components/strategies/strategy-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { createStrategyMutationOptions } from '@/lib/api/strategies/strategy-queries';
import { slugify, starterSpec } from '@/lib/strategies/tree';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';
import { ApiError } from '@/utils/api-error';
import { toastError } from '@/utils/toast-error';

const NEW = 'new'; // Store key for the not-yet-created strategy's draft.

export default function NewStrategyPage() {
  const router = useRouter();
  const client = useQueryClient();
  const draft = useStrategyBuilderStore((s) => s.drafts[NEW]);
  const discardDraft = useStrategyBuilderStore((s) => s.discardDraft);
  const create = useMutation(createStrategyMutationOptions(client));
  const [name, setName] = useState('');
  const [serverErrors, setServerErrors] = useState<SpecError[]>([]);

  const onSubmit = async (spec: StrategySpec) => {
    try {
      const created = await create.mutateAsync({ name: name.trim(), spec: { ...spec, strategyId: slugify(name) } });
      discardDraft(NEW);
      toast.success(`Created “${created.name}”`);
      router.replace(`/strategies/${created.id}`);
    } catch (error) {
      if (error instanceof ApiError) setServerErrors(error.specErrors);
      toastError(error, 'Could not create the strategy');
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">New strategy</h1>
        <p className="text-sm text-muted-foreground">Starts from a 200-period SMA crossover. Change anything.</p>
      </div>
      <StrategyForm
        defaultValues={draft ?? starterSpec('strategy')}
        storeKey={NEW}
        serverErrors={serverErrors}
        onEdit={() => setServerErrors((prev) => (prev.length ? [] : prev))}
        onSubmit={onSubmit}
        header={
          <div className="grid max-w-md gap-2">
            <Label htmlFor="strategy-name">Name</Label>
            <Input
              id="strategy-name"
              value={name}
              maxLength={200}
              placeholder="e.g. SMA 200 crossover"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
        }
        footer={({ runnable, submitting }) => (
          <FormFooter
            runnable={runnable}
            submitting={submitting}
            blockedReason={name.trim() ? undefined : 'Give it a name to save.'}
            label="Create strategy"
          />
        )}
      />
    </div>
  );
}
