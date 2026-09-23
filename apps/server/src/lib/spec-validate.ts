import {
  BAR_DERIVED,
  OPERATORS_BY_INDICATOR,
  PERIODIC,
  SMA_OPERATORS,
  type ConditionNode,
  type StrategySpec,
} from '../types/spec.js';
import type { SpecError, SpecErrorCode } from '../types/strategy.js';
import { isGroup, walk } from './spec-tree.js';

// The semantic rules, mirroring engine/dsl/validator.py. A spec can parse
// cleanly and still be unrunnable -- an operator that means nothing for its
// indicator, a risk-sized strategy with no stop to divide by.
//
// The engine validates again and is authoritative. This runs first so the
// builder can mark every bad field without a round trip, which is why the codes
// are identical: the UI renders either source the same way.
//
// Two rules are deliberately absent. INDICATOR_PERIOD_TOO_LARGE needs the
// backtest window and SYMBOL_NOT_IN_CATALOG needs the catalog, and neither is
// known when a strategy is merely being saved.

type Leaf = Extract<ConditionNode, { indicator: string }>;
type ExitLeaf = Extract<ConditionNode, { type: string }>;

const isLeaf = (n: ConditionNode): n is Leaf => 'indicator' in n;
const isExit = (n: ConditionNode): n is ExitLeaf => 'type' in n;

const err = (path: string, code: SpecErrorCode, message: string): SpecError => ({
  path,
  code,
  message,
});


function checkLeaf(leaf: Leaf, path: string): SpecError[] {
  const out: SpecError[] = [];
  const { indicator, operator, period, value, reference } = leaf;

  const allowed = OPERATORS_BY_INDICATOR[indicator] ?? [];
  if (!allowed.includes(operator)) {
    out.push(
      err(
        `${path}.operator`,
        'UNSUPPORTED_OPERATOR',
        `${indicator} supports ${allowed.join(', ')}`
      )
    );
  }

  // rsi/sma/ema/atr need a window; close and volume come off the bar and have
  // none -- except volume with a ...Sma operator, where it is the averaging window.
  if (PERIODIC.has(indicator) && period === undefined) {
    out.push(err(`${path}.period`, 'MISSING_PERIOD', `${indicator} needs a period`));
  }
  if (indicator === 'close' && period !== undefined) {
    out.push(err(`${path}.period`, 'INVALID_REFERENCE', 'close has no period'));
  }
  if (indicator === 'volume') {
    const wantsPeriod = SMA_OPERATORS.has(operator);
    if (wantsPeriod && period === undefined) {
      out.push(err(`${path}.period`, 'MISSING_PERIOD', `${operator} needs a period to average`));
    }
    if (!wantsPeriod && period !== undefined) {
      out.push(
        err(`${path}.period`, 'INVALID_REFERENCE', 'volume takes a period only with greaterThanSma or lessThanSma')
      );
    }
  }

  // Exactly one of value / reference.
  if (value === undefined && reference === undefined) {
    out.push(err(path, 'MISSING_THRESHOLD', 'needs either a value or a reference'));
  }
  if (value !== undefined && reference !== undefined) {
    out.push(err(path, 'AMBIGUOUS_COMPARISON', 'give a value or a reference, not both'));
  }
  // A ...Sma operator already compares against an average.
  if (reference !== undefined && SMA_OPERATORS.has(operator)) {
    out.push(err(`${path}.reference`, 'AMBIGUOUS_COMPARISON', `${operator} already averages`));
  }

  if (reference !== undefined) {
    const ref = reference;
    if (PERIODIC.has(ref.indicator) && ref.period === undefined) {
      out.push(err(`${path}.reference.period`, 'INVALID_REFERENCE', `${ref.indicator} needs a period`));
    }
    if (BAR_DERIVED.has(ref.indicator) && ref.period !== undefined) {
      out.push(err(`${path}.reference.period`, 'INVALID_REFERENCE', `${ref.indicator} has no period`));
    }
  }

  return out;
}

function checkTree(root: ConditionNode, name: 'entry' | 'exit'): SpecError[] {
  const out: SpecError[] = [];
  const seen = new Map<string, string>();

  for (const [path, node] of walk(root, name)) {
    // `all` of nothing is true, so an empty group fires on every bar.
    for (const key of ['all', 'any'] as const) {
      if (isGroup(node, key)) {
        const children = (node as Record<string, ConditionNode[]>)[key];
        if (children !== undefined && children.length === 0) {
          out.push(err(path, 'EMPTY_CONDITION_GROUP', `${key} needs at least one condition`));
        }
      }
    }

    if (isExit(node)) {
      if (name === 'entry') {
        out.push(
          err(path, 'EXIT_CONDITION_IN_ENTRY', 'there is no position yet to measure against')
        );
      }
      continue;
    }

    if (!isLeaf(node)) continue;

    out.push(...checkLeaf(node, path));

    // The identical condition stated twice in one tree is always a mistake.
    const key = JSON.stringify(node);
    const first = seen.get(key);
    if (first !== undefined) {
      out.push(err(path, 'DUPLICATE_CONDITION', `the same condition is already at ${first}`));
    } else {
      seen.set(key, path);
    }
  }

  return out;
}

/** Every semantic problem with a spec, in document order. */
export function validateSpec(spec: StrategySpec): SpecError[] {
  const out = [...checkTree(spec.entry, 'entry'), ...checkTree(spec.exit, 'exit')];

  // Size = (equity x riskPercent) / stop distance, so riskPercent sizing has
  // nothing to divide by without a stop.
  if (spec.sizing.type === 'riskPercent') {
    const hasStop = [...walk(spec.exit, 'exit')].some(
      ([, n]) => isExit(n) && n.type === 'stopLossPercent'
    );
    if (!hasStop) {
      out.push(err('exit', 'MISSING_STOP_LOSS', 'riskPercent sizing needs a stopLossPercent'));
    }
  }

  return out;
}
