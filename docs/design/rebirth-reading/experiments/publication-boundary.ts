import { upstreamSelected, type GateArticle } from "./vendor/aihot/selected-gate.ts";

/** A candidate already passed material, readable-copy and source eligibility checks. */
export interface Candidate {
  id: string;
  selectionCandidate: boolean;
  visibility: "public" | "withdrawn";
  article: GateArticle;
  editorialOverride?: boolean;
  independent: {
    readable: boolean;
    duplicateCheck: "distinct" | "duplicate" | "pending";
  };
  relations: ReadonlyArray<{
    eventId: string;
    status: "confirmed" | "pending" | "revoked";
  }>;
}

/** Experiment-only policy boundary. No DB, queue, event writer or upstream application is loaded. */
export function projectCandidate(candidate: Candidate) {
  const independentlyReady = candidate.independent.readable
    && candidate.independent.duplicateCheck === "distinct";
  const selected = candidate.visibility === "public" && candidate.selectionCandidate
    && (independentlyReady || upstreamSelected(candidate.selectionCandidate, candidate.article,
      { selected: candidate.editorialOverride }));
  return {
    id: candidate.id,
    selected,
    eventIds: candidate.visibility === "public"
      ? [...new Set(candidate.relations.filter((relation) => relation.status === "confirmed")
        .map((relation) => relation.eventId))]
      : [],
  };
}
