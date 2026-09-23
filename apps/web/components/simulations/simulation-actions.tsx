'use client';

import type { Simulation } from '@quant/contracts/simulation';
import type { StrategyVersion } from '@quant/contracts/strategy';
import { RiAlarmWarningLine, RiPlayLine, RiStopLine } from '@remixicon/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { toast } from 'sonner';

import { Choice } from '@/components/strategies/choice';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  killMutationOptions,
  startSimulationMutationOptions,
  stopSimulationMutationOptions,
} from '@/lib/api/simulations/simulation-queries';

type Confirm = 'stop' | 'kill' | null;

/** Start / switch version, Stop, and Kill. Stop and kill are different verbs and look it. */
export function SimulationActions({ sim, versions }: { sim: Simulation; versions: StrategyVersion[] }) {
  const client = useQueryClient();
  const onError = (e: Error) => toast.error(e.message);
  const start = useMutation({ ...startSimulationMutationOptions(client, sim.id), onError });
  const stop = useMutation({ ...stopSimulationMutationOptions(client, sim.id), onError });
  const kill = useMutation({ ...killMutationOptions(client, sim.id), onError });
  const [versionId, setVersionId] = useState(sim.versionId);
  const [confirm, setConfirm] = useState<Confirm>(null);

  const running = sim.live?.desired.status === 'RUNNING';
  const halted = sim.live?.observed?.status === 'HALTED';
  const engaged = sim.live?.killSwitch === 'ENGAGED';
  const switching = versionId !== sim.versionId;
  const target = versions.find((v) => v.id === versionId);

  const startLabel = switching
    ? `Switch to v${target?.version}`
    : halted
      ? 'Restate and restart'
      : running
        ? 'Restart'
        : 'Start';

  const options = Object.fromEntries(
    versions.map((v, i) => [
      v.id,
      `v${v.version}${i === 0 ? ' (latest)' : ''}${v.id === sim.versionId ? ' · running' : ''}`,
    ])
  );

  const onStart = () =>
    start.mutate(switching ? { versionId } : {}, {
      onSuccess: () => toast.success(switching ? `Moving to v${target?.version}` : 'Asked to start'),
    });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        {versions.length > 1 && (
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Version</span>
            <Choice label="Version" value={versionId} options={options} onChange={setVersionId} />
          </div>
        )}
        <Button onClick={onStart} disabled={start.isPending}>
          <RiPlayLine /> {start.isPending ? 'Asking…' : startLabel}
        </Button>
        <Button variant="outline" onClick={() => setConfirm('stop')} disabled={!running || stop.isPending}>
          <RiStopLine /> Stop
        </Button>
        {engaged ? (
          <Button variant="outline" onClick={() => kill.mutate(false)} disabled={kill.isPending}>
            Release kill switch
          </Button>
        ) : (
          <Button variant="destructive" onClick={() => setConfirm('kill')} disabled={kill.isPending}>
            <RiAlarmWarningLine /> Kill
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        <strong>Stop</strong> shuts the node down in an orderly way. <strong>Kill</strong> blocks every order at once
        while it stays up. Neither closes an open position.
      </p>

      <AlertDialog open={confirm !== null} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          {confirm === 'stop' ? (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>Stop “{sim.name}”?</AlertDialogTitle>
                <AlertDialogDescription>
                  The node shuts down and places no more orders, exits included. It does <strong>not</strong> close an
                  open position: anything open stays open, with nothing managing its stop, until you start it again.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={() => stop.mutate(undefined, { onSuccess: () => setConfirm(null) })}>
                  Stop signalling
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          ) : (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>Engage the kill switch?</AlertDialogTitle>
                <AlertDialogDescription>
                  Every order is blocked immediately, <strong>exits included</strong>: its stop loss and take profit
                  stop acting too. It does not close anything, so an open position becomes yours to deal with. Use it
                  when you no longer trust what the strategy would send. Release it to let it trade again.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  onClick={() => kill.mutate(true, { onSuccess: () => setConfirm(null) })}
                >
                  Engage kill switch
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          )}
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
