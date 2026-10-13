const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function createWorker(fetchImpl, initialSettings = {}, actionStubs = {}) {
  let messageListener;
  let actionListener;
  const actionCalls = [];
  const storage = { aiSettings: {
    apiKey: "private-key",
    jsonMode: true,
    ...initialSettings
  } };
  const chrome = {
    storage: { local: {
      setAccessLevel: async () => {},
      get: async (key) => ({ [key]: storage[key] }),
      set: async (value) => Object.assign(storage, value)
    } },
    runtime: { onMessage: { addListener: (listener) => { messageListener = listener; } },
      openOptionsPage: async () => { actionCalls.push(["options"]); },
      getURL: (resource) => `chrome-extension://test-extension/${resource}` },
    action: { onClicked: { addListener: (listener) => { actionListener = listener; } } },
    tabs: {
      get: async (tabId) => {
        actionCalls.push(["getTab", tabId]);
        return { url: actionStubs.tabUrl || "" };
      },
      sendMessage: async (tabId, message) => {
        actionCalls.push(["sendMessage", tabId, message]);
        return actionStubs.sendMessage?.(tabId, message);
      },
      create: async (details) => {
        actionCalls.push(["createTab", details]);
        return actionStubs.createTab?.(details);
      }
    },
    scripting: {
      insertCSS: async (details) => {
        actionCalls.push(["insertCSS", details]);
        return actionStubs.insertCSS?.(details);
      },
      executeScript: async (details) => {
        actionCalls.push(["executeScript", details]);
        return actionStubs.executeScript?.(details);
      }
    }
  };
  const source = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  vm.runInNewContext(source, { chrome, fetch: fetchImpl, URL, AbortController,
    setTimeout, clearTimeout, console, Math, Date, Promise }, { filename: "background.js" });
  return {
    storage,
    send: (message) => new Promise((resolve) => messageListener(message, {}, resolve)),
    clickAction: (tab) => actionListener(tab),
    actionCalls
  };
}

test("action on a YouTube watch page opens the in-page panel", async () => {
  const worker = createWorker(async () => { throw new Error("unexpected fetch"); });
  await worker.clickAction({ id: 42, url: "https://www.youtube.com/watch?v=ABCDEFGHIJK&t=12" });
  assert.deepEqual(worker.actionCalls.map(([name]) => name), ["sendMessage"]);
  assert.equal(worker.actionCalls[0][1], 42);
  assert.equal(worker.actionCalls[0][2].type, "TOGGLE_PANEL");
});

test("action can read the clicked video tab URL when it is absent from the click event", async () => {
  const worker = createWorker(async () => { throw new Error("unexpected fetch"); }, {}, {
    tabUrl: "https://www.youtube.com/watch?v=ABCDEFGHIJK"
  });
  await worker.clickAction({ id: 42 });
  assert.deepEqual(worker.actionCalls.map(([name]) => name), ["getTab", "sendMessage"]);
});

test("action injects the content script and retries if a watch page has no receiver yet", async () => {
  let attempts = 0;
  const worker = createWorker(async () => { throw new Error("unexpected fetch"); }, {}, {
    sendMessage: async () => {
      if (++attempts === 1) throw new Error("Could not establish connection. Receiving end does not exist.");
    }
  });
  await worker.clickAction({ id: 42, url: "https://www.youtube.com/watch?v=ABCDEFGHIJK" });
  const calls = worker.actionCalls;
  assert.equal(calls.filter(([name]) => name === "sendMessage").length, 2);
  assert.equal(calls.some(([name]) => name === "insertCSS"), true);
  assert.equal(calls.some(([name]) => name === "executeScript"), true);
  const injected = calls.filter(([name]) => name === "executeScript")
    .flatMap(([, details]) => details.files || []);
  assert.equal(injected.includes("lib/core.js"), true);
  assert.equal(injected.includes("content.js"), true);
  assert.equal(calls.some(([name]) => name === "createTab" || name === "options"), false);
});

test("action on the YouTube homepage asks the page to show its video hint", async () => {
  const worker = createWorker(async () => { throw new Error("unexpected fetch"); });
  await worker.clickAction({ id: 42, url: "https://www.youtube.com/" });
  assert.deepEqual(worker.actionCalls.map(([name]) => name), ["sendMessage"]);
  assert.equal(worker.actionCalls[0][2].type, "TOGGLE_PANEL");
});

test("action opens extension help if the YouTube content script cannot be injected", async () => {
  const worker = createWorker(async () => { throw new Error("unexpected fetch"); }, {}, {
    sendMessage: async () => { throw new Error("No receiver"); },
    executeScript: async () => { throw new Error("The extensions gallery cannot be scripted"); }
  });
  await worker.clickAction({ id: 42, url: "https://www.youtube.com/watch?v=ABCDEFGHIJK" });
  const created = worker.actionCalls.filter(([name]) => name === "createTab");
  assert.equal(created.length, 1);
  assert.equal(created[0][1].url, "chrome-extension://test-extension/help.html");
  assert.equal(worker.actionCalls.some(([name]) => name === "options"), false);
});

test("content script gets non-secret settings and model calls carry the key only in worker fetch", async () => {
  let request;
  const worker = createWorker(async (url, init) => {
    request = { url, init };
    return { ok: true, status: 200, text: async () => JSON.stringify({
      choices: [{ finish_reason: "stop", message: { content: '{"summary":"好","chapters":[]}' } }]
    }) };
  });
  const publicConfig = await worker.send({ type: "GET_SETTINGS" });
  assert.equal(publicConfig.ok, true);
  assert.equal(publicConfig.result.configured, true);
  assert.equal(JSON.stringify(publicConfig).includes("private-key"), false);
  const answer = await worker.send({ type: "MODEL_CALL", messages: [
    { role: "user", content: "视频字幕" }
  ] });
  assert.equal(answer.ok, true);
  assert.equal(request.url, "https://open.bigmodel.cn/api/paas/v4/chat/completions");
  assert.equal(request.init.headers.Authorization, "Bearer private-key");
  const body = JSON.parse(request.init.body);
  assert.equal(body.model, "glm-4.7-flash");
  assert.equal(body.response_format.type, "json_object");
  assert.equal(body.enable_thinking, undefined);
  assert.equal(body.thinking.type, "disabled");
});

