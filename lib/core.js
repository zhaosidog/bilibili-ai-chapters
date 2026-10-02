(function (root) {
  "use strict";

  function formatTime(value) {
    const seconds = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const rest = seconds % 60;
    return hours
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`
      : `${minutes}:${String(rest).padStart(2, "0")}`;
  }

  function selectPage(view, requestedPage) {
    const pages = Array.isArray(view?.pages) && view.pages.length
      ? view.pages
      : [{ cid: view?.cid, page: 1, part: view?.title, duration: view?.duration }];
    const index = Math.max(1, Math.floor(Number(requestedPage) || 1)) - 1;
    if (index >= pages.length || !Number.isFinite(Number(pages[index]?.cid))) {
      throw new Error("无法找到当前视频分 P 的信息。");
    }
    return {
      bvid: String(view.bvid || ""),
      cid: Number(pages[index].cid),
      page: index + 1,
      title: String(view.title || pages[index].part || "未命名视频"),
      part: String(pages[index].part || view.title || ""),
      duration: Number(pages[index].duration || view.duration || 0)
    };
  }

  function pickSubtitleTrack(tracks) {
    if (!Array.isArray(tracks) || !tracks.length) return null;
    const score = (track) => {
      const language = String(track?.lan || track?.lan_doc || "").toLowerCase();
      if (/zh-cn|zh_hans|zh-hans|中文|简体/.test(language)) return 0;
      if (/^zh|中文/.test(language)) return 1;
      if (/^en|english/.test(language)) return 2;
      return 3;
    };
    return [...tracks].sort((a, b) => score(a) - score(b))[0];
  }

  function normalizeSegments(input, duration) {
    const rows = Array.isArray(input?.body) ? input.body : input;
    if (!Array.isArray(rows)) throw new Error("字幕格式不正确。");
    const maxTime = Number.isFinite(Number(duration)) && Number(duration) > 0
      ? Number(duration) : Infinity;
    return rows.map((row) => {
      const from = Number(row?.from ?? row?.start ?? row?.start_time);
      const to = Number(row?.to ?? row?.end ?? row?.end_time ?? from + 1);
      const content = String(row?.content ?? row?.text ?? "").replace(/\s+/g, " ").trim();
      return { from, to, content };
    }).filter((row) => row.content && Number.isFinite(row.from) && row.from >= 0 &&
      row.from < maxTime && Number.isFinite(row.to) && row.to > row.from)
      .sort((a, b) => a.from - b.from);
  }

  function transcriptCoverage(segments, duration) {
    const first = segments.length ? segments[0].from : 0;
    const last = segments.reduce((end, segment) => Math.max(end, segment.to), 0);
    const complete = segments.length > 0 &&
      (duration < 180 || (first <= duration * 0.2 && last >= duration * 0.6));
    return { first, last, complete };
  }

  function chapterCoverage(result, duration) {
    const starts = Array.isArray(result?.chapters)
      ? result.chapters.map((chapter) => Number(chapter?.start)).filter(Number.isFinite) : [];
    const first = starts.length ? Math.min(...starts) : 0;
    const last = starts.length ? Math.max(...starts) : 0;
    const complete = starts.length > 0 &&
      (duration < 180 || (first <= duration * 0.2 && last >= duration * 0.4));
    return { first, last, complete };
  }

  function chunkSegments(segments, maxChars = 9000) {
    const limit = Math.max(500, Number(maxChars) || 9000);
    const chunks = [];
    let lines = [];
    let length = 0;
    let start = 0;
    let end = 0;
    const flush = () => {
      if (lines.length) chunks.push({ start, end, text: lines.join("\n") });
      lines = [];
      length = 0;
    };
    for (const segment of segments) {
      const line = `[${formatTime(segment.from)}] ${segment.content}`;
      if (lines.length && length + line.length + 1 > limit) flush();
      if (!lines.length) start = segment.from;
      end = segment.to;
      lines.push(line);
      length += line.length + 1;
    }
    flush();
    return chunks;
  }

  function parseModelJson(content) {
    let text = typeof content === "string" ? content :
      Array.isArray(content) ? content.map((part) => part?.text || "").join("\n") : "";
    text = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    const first = text.indexOf("{");
    const last = text.lastIndexOf("}");
    if (first < 0 || last < first) throw new Error("模型没有返回有效的 JSON。请重试或更换模型。");
    try {
      return JSON.parse(text.slice(first, last + 1));
    } catch {
      throw new Error("模型返回的 JSON 无法解析。请重试或更换模型。");
    }
  }

  function normalizeResult(value, duration) {
    const limit = Number.isFinite(Number(duration)) && Number(duration) > 0
      ? Number(duration) : Infinity;
    const summary = String(value?.summary || "").trim();
    const chapters = (Array.isArray(value?.chapters) ? value.chapters : [])
      .map((chapter) => ({
        start: Number(chapter?.start ?? chapter?.time),
        title: String(chapter?.title || "").trim().slice(0, 90),
        summary: String(chapter?.summary || "").trim().slice(0, 500)
      }))
      .filter((chapter) => Number.isFinite(chapter.start) && chapter.start >= 0 &&
        chapter.start < limit && chapter.title)
      .sort((a, b) => a.start - b.start)
      .filter((chapter, index, list) => index === 0 || chapter.start - list[index - 1].start >= 2);
    if (!summary || !chapters.length) {
      throw new Error("模型返回内容缺少总结或章节，请重试或更换模型。");
    }
    return { summary, chapters };
  }

  const api = { formatTime, selectPage, pickSubtitleTrack, normalizeSegments,
    transcriptCoverage, chapterCoverage, chunkSegments, parseModelJson, normalizeResult };
  root.BiliAICore = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
