const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../lib/core.js");

test("selectPage uses the CID and duration of the requested part", () => {
  const view = {
    bvid: "BV1dRYP6oEtB", title: "课程", duration: 200,
    pages: [{ cid: 11, page: 1, part: "概览", duration: 80 },
      { cid: 22, page: 2, part: "实践", duration: 120 }]
  };
  assert.deepEqual(core.selectPage(view, 2), {
    bvid: "BV1dRYP6oEtB", cid: 22, page: 2, title: "课程", part: "实践", duration: 120
  });
  assert.throws(() => core.selectPage(view, 3), /分 P/);
});

test("subtitle parsing sorts rows and rejects invalid or out-of-range timestamps", () => {
  const rows = { body: [
    { from: 9.2, to: 11, content: "  第二  段 " },
    { from: 1, to: 2, content: "第一段" },
    { from: 12, to: 13, content: "越界" },
    { from: -1, to: 1, content: "负数" },
    { from: 3, to: 3, content: "零时长" }
  ] };
  assert.deepEqual(core.normalizeSegments(rows, 12), [
    { from: 1, to: 2, content: "第一段" },
    { from: 9.2, to: 11, content: "第二 段" }
  ]);
});

test("chunked transcript preserves time marks and sequence", () => {
  const rows = Array.from({ length: 10 }, (_, i) => ({
    from: i * 10, to: i * 10 + 5, content: `内容${i}`.repeat(30)
  }));
  const chunks = core.chunkSegments(rows, 500);
  assert.ok(chunks.length >= 2);
  assert.equal(chunks[0].start, 0);
  assert.equal(chunks.at(-1).end, 95);
  assert.match(chunks[0].text, /\[0:00\]/);
  assert.match(chunks.at(-1).text, /\[1:30\]/);
});

test("model JSON parsing and result validation keep only navigable chapters", () => {
  const parsed = core.parseModelJson("```json\n{\"summary\":\"总结\",\"chapters\":[{\"start\":10,\"title\":\"开始\"},{\"start\":11,\"title\":\"重复\"},{\"start\":200,\"title\":\"越界\"}]}\n```");
  assert.deepEqual(core.normalizeResult(parsed, 100), {
    summary: "总结", chapters: [{ start: 10, title: "开始", summary: "" }]
  });
  assert.throws(() => core.parseModelJson("no JSON"), /JSON/);
  assert.throws(() => core.normalizeResult({ summary: "", chapters: [] }, 100), /缺少/);
});