test("Qwen JSON mode disables thinking without changing other model requests", async () => {
  let body;
  const worker = createWorker(async (_url, init) => {
    body = JSON.parse(init.body);
    return { ok: true, status: 200, text: async () => JSON.stringify({
      choices: [{ finish_reason: "stop", message: { content: '{"summary":"好","chapters":[]}' } }]
    }) };
  }, { provider: "qwen-cn", endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    model: "qwen3.5-35b-a3b" });
  const response = await worker.send({ type: "MODEL_CALL", messages: [
    { role: "user", content: "请按 JSON 总结视频字幕" }
  ] });
  assert.equal(response.ok, true);
  assert.equal(body.response_format.type, "json_object");
  assert.equal(body.enable_thinking, false);
  assert.equal(body.thinking, undefined);
});

test("DeepSeek Flash disables thinking without Qwen-specific parameters", async () => {
  let body;
  const worker = createWorker(async (_url, init) => {
    body = JSON.parse(init.body);
    return { ok: true, status: 200, text: async () => JSON.stringify({
      choices: [{ finish_reason: "stop", message: { content: '{"summary":"好","chapters":[]}' } }]
    }) };
  }, { provider: "deepseek", endpoint: "https://api.deepseek.com/chat/completions",
    model: "deepseek-flash" });
  const response = await worker.send({ type: "MODEL_CALL", messages: [
    { role: "user", content: "请按 JSON 总结视频字幕" }
  ] });
  assert.equal(response.ok, true);
  assert.equal(body.thinking.type, "disabled");
  assert.equal(body.enable_thinking, undefined);
});

test("worker blocks untrusted fetch targets and insecure model endpoints", async () => {
  const worker = createWorker(async () => { throw new Error("fetch should not run"); },
    { endpoint: "http://example.com/chat/completions" });
  const bili = await worker.send({ type: "BILI_GET", url: "https://evil.example/steal" });
  assert.equal(bili.ok, false);
  const model = await worker.send({ type: "MODEL_CALL", messages: [
    { role: "user", content: "hello" }
  ] });
  assert.equal(model.ok, false);
  assert.match(model.error, /HTTPS/);
});

test("worker reads AI subtitle URLs but rejects unrelated CDN paths", async () => {
  let fetchedUrl;
  const worker = createWorker(async (url) => {
    fetchedUrl = url;
    return { ok: true, json: async () => ({ body: [
      { from: 0, to: 2, content: "字幕" }
    ] }) };
  });
  const aiUrl = "https://aisubtitle.hdslb.com/bfs/ai_subtitle/prod/test?auth_key=smoke";
  const accepted = await worker.send({ type: "BILI_GET", url: aiUrl });
  assert.equal(accepted.ok, true);
  assert.equal(fetchedUrl, aiUrl);
  const rejected = await worker.send({ type: "BILI_GET",
    url: "https://aisubtitle.hdslb.com/bfs/face/test.json" });
  assert.equal(rejected.ok, false);
  const otherHost = await worker.send({ type: "BILI_GET",
    url: "https://evil.example/bfs/ai_subtitle/prod/test" });
  assert.equal(otherHost.ok, false);
});

test("local ASR request uses only validated BVID and page", async () => {
  let body;
  const worker = createWorker(async (_url, init) => {
    body = JSON.parse(init.body);
    return { ok: true, json: async () => ({ job_id: "job123", status: "queued" }) };
  });
  const response = await worker.send({ type: "LOCAL_ASR", action: "start",
    bvid: "BV1dRYP6oEtB", page: 2 });
  assert.equal(response.ok, true);
  assert.equal(body.p, 2);
  const invalid = await worker.send({ type: "LOCAL_ASR", action: "start",
    bvid: "../etc/passwd", page: 1 });
  assert.equal(invalid.ok, false);
});

test("YouTube ASR and summary cache accept only validated platform IDs", async () => {
  let body;
  const worker = createWorker(async (_url, init) => {
    body = JSON.parse(init.body);
    return { ok: true, json: async () => ({ job_id: "job123", status: "queued" }) };
  });
  const started = await worker.send({ type: "LOCAL_ASR", action: "start",
    youtubeId: "ABCDEFGHIJK" });
  assert.equal(started.ok, true);
  assert.equal(JSON.stringify(body), '{"youtubeId":"ABCDEFGHIJK"}');
  const invalid = await worker.send({ type: "LOCAL_ASR", action: "start",
    youtubeId: "../bad-id" });
  assert.equal(invalid.ok, false);
  const mixed = await worker.send({ type: "LOCAL_ASR", action: "start",
    youtubeId: "ABCDEFGHIJK", bvid: "BV1dRYP6oEtB" });
  assert.equal(mixed.ok, false);
  const key = "yt:ABCDEFGHIJK:test-profile";
  await worker.send({ type: "PUT_CACHE", key, value: { summary: "YouTube 总结" } });
  assert.equal((await worker.send({ type: "GET_CACHE", key })).result.summary, "YouTube 总结");
  assert.equal((await worker.send({ type: "GET_CACHE", key: "yt:../bad-id:test" })).result, null);
});
