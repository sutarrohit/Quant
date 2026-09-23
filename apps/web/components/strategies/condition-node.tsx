'use client';

import {
  ExitConditionSchema,
  IndicatorConditionSchema,
  OPERATORS_BY_INDICATOR,
  PERIODIC,
  type ConditionNode,
} from '@quant/contracts/spec';
import { RiAddLine, RiArrowDownSLine, RiArrowRightSLine, RiCloseLine, RiNodeTree } from '@remixicon/react';

import { Choice } from '@/components/strategies/choice';
import { ErrorList, useErrorMap, useErrorsAt } from '@/components/strategies/spec-errors';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  GROUP_LABELS,
  INDICATOR_LABELS,
  OPERATOR_LABELS,
  canAddGroup,
  childrenOf,
  editLeaf,
  groupKind,
  isExit,
  needsPeriod,
  needsThreshold,
  newLeaf,
  newStop,
  setComparison,
  setGroupKind,
  type ExitLeaf,
  type GroupKind,
  type Leaf,
} from '@/lib/strategies/tree';
import { useStrategyBuilderStore } from '@/stores/strategy-builder';

interface NodeProps {
  node: ConditionNode;
  path: string; // Form path, e.g. "entry.all.0".
  level: number; // Root is 1.
  allowExit: boolean; // Stops and targets only belong in the exit tree.
  atLeafLimit: boolean;
  storeKey: string; // Whose collapsed-state this is.
  onChange: (next: ConditionNode) => void;
  onRemove?: () => void; // Absent on the root.
}

const pick = (options: Record<string, string>, keys: readonly string[]) =>
  Object.fromEntries(keys.map((k) => [k, options[k] ?? k]));

/** Structural problems with one row, by field -- the part the form cannot make impossible. */
function leafIssues(node: ConditionNode, schema: typeof IndicatorConditionSchema | typeof ExitConditionSchema) {
  const parsed = schema.safeParse(node);
  const byField = new Map<string, string[]>();
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const key = issue.path.join('.');
      byField.set(key, [...(byField.get(key) ?? []), issue.message]);
    }
  }
  return (field: string) => byField.get(field) ?? [];
}

export function ConditionNodeEditor(props: NodeProps) {
  if (groupKind(props.node)) return <GroupEditor {...props} />;
  if (isExit(props.node)) return <ExitLeafEditor {...props} node={props.node} />;
  return <LeafEditor {...props} node={props.node as Leaf} />;
}

