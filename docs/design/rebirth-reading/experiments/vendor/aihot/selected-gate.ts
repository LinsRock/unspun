// Extracted from publication/publish.ts at AIHOT cd424b0 (MIT; see LICENSE).
// Only the selected predicate is extracted, not publication eligibility or persistence.
export interface GateArticle {
  grouping_status: "pending" | "complete" | "failed";
  selection_adds_value: boolean | null;
}

export function upstreamSelected(
  selectionCandidate: boolean,
  article: GateArticle,
  f: { selected?: boolean } = {},
): boolean {
  const selected = selectionCandidate && article.grouping_status === "complete"
    && (f.selected === true || article.selection_adds_value !== false);
  return selected;
}
