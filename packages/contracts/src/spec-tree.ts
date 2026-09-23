import type { ConditionNode } from './spec.js';

// Walking a condition tree. Shared by the schema, which bounds its size, and
// the semantic validator, which inspects every node.

type Group = 'all' | 'any' | 'not';

export const isGroup = (node: ConditionNode, key: Group): boolean => key in node;

/** The children of a group node, or null for a leaf. */
export function childrenOf(node: ConditionNode): ConditionNode[] | null {
  if (isGroup(node, 'all')) return (node as { all: ConditionNode[] }).all;
  if (isGroup(node, 'any')) return (node as { any: ConditionNode[] }).any;
  if (isGroup(node, 'not')) return [(node as { not: ConditionNode }).not];
  return null;
}

/** Every node in the tree, with the JSON path that points at it. */
export function* walk(node: ConditionNode, path: string): Generator<[string, ConditionNode]> {
  yield [path, node];

  if (isGroup(node, 'not')) {
    yield* walk((node as { not: ConditionNode }).not, `${path}.not`);
    return;
  }
  for (const key of ['all', 'any'] as const) {
    if (!isGroup(node, key)) continue;
    const children = (node as Record<string, ConditionNode[]>)[key] ?? [];
    for (const [i, child] of children.entries()) yield* walk(child, `${path}.${key}[${i}]`);
  }
}

/** Depth and leaf count, which together bound what the interpreter must evaluate. */
export function shape(node: ConditionNode): { depth: number; leaves: number } {
  const children = childrenOf(node);
  if (children === null) return { depth: 1, leaves: 1 };
  if (children.length === 0) return { depth: 1, leaves: 0 };

  const parts = children.map(shape);
  return {
    depth: 1 + Math.max(...parts.map((p) => p.depth)),
    leaves: parts.reduce((sum, p) => sum + p.leaves, 0),
  };
}
