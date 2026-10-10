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

test("subtitle export preserves millisecond SRT cues and readable TXT timestamps", () => {
  const segments = [
    { from: 0.125, to: 2.5, content: "第一行" },
    { from: 3661.007, to: 3662.25, content: "第二行" }
  ];
  assert.equal(core.segmentsToSrt(segments),
    "1\r\n00:00:00,125 --> 00:00:02,500\r\n第一行\r\n\r\n" +
    "2\r\n01:01:01,007 --> 01:01:02,250\r\n第二行\r\n");
  assert.equal(core.segmentsToText(segments), "[0:00] 第一行\r\n[1:01:01] 第二行\r\n");
});

test("active subtitle selection respects starts, ends, and silent gaps", () => {
  const segments = [
    { from: 0, to: 4 },
    { from: 5, to: 10 },
    { from: 12, to: 16 }
  ];
  assert.equal(core.activeSegmentIndex(segments, 0), 0);
  assert.equal(core.activeSegmentIndex(segments, 3.9), 0);
  assert.equal(core.activeSegmentIndex(segments, 4), -1);
  assert.equal(core.activeSegmentIndex(segments, 7), 1);
  assert.equal(core.activeSegmentIndex(segments, 11), -1);
  assert.equal(core.activeSegmentIndex(segments, 16), -1);
  assert.equal(core.activeSegmentIndex([], 2), -1);
  assert.equal(core.activeSegmentIndex([
    { from: 0, to: 10 }, { from: 4, to: 5 }
  ], 6), 0);
});

test("subtitle filename removes Windows-unsafe characters and marks the video part", () => {
  assert.equal(core.subtitleFilename("标题: 第一/二集? ", "BV1dRYP6oEtB", 2, "srt"),
    "标题_ 第一_二集__BV1dRYP6oEtB_P2.srt");
  assert.equal(core.subtitleFilename("  ", "BV1dRYP6oEtB", 1, "txt"),
    "视频字幕_BV1dRYP6oEtB.txt");
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

test("rejects subtitles and chapters that cover only the opening of a long video", () => {
  const duration = 1744;
  assert.equal(core.transcriptCoverage([
    { from: 0, to: 30 }, { from: 70, to: 80 }
  ], duration).complete, false);
  assert.equal(core.chapterCoverage({ chapters: [
    { start: 0 }, { start: 10 }, { start: 30 }, { start: 50 }, { start: 80 }
  ] }, duration).complete, false);
  assert.equal(core.transcriptCoverage([
    { from: 0, to: 30 }, { from: 1700, to: 1720 }
  ], duration).complete, true);
  assert.equal(core.chapterCoverage({ chapters: [
    { start: 0 }, { start: 600 }, { start: 1200 }
  ] }, duration).complete, true);
});

test("model JSON parsing and result validation keep only navigable chapters", () => {
  const parsed = core.parseModelJson("```json\n{\"summary\":\"总结\",\"chapters\":[{\"start\":10,\"title\":\"开始\"},{\"start\":11,\"title\":\"重复\"},{\"start\":200,\"title\":\"越界\"}]}\n```");
  assert.deepEqual(core.normalizeResult(parsed, 100), {
    summary: "总结", chapters: [{ start: 10, title: "开始", summary: "" }]
  });
  assert.throws(() => core.parseModelJson("no JSON"), /JSON/);
  assert.throws(() => core.normalizeResult({ summary: "", chapters: [] }, 100), /缺少/);
});
