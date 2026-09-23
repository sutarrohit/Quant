import type { StrategySpecInput } from '@quant/contracts/spec';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

// Client state for the strategy builder. Server data (strategies, versions) is
// TanStack Query's; the live form values are react-hook-form's. This holds only
// what outlives the form.

type ById<T> = Record<string, T>;

interface StrategyBuilderState {
  drafts: ById<StrategySpecInput>; // Unsaved edits, so leaving the page does not lose them.
  selectedVersion: ById<number>; // Which version the builder is showing.
  collapsed: ById<string[]>; // Condition paths folded shut, e.g. "entry.all[1]".
  previewOpen: boolean; // The JSON preview pane.

  saveDraft: (strategyId: string, spec: StrategySpecInput) => void;
  discardDraft: (strategyId: string) => void;
  selectVersion: (strategyId: string, version: number) => void;
  toggleCollapsed: (strategyId: string, path: string) => void;
  setPreviewOpen: (open: boolean) => void;
}

const without = <T>(map: ById<T>, key: string): ById<T> =>
  Object.fromEntries(Object.entries(map).filter(([k]) => k !== key));

export const useStrategyBuilderStore = create<StrategyBuilderState>()(
  persist(
    (set) => ({
      drafts: {},
      selectedVersion: {},
      collapsed: {},
      previewOpen: true,

      saveDraft: (id, spec) => set((s) => ({ drafts: { ...s.drafts, [id]: spec } })),

      // Also clears the version pin: after a save, the builder should show the new head.
      discardDraft: (id) =>
        set((s) => ({ drafts: without(s.drafts, id), selectedVersion: without(s.selectedVersion, id) })),

      selectVersion: (id, version) => set((s) => ({ selectedVersion: { ...s.selectedVersion, [id]: version } })),

      toggleCollapsed: (id, path) =>
        set((s) => {
          const current = s.collapsed[id] ?? [];
          const next = current.includes(path) ? current.filter((p) => p !== path) : [...current, path];
          return { collapsed: { ...s.collapsed, [id]: next } };
        }),

      setPreviewOpen: (open) => set({ previewOpen: open }),
    }),
    {
      name: 'strategy-builder',
      // Per tab: a draft should not reappear days later in a different window.
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ drafts: s.drafts, collapsed: s.collapsed, previewOpen: s.previewOpen }),
    }
  )
);
