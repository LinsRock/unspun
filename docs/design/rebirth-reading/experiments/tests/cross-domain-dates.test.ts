import assert from "node:assert/strict";
import { test } from "node:test";
import {
  articleUtcOffset, readPublicationDate, readRelativeDate,
} from "../vendor/aihot/dates.ts";

// Constructed date-element fixtures, not captured source pages or verified publication claims.
test("Chinese culture, transport and research date elements preserve distinct precision", () => {
  const fixtures = [
    { title: "博物馆展览考据", text: "2026年11月4日", claim: "2026-11-04", at: "2026-11-03T16:00:00.000Z" },
    { title: "城市轨道开通公告", text: "2026年11月4日 00:00", claim: "2026-11-03T16:00:00.000Z", at: "2026-11-03T16:00:00.000Z" },
    { title: "材料科学论文解读", text: "2026-11-04T09:20:00+09:00", claim: "2026-11-04T00:20:00.000Z", at: "2026-11-04T00:20:00.000Z" },
  ];
  for (const fixture of fixtures) {
    const result = readPublicationDate(fixture.text);
    assert.equal(result.publicationTime, fixture.claim, fixture.title);
    assert.equal(result.publishedAt?.toISOString(), fixture.at, fixture.title);
  }
});

test("a knowledge essay with no date stays unknown, including unsupported Chinese numerals", () => {
  for (const text of [undefined, null, "", "发布日期不详", "二〇二六年十一月四日"]) {
    assert.deepEqual(readPublicationDate(text), { publishedAt: null, publicationTime: null });
  }
});

test("a Chinese byline near midnight preserves the observed source day across hosts", () => {
  const observedAt = new Date("2026-11-03T16:10:00Z");
  assert.deepEqual(readRelativeDate("城市研究者·昨天 23:50", observedAt), {
    publishedAt: new Date("2026-11-03T15:50:00Z"),
    publicationTime: "2026-11-03T15:50:00.000Z",
  });
  assert.deepEqual(readRelativeDate("社区观察·2天前", observedAt), {
    publishedAt: new Date("2026-11-01T16:00:00Z"), publicationTime: "2026-11-02",
  });
  assert.deepEqual(readRelativeDate("报道称昨天 23:50 开始试运行", observedAt), {
    publishedAt: null, publicationTime: null,
  });
});

test("global source configuration overrides the Chinese default without changing calendar precision", () => {
  const offset = articleUtcOffset({ publishedAtUtcOffset: "+08:00", detail: { publishedAtUtcOffset: "-05:00" } });
  assert.deepEqual(readPublicationDate("November 4, 2026", offset), {
    publishedAt: new Date("2026-11-04T05:00:00Z"), publicationTime: "2026-11-04",
  });
  assert.equal(articleUtcOffset({ publishedAtUtcOffset: "+00:00" }), "+00:00");
  assert.equal(articleUtcOffset({}), undefined);
});

test("date utility is permissive: choosing the publication element remains the caller's job", () => {
  // Characterization of a limitation: an event date or update label is not a publication claim.
  assert.equal(readPublicationDate("讲座将于2026年11月5日举行").publicationTime, "2026-11-05");
  assert.equal(readPublicationDate("更新于2026年11月4日").publicationTime, "2026-11-04");
});
