'use client';

import type { Simulation } from '@quant/contracts/simulation';
import { RiLoader4Line } from '@remixicon/react';

import { Badge } from '@/components/ui/badge';

type Variant = 'default' | 'secondary' | 'destructive' | 'outline';

export interface SimState {
  label: string;
  variant: Variant;
  busy?: boolean; // Spins: something is changing right now.
  hint: string; // One plain sentence on what it means and what happens next.
}

/** The one reading of a simulation's state, most urgent first. List and detail both use it. */
export function simState(sim: Simulation): SimState {
  const { live, liveError } = sim;

  if (!live) {
    return liveError?.code === 'ACCOUNT_NOT_FOUND'
      ? { label: 'Not started', variant: 'outline', hint: 'The engine has no record of it yet. Start it to begin.' }
      : {
          label: 'Engine unreachable',
          variant: 'destructive',
          hint: liveError?.message ?? 'Could not read the engine.',
        };
  }

  const { desired, observed } = live;

  if (observed?.status === 'HALTED') {
    return {
      label: 'Halted: needs an operator',
      variant: 'destructive',
      hint: 'The node disagreed with the exchange on startup and will not retry by itself. Check the account, then Start to restate it.',
    };
  }
  if (live.heartbeatStale) {
    return {
      label: 'Not heartbeating',
      variant: 'destructive',
      hint: 'No heartbeat for over 90 seconds. The supervisor presumes the node dead and restarts it.',
    };
  }
  if (live.converging) {
    return desired.status === 'STOPPED'
      ? { label: 'Stopping', variant: 'secondary', busy: true, hint: 'Asked to stop; the node has not confirmed yet.' }
      : {
          label: observed ? 'Converging' : 'Waiting for the supervisor',
          variant: 'secondary',
          busy: true,
          hint: observed
            ? `Running revision ${observed.revision}; revision ${desired.revision} was asked for. It restarts onto the new one.`
            : 'Recorded; the supervisor picks it up within a few seconds.',
        };
  }

  switch (observed?.status) {
    case 'RUNNING':
      return { label: 'Running', variant: 'default', hint: 'Trading on paper, at the revision asked for.' };
    case 'STARTING':
      return { label: 'Starting', variant: 'secondary', busy: true, hint: 'The node is starting up.' };
    case 'RECONCILING':
      return {
        label: 'Reconciling',
        variant: 'secondary',
        busy: true,
        hint: 'Checking its state against the exchange before it trades.',
      };
    case 'FAILED':
      return {
        label: 'Failed',
        variant: 'destructive',
        hint: 'The node crashed. The supervisor restarts it by itself.',
      };
    case 'STOPPED':
      return { label: 'Stopped', variant: 'outline', hint: 'Shut down. Any open position was left open, unmanaged.' };
    default:
      return { label: 'Unknown', variant: 'outline', hint: 'The engine has not reported on it yet.' };
  }
}

export function StateBadge({ sim }: { sim: Simulation }) {
  const state = simState(sim);
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge variant={state.variant} title={state.hint}>
        {state.busy && <RiLoader4Line className="animate-spin" />}
        {state.label}
      </Badge>
      {sim.live?.killSwitch === 'ENGAGED' && <Badge variant="destructive">Kill switch on</Badge>}
    </span>
  );
}
