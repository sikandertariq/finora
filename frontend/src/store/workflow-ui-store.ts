import { create } from "zustand";

// Which workflow is currently open for review — ephemeral UI selection, the
// same shape as CLAUDE.md's own "tenant switcher" example. The workflow's
// actual data (status, extracted fields) is server state and lives in React
// Query, keyed off this id — never duplicated here.
interface WorkflowUiState {
  activeWorkflowId: number | null;
  setActiveWorkflowId: (id: number | null) => void;
}

export const useWorkflowUiStore = create<WorkflowUiState>((set) => ({
  activeWorkflowId: null,
  setActiveWorkflowId: (id) => set({ activeWorkflowId: id }),
}));
