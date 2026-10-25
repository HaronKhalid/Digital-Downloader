// Tiny shared state so modules never import each other in a cycle.
export const state = {
  activeJobId: null, // a download that is queued or running
  lastJobId: null, // the most recent job (used by Open file / Open folder)
  lastRequest: null, // payload of the last download, for "Try again"
};
