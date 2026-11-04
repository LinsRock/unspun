import assert from "node:assert/strict";
import { test } from "node:test";
import { projectCandidate, type Candidate } from "../publication-boundary.ts";
import { upstreamSelected } from "../vendor/aihot/selected-gate.ts";

const essay = (): Candidate => ({
  id: "culture-essay",
  selectionCandidate: true,
  visibility: "public",
  article: { grouping_status: "pending", selection_adds_value: null },
  independent: { readable: true, duplicateCheck: "distinct" },
  relations: [{ eventId: "museum-opening", status: "pending" }],
});

test("a qualified independent essay is selected while grouping and event evidence stay pending", () => {
  const candidate = essay();
  assert.equal(upstreamSelected(candidate.selectionCandidate, candidate.article), false);
  assert.deepEqual(projectCandidate(candidate), { id: "culture-essay", selected: true, eventIds: [] });
  assert.equal(candidate.article.grouping_status, "pending");
});

test("independent admission still needs material eligibility, readability and a completed duplicate check", () => {
  for (const candidate of [
    { ...essay(), selectionCandidate: false },
    { ...essay(), independent: { readable: false, duplicateCheck: "distinct" as const } },
    { ...essay(), independent: { readable: true, duplicateCheck: "duplicate" as const } },
    { ...essay(), independent: { readable: true, duplicateCheck: "pending" as const } },
  ]) assert.equal(projectCandidate(candidate).selected, false);
});

test("withdrawal blocks reading and evidence even when the independent and upstream gates pass", () => {
  assert.deepEqual(projectCandidate({ ...essay(), visibility: "withdrawn",
    article: { grouping_status: "complete", selection_adds_value: true },
    relations: [{ eventId: "museum-opening", status: "confirmed" }],
  }), { id: "culture-essay", selected: false, eventIds: [] });
});

test("confirming two links and revoking one preserves article identity and its other evidence", () => {
  const candidate = essay();
  const confirmed: Candidate = { ...candidate,
    article: { grouping_status: "complete", selection_adds_value: true },
    relations: [
      { eventId: "museum-opening", status: "confirmed" },
      { eventId: "archive-discovery", status: "confirmed" },
    ],
  };
  assert.deepEqual(projectCandidate(confirmed), {
    id: candidate.id, selected: true, eventIds: ["museum-opening", "archive-discovery"],
  });
  assert.deepEqual(projectCandidate({ ...confirmed, relations: [
    { eventId: "museum-opening", status: "revoked" },
    { eventId: "archive-discovery", status: "confirmed" },
  ] }), { id: candidate.id, selected: true, eventIds: ["archive-discovery"] });
});

test("ordinary report admission keeps the extracted upstream predicate", () => {
  const ordinary = { ...essay(), independent: { readable: false, duplicateCheck: "pending" as const } };
  assert.equal(projectCandidate(ordinary).selected, false);
  assert.equal(projectCandidate({ ...ordinary,
    article: { grouping_status: "complete", selection_adds_value: true },
  }).selected, true);
  assert.equal(projectCandidate({ ...ordinary,
    article: { grouping_status: "complete", selection_adds_value: false },
  }).selected, false);
});
