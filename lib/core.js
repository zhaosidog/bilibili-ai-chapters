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

  function formatSrtTime(value) {
    const milliseconds = Math.max(0, Math.round(Number(value) * 1000) || 0);
    const hours = Math.floor(milliseconds / 3600000);
    const minutes = Math.floor((milliseconds % 3600000) / 60000);
    const seconds = Math.floor((milliseconds % 60000) / 1000);
    const rest = milliseconds % 1000;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")},${String(rest).padStart(3, "0")}`;
  }

  function segmentsToSrt(segments) {
    return segments.map((segment, index) =>
      `${index + 1}\r\n${formatSrtTime(segment.from)} --> ${formatSrtTime(segment.to)}\r\n${segment.content}`
    ).join("\r\n\r\n") + "\r\n";
  }

  function segmentsToText(segments) {
    return segments.map((segment) =>
      `[${formatTime(segment.from)}] ${segment.content}`
    ).join("\r\n") + "\r\n";
  }

  function subtitleFilename(title, bvid, page, format) {
    const safeTitle = String(title || "").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
      .replace(/\s+/g, " ").slice(0, 80).replace(/[. ]+$/g, "") || "视频字幕";
    const part = Number(page) > 1 ? `_P${Math.floor(Number(page))}` : "";
    return `${safeTitle}_${bvid}${part}.${format}`;
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

  function pickYouTubeCaptionTracks(tracks) {
    if (!Array.isArray(tracks)) return [];
    const languageRank = (track) => {
      const language = String(track?.languageCode || "").toLowerCase();
      if (/^zh(?:-|$)/.test(language)) return 0;
      if (/^en(?:-|$)/.test(language)) return 1;
      return 2;
    };
    return tracks.filter((track) => track && typeof track.baseUrl === "string")
      .map((track, index) => ({ track, index }))
      .sort((a, b) => languageRank(a.track) - languageRank(b.track) ||
        Number(a.track.kind === "asr") - Number(b.track.kind === "asr") || a.index - b.index)
      .map(({ track }) => track);
  }

  function youtubeCaptionSegments(document, duration) {
    if (!Array.isArray(document?.events)) throw new Error("YouTube 字幕格式不正确。");
    const rows = document.events.map((event) => {
      const from = Number(event?.tStartMs) / 1000;
      const length = Number(event?.dDurationMs);
      return {
        from,
        to: from + (Number.isFinite(length) && length > 0 ? length / 1000 : 1),
        content: Array.isArray(event?.segs) ? event.segs.map((segment) =>
          String(segment?.utf8 || "")).join("") : ""
      };
    });
    return normalizeSegments(rows, duration);
  }

  function youtubePanelSegments(document, duration) {
    const rows = [];
    const pending = [document];
    let visited = 0;
    while (pending.length && rows.length < 20_000 && visited++ < 200_000) {
      const node = pending.pop();
      if (!node || typeof node !== "object") continue;
      if (node.transcriptSegmentViewModel) {
        const segment = node.transcriptSegmentViewModel;
        const parts = String(segment.timestamp || "").trim().split(":");
        if (parts.length >= 2 && parts.length <= 3 && parts.every((part) => /^\d+$/.test(part))) {
          const from = parts.reduce((seconds, part) => seconds * 60 + Number(part), 0);
          const content = String(segment.simpleText || "").replace(/\s+/g, " ").trim();
          if (content) rows.push({ from, content });
        }
        continue;
      }
      const children = Array.isArray(node) ? node : Object.values(node);
      for (let index = children.length - 1; index >= 0; index--) pending.push(children[index]);
    }
    rows.sort((a, b) => a.from - b.from);
    const unique = rows.filter((row, index) => index === 0 || row.from !== rows[index - 1].from ||
      row.content !== rows[index - 1].content);
    return normalizeSegments(unique.map((row, index) => ({
      ...row,
      to: Math.min(Number(duration) || Infinity, row.from + 8,
        unique[index + 1]?.from > row.from ? unique[index + 1].from : Infinity)
    })), duration);
  }

  function embeddedYouTubePlayerResponse(text, videoId) {
    if (typeof text !== "string" || text.length > 8_000_000) return null;
    const marker = /ytInitialPlayerResponse\s*=\s*/g;
    let match;
    while ((match = marker.exec(text))) {
      const start = match.index + match[0].length;
      if (text[start] !== "{") continue;
      let depth = 0;
      let quoted = false;
      let escaped = false;
      for (let index = start; index < text.length; index++) {
        const char = text[index];
        if (quoted) {
          if (escaped) escaped = false;
          else if (char === "\\") escaped = true;
          else if (char === '"') quoted = false;
        } else if (char === '"') quoted = true;
        else if (char === "{") depth++;
        else if (char === "}" && --depth === 0) {
          try {
            const player = JSON.parse(text.slice(start, index + 1));
            if (player?.videoDetails?.videoId === videoId) return player;
          } catch { /* try another script assignment */ }
          marker.lastIndex = index + 1;
          break;
        }
      }
    }
    return null;
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

  function activeSegmentIndex(segments, seconds) {
    const time = Number(seconds);
    if (!Array.isArray(segments) || !segments.length || !Number.isFinite(time) || time < 0) return -1;
    let left = 0;
    let right = segments.length;
    while (left < right) {
      const middle = Math.floor((left + right) / 2);
      if (segments[middle].from <= time) left = middle + 1;
      else right = middle;
    }
    for (let index = left - 1; index >= 0; index--) {
      if (time < segments[index].to) return index;
    }
    return -1;
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

  const api = { formatTime, formatSrtTime, segmentsToSrt, segmentsToText,
    subtitleFilename, selectPage, pickSubtitleTrack, pickYouTubeCaptionTracks,
    youtubeCaptionSegments, youtubePanelSegments, embeddedYouTubePlayerResponse, normalizeSegments,
    transcriptCoverage, activeSegmentIndex, chapterCoverage, chunkSegments,
    parseModelJson, normalizeResult };
  root.BiliAICore = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
