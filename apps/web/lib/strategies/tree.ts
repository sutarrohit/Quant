import {
  BAR_DERIVED,
  MAX_DEPTH,
  OPERATORS_BY_INDICATOR,
  PERIODIC,
  SMA_OPERATORS,
  type ConditionNode,
  type StrategySpecInput,
} from '@quant/contracts/spec';

// UI-side editing of a condition tree. The rules come from contracts; this only
// decides how an edit keeps a node consistent with them.

export type Leaf = Extract<ConditionNode, { indicator: string }>;
export type ExitLeaf = Extract<ConditionNode, { type: string }>;
export type GroupKind = 'all' | 'any' | 'not';

export const isLeaf = (n: ConditionNode): n is Leaf => 'indicator' in n;
export const isExit = (n: ConditionNode): n is ExitLeaf => 'type' in n;
export const groupKind = (n: ConditionNode): GroupKind | null =>
  'all' in n ? 'all' : 'any' in n ? 'any' : 'not' in n ? 'not' : null;

export const childrenOf = (n: ConditionNode): ConditionNode[] =>
  'all' in n ? n.all : 'any' in n ? n.any : 'not' in n ? [n.not] : [];

export const INDICATOR_LABELS: Record<string, string> = {
  rsi: 'RSI',
  sma: 'SMA',
  ema: 'EMA',
  atr: 'ATR',
  close: 'Close',
  volume: 'Volume',
};

export const OPERATOR_LABELS: Record<string, string> = {
  crossesAbove: 'crosses above',
  crossesBelow: 'crosses below',
  greaterThan: 'is above',
  lessThan: 'is below',
  greaterThanSma: 'is above its SMA',
  lessThanSma: 'is below its SMA',
};

export const GROUP_LABELS: Record<GroupKind, string> = { all: 'All of', any: 'Any of', not: 'Not' };

export const newLeaf = (): Leaf => ({ indicator: 'rsi', period: 14, operator: 'crossesAbove', value: '30' });
export const newStop = (): ExitLeaf => ({ type: 'stopLossPercent', value: '2' });

/** Does this indicator/operator pair take a period of its own? */
export const needsPeriod = (indicator: string, operator: string) =>
  PERIODIC.has(indicator) || (indicator === 'volume' && SMA_OPERATORS.has(operator));

/** ...Sma operators already compare against an average, so they take no threshold. */
export const needsThreshold = (operator: string) => !SMA_OPERATORS.has(operator);

/**
 * Apply an edit to a leaf and drop whatever the new combination cannot take --
 * an operator the indicator does not support, a period close has no use for.
 * This is what makes most spec errors unreachable from the form.
 */
export function editLeaf(leaf: Leaf, patch: Partial<Leaf>): Leaf {
  const next = { ...leaf, ...patch } as Leaf;

  const allowed = OPERATORS_BY_INDICATOR[next.indicator] ?? [];
  if (!allowed.includes(next.operator)) next.operator = allowed[0] as Leaf['operator'];

  if (needsPeriod(next.indicator, next.operator)) next.period ??= 14;
  else delete next.period;

  if (!needsThreshold(next.operator)) {
    delete next.value;
    delete next.reference;
  } else if (next.value === undefined && next.reference === undefined) {
    next.value = '0';
  }

  if (next.reference) {
    const ref = { ...next.reference };
    if (BAR_DERIVED.has(ref.indicator)) delete ref.period;
    else ref.period ??= 50;
    next.reference = ref;
  }
  return next;
}

/** Switch between comparing to a number and to another series. */
export function setComparison(leaf: Leaf, to: 'value' | 'reference'): Leaf {
  const rest = { ...leaf };
  delete rest.value;
  delete rest.reference;
  return to === 'value' ? { ...rest, value: '0' } : { ...rest, reference: { indicator: 'sma', period: 50 } };
}

/** Change a group's kind. `not` takes exactly one child, so extra children are dropped. */
export function setGroupKind(node: ConditionNode, kind: GroupKind, fallback: () => ConditionNode): ConditionNode {
  const children = childrenOf(node);
  if (kind === 'not') return { not: children[0] ?? fallback() };
  return kind === 'all' ? { all: children } : { any: children };
}

/** Depth of the deepest node beneath (and including) this one. Leaves are 1. */
export function depthOf(node: ConditionNode): number {
  const kids = childrenOf(node);
  return groupKind(node) === null || kids.length === 0 ? 1 : 1 + Math.max(...kids.map(depthOf));
}

/** Can a group be added as a child of a node at `level` (root is 1)? It needs room for its own leaf. */
export const canAddGroup = (level: number) => level + 2 <= MAX_DEPTH;

/** `entry.all[0].period` (what the validator reports) -> `entry.all.0.period` (what the form uses). */
export const toFieldPath = (path: string) => path.replace(/\[(\d+)\]/g, '.$1');

/** What a brand-new strategy starts as: the gate example from the plan. */
export function starterSpec(strategyId: string): StrategySpecInput {
  return {
    strategyId,
    version: 1,
    market: { exchange: 'binance', marketType: 'spot', symbols: ['SOL/USDT'], timeframe: '15m' },
    entry: { all: [{ indicator: 'close', operator: 'crossesAbove', reference: { indicator: 'sma', period: 200 } }] },
    exit: { any: [newStop(), { type: 'takeProfitPercent', value: '4' }] },
    sizing: { type: 'riskPercent', riskPercent: '1' },
  };
}

/** A spec id from a display name: "SMA 200 cross!" -> "sma-200-cross". */
export const slugify = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 100) || 'strategy';
