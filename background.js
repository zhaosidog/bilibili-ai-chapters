"use strict";

const DEFAULT_SETTINGS = {
  provider: "glm-cn",
  endpoint: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
  model: "glm-4.7-flash",
  apiKey: "",
  autoAnalyze: true,
  localAsrEnabled: true,
  jsonMode: true
};

const storageReady = chrome.storage.local.setAccessLevel
  ? chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" })
  : Promise.resolve();

async function settings() {
  await storageReady;
  const saved = await chrome.storage.local.get("aiSettings");
  return { ...DEFAULT_SETTINGS, ...(saved.aiSettings || {}) };
}

function publicSettings(value) {
  let hash = 2166136261;
  for (const char of `${value.endpoint}|${value.model}|${value.jsonMode}`) {
    hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  }
  return {
    configured: Boolean(value.apiKey && value.endpoint && value.model),
    provider: value.provider,
    model: value.model,
    profileId: (hash >>> 0).toString(16),
    autoAnalyze: Boolean(value.autoAnalyze),
    localAsrEnabled: Boolean(value.localAsrEnabled)
  };
}

function checkedEndpoint(raw) {
  let url;
  try { url = new URL(raw); } catch { throw new Error("模型 API 地址无效。"); }
  if (url.protocol !== "https:" &&
      !(url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname))) {
    throw new Error("模型 API 必须使用 HTTPS；本机地址可使用 HTTP。");
  }
  if (url.username || url.password || url.hash) throw new Error("模型 API 地址含有不支持的参数。");
  return url;
}