function GroupEditor({ node, path, level, allowExit, atLeafLimit, storeKey, onChange, onRemove }: NodeProps) {
  const kind = groupKind(node) as GroupKind;
  const children = childrenOf(node);
  const errors = useErrorsAt(path);
  const collapsed = useStrategyBuilderStore((s) => (s.collapsed[storeKey] ?? []).includes(path));
  const toggle = useStrategyBuilderStore((s) => s.toggleCollapsed);

  const replaceChild = (i: number, next: ConditionNode) =>
    onChange(
      kind === 'not' ? { not: next } : ({ [kind]: children.map((c, j) => (j === i ? next : c)) } as ConditionNode)
    );
  const removeChild = (i: number) => onChange({ [kind]: children.filter((_, j) => j !== i) } as ConditionNode);
  const add = (child: ConditionNode) => onChange({ [kind]: [...children, child] } as ConditionNode);
  const childPath = (i: number) => (kind === 'not' ? `${path}.not` : `${path}.${kind}.${i}`);

  return (
    <div
      className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3"
      data-invalid={errors.length > 0 || undefined}
    >
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={collapsed ? 'Expand group' : 'Collapse group'}
          onClick={() => toggle(storeKey, path)}
        >
          {collapsed ? <RiArrowRightSLine /> : <RiArrowDownSLine />}
        </Button>
        <Choice
          label="Group type"
          value={kind}
          options={GROUP_LABELS}
          onChange={(k) => onChange(setGroupKind(node, k as GroupKind, allowExit ? newStop : newLeaf))}
        />
        <span className="text-xs text-muted-foreground">
          {kind === 'not' ? 'the condition below' : `${children.length} condition${children.length === 1 ? '' : 's'}`}
        </span>
        {onRemove && (
          <Button variant="ghost" size="icon" className="ml-auto" aria-label="Remove group" onClick={onRemove}>
            <RiCloseLine />
          </Button>
        )}
      </div>
      <ErrorList messages={errors} />

      {!collapsed && (
        <div className="flex flex-col gap-2 border-l-2 pl-3">
          {children.map((child, i) => (
            <ConditionNodeEditor
              key={i}
              node={child}
              path={childPath(i)}
              level={level + 1}
              allowExit={allowExit}
              atLeafLimit={atLeafLimit}
              storeKey={storeKey}
              onChange={(next) => replaceChild(i, next)}
              onRemove={kind === 'not' ? undefined : () => removeChild(i)}
            />
          ))}

          {kind !== 'not' && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" disabled={atLeafLimit} onClick={() => add(newLeaf())}>
                <RiAddLine /> Condition
              </Button>
              {allowExit && (
                <Button variant="outline" size="sm" disabled={atLeafLimit} onClick={() => add(newStop())}>
                  <RiAddLine /> Stop / target
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                disabled={atLeafLimit || !canAddGroup(level)}
                title={canAddGroup(level) ? undefined : 'Groups can nest five levels deep'}
                onClick={() => add({ all: [newLeaf()] })}
              >
                <RiNodeTree /> Group
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LeafEditor({ node, path, onChange, onRemove }: NodeProps & { node: Leaf }) {
  const issues = leafIssues(node, IndicatorConditionSchema);
  const errorMap = useErrorMap();
  const here = errorMap.get(path) ?? [];
  const at = (field: string) => [...issues(field), ...(errorMap.get(`${path}.${field}`) ?? [])];
  const operators = pick(OPERATOR_LABELS, OPERATORS_BY_INDICATOR[node.indicator] ?? []);
  const comparing = node.reference ? 'reference' : 'value';

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-2">
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <Choice
            label="Indicator"
            value={node.indicator}
            options={INDICATOR_LABELS}
            onChange={(v) => onChange(editLeaf(node, { indicator: v as Leaf['indicator'] }))}
          />
          {needsPeriod(node.indicator, node.operator) && (
            <Input
              type="number"
              aria-label="Period"
              className="h-7 w-20"
              value={Number.isFinite(node.period) ? node.period : ''}
              aria-invalid={at('period').length > 0 || undefined}
              onChange={(e) => onChange({ ...node, period: e.target.valueAsNumber })}
            />
          )}
          <Choice
            label="Operator"
            value={node.operator}
            options={operators}
            onChange={(v) => onChange(editLeaf(node, { operator: v as Leaf['operator'] }))}
          />

          {needsThreshold(node.operator) && (
            <>
              <Choice
                label="Compare with"
                value={comparing}
                options={{ value: 'a number', reference: 'another series' }}
                onChange={(v) => onChange(setComparison(node, v as 'value' | 'reference'))}
              />
              {node.reference ? (
                <>
                  <Choice
                    label="Series"
                    value={node.reference.indicator}
                    options={INDICATOR_LABELS}
                    onChange={(v) => onChange(editLeaf(node, { reference: { indicator: v as Leaf['indicator'] } }))}
                  />
                  {PERIODIC.has(node.reference.indicator) && (
                    <Input
                      type="number"
                      aria-label="Series period"
                      className="h-7 w-20"
                      value={Number.isFinite(node.reference.period) ? node.reference.period : ''}
                      onChange={(e) =>
                        onChange({ ...node, reference: { ...node.reference!, period: e.target.valueAsNumber } })
                      }
                    />
                  )}
                </>
              ) : (
                <Input
                  inputMode="decimal"
                  aria-label="Value"
                  className="h-7 w-24"
                  value={node.value ?? ''}
                  aria-invalid={at('value').length > 0 || undefined}
                  onChange={(e) => onChange({ ...node, value: e.target.value })}
                />
              )}
            </>
          )}
        </div>
        {onRemove && (
          <Button variant="ghost" size="icon" aria-label="Remove condition" onClick={onRemove}>
            <RiCloseLine />
          </Button>
        )}
      </div>
      <ErrorList
        messages={[
          ...here,
          ...at('indicator'),
          ...at('operator'),
          ...at('period'),
          ...at('value'),
          ...at('reference'),
          ...at('reference.period'),
        ]}
      />
    </div>
  );
}

function ExitLeafEditor({ node, path, onChange, onRemove }: NodeProps & { node: ExitLeaf }) {
  const issues = leafIssues(node, ExitConditionSchema);
  const errors = [...useErrorsAt(path), ...issues('value')];

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <Choice
          label="Exit type"
          value={node.type}
          options={{ stopLossPercent: 'Stop loss', takeProfitPercent: 'Take profit' }}
          onChange={(v) => onChange({ ...node, type: v } as ExitLeaf)}
        />
        <span className="text-sm text-muted-foreground">at</span>
        <Input
          inputMode="decimal"
          aria-label="Percent"
          className="h-7 w-20"
          value={node.value}
          aria-invalid={errors.length > 0 || undefined}
          onChange={(e) => onChange({ ...node, value: e.target.value })}
        />
        <span className="text-sm text-muted-foreground">%</span>
        {onRemove && (
          <Button variant="ghost" size="icon" className="ml-auto" aria-label="Remove exit" onClick={onRemove}>
            <RiCloseLine />
          </Button>
        )}
      </div>
      <ErrorList messages={errors} />
    </div>
  );
}