async function modelCall(message) {
  const config = await settings();
  if (!config.apiKey) throw new Error("请先在扩展设置中填写 API Key。");
  const endpoint = checkedEndpoint(config.endpoint);
  const messages = message.messages;
  if (!Array.isArray(messages) || !messages.length || messages.length > 5 ||
      messages.some((item) => !["system", "user"].includes(item?.role) ||
        typeof item.content !== "string") ||
      messages.reduce((sum, item) => sum + item.content.length, 0) > 75000) {
    throw new Error("发送给模型的文本格式或长度不正确。");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const body = {
      model: config.model,
      messages,
      stream: false,
      temperature: 0.2,
      max_tokens: message.final ? 3500 : 1800
    };
    if (config.jsonMode) {
      body.response_format = { type: "json_object" };
      if (config.provider === "qwen-cn" || /^qwen3\.5-/i.test(config.model)) {
        body.enable_thinking = false;
      }
    }
    if ((config.provider === "glm-cn" && config.model === "glm-4.7-flash") ||
        (config.provider === "deepseek" && config.model === "deepseek-flash")) {
      body.thinking = { type: "disabled" };
    }
    const response = await fetch(endpoint.href, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${config.apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    const raw = await response.text();
    let data;
    try { data = JSON.parse(raw); } catch { throw new Error(`模型接口返回非 JSON（HTTP ${response.status}）。`); }
    if (!response.ok) {
      const detail = String(data?.error?.message || data?.message || "请求失败")
        .replaceAll(config.apiKey, "[API Key]").slice(0, 300);
      throw new Error(`模型接口 HTTP ${response.status}：${detail}`);
    }
    const choice = data?.choices?.[0];
    if (choice?.finish_reason === "length") {
      throw new Error("模型输出被截断。请减少输入长度或提高接口的输出上限。");
    }
    const content = choice?.message?.content;
    if (!content) throw new Error("模型接口没有返回正文。");
    return { content };
  } catch (error) {
    if (error.name === "AbortError") throw new Error("模型接口两分钟内没有响应。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function checkedBiliUrl(raw) {
  let url;
  try { url = new URL(raw); } catch { throw new Error("B 站资源地址无效。"); }
  const api = url.hostname === "api.bilibili.com" &&
    /^\/x\/(web-interface\/view|player\/(?:v2|wbi\/v2))$/.test(url.pathname);
  const subtitlePath = url.pathname.startsWith("/bfs/subtitle/") ||
    url.pathname.startsWith("/bfs/ai_subtitle/");
  const subtitle = url.protocol === "https:" &&
    (url.hostname === "hdslb.com" || url.hostname.endsWith(".hdslb.com")) &&
    subtitlePath;
  if (url.protocol !== "https:" || url.username || url.password || !(api || subtitle)) {
    throw new Error("不允许读取这个 B 站资源地址。");
  }
  return url;
}

async function biliGet(raw) {
  const url = checkedBiliUrl(raw);
  const response = await fetch(url.href, { credentials: "include" });
  if (!response.ok) throw new Error(`B 站资源读取失败（HTTP ${response.status}）。`);
  const json = await response.json();
  if (url.hostname === "api.bilibili.com" && json?.code !== 0) {
    throw new Error(`B 站接口返回错误：${String(json?.message || json?.code).slice(0, 150)}`);
  }
  return json;
}

async function localAsr(message) {
  const config = await settings();
  if (!config.localAsrEnabled) throw new Error("本地语音转写尚未启用。");
  const bvid = String(message.bvid || "");
  const youtubeId = String(message.youtubeId || "");
  if (youtubeId) {
    if (bvid || !/^[A-Za-z0-9_-]{11}$/.test(youtubeId)) throw new Error("YouTube 视频 ID 无效。");
  } else if (!/^BV[0-9A-Za-z]{10}$/.test(bvid)) {
    throw new Error("视频 BV 号无效。");
  }
  const base = "http://127.0.0.1:8765";
  let path;
  let init;
  if (message.action === "start") {
    path = "/transcribe";
    let payload;
    if (youtubeId) {
      if (message.page != null) throw new Error("YouTube 视频没有分 P 参数。");
      payload = { youtubeId };
    } else {
      const page = Math.floor(Number(message.page) || 1);
      if (page < 1 || page > 1000) throw new Error("视频分 P 无效。");
      payload = { bvid, p: page };
    }
    init = { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) };
  } else if (message.action === "poll" && /^[a-z0-9_-]{1,100}$/i.test(message.jobId || "")) {
    path = `/jobs/${encodeURIComponent(message.jobId)}`;
    init = { method: "GET" };
  } else {
    throw new Error("本地转写请求无效。");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(base + path, { ...init, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(String(data?.error || "本地转写服务出错。").slice(0, 300));
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("本地转写服务响应超时。");
    if (error instanceof TypeError) {
      throw new Error("没有连接到本地语音转写服务。请按 README 启动 helper。");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function getCache(key) {
  await storageReady;
  if (!/^(?:BV[0-9A-Za-z]{10}:\d{1,4}|yt:[A-Za-z0-9_-]{11}):.{1,120}$/.test(String(key || ""))) return null;
  const saved = await chrome.storage.local.get("summaryCache");
  return saved.summaryCache?.[key] || null;
}

async function putCache(key, value) {
  await storageReady;
  if (!/^(?:BV[0-9A-Za-z]{10}:\d{1,4}|yt:[A-Za-z0-9_-]{11}):.{1,120}$/.test(String(key || ""))) return;
  const saved = await chrome.storage.local.get("summaryCache");
  const cache = saved.summaryCache || {};
  cache[key] = { ...value, savedAt: Date.now() };
  const keys = Object.keys(cache).sort((a, b) => (cache[b].savedAt || 0) - (cache[a].savedAt || 0));
  for (const stale of keys.slice(40)) delete cache[stale];
  await chrome.storage.local.set({ summaryCache: cache });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    switch (message?.type) {
      case "GET_SETTINGS": return publicSettings(await settings());
      case "BILI_GET": return biliGet(message.url);
      case "MODEL_CALL": return modelCall(message);
      case "LOCAL_ASR": return localAsr(message);
      case "GET_CACHE": return getCache(message.key);
      case "PUT_CACHE": return putCache(message.key, message.value);
      case "OPEN_OPTIONS": await chrome.runtime.openOptionsPage(); return true;
      default: throw new Error("未知的扩展请求。");
    }
  })().then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
  return true;
});

async function toggleVideoPanel(tabId) {
  const message = { type: "TOGGLE_PANEL" };
  try {
    await chrome.tabs.sendMessage(tabId, message);
    return true;
  } catch { /* an existing tab may not have the current content script */ }
  try {
    const target = { tabId };
    await chrome.scripting.insertCSS({ target, files: ["content.css"] });
    await chrome.scripting.executeScript({ target, files: ["lib/core.js", "content.js"] });
    await chrome.tabs.sendMessage(tabId, message);
    return true;
  } catch {
    return false;
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  let url;
  try {
    const address = tab.url || (tab.id != null ? (await chrome.tabs.get(tab.id)).url : "");
    url = new URL(address || "about:blank");
  } catch {
    url = new URL("about:blank");
  }
  const youtubeSite = url.hostname === "www.youtube.com";
  const biliVideo = url.hostname === "www.bilibili.com" && /^\/video\/BV[0-9A-Za-z]{10}/.test(url.pathname);
  if (tab.id != null && (youtubeSite || biliVideo)) {
    if (await toggleVideoPanel(tab.id)) return;
    await chrome.tabs.create({ url: chrome.runtime.getURL("help.html") });
    return;
  }
  if (["youtube.com", "m.youtube.com", "youtu.be"].includes(url.hostname)) {
    await chrome.tabs.create({ url: chrome.runtime.getURL("help.html") });
    return;
  }
  await chrome.runtime.openOptionsPage();
});
