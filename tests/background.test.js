const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function createWorker(fetchImpl, initialSettings = {}) {
  let messageListener;
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
      openOptionsPage: async () => {} },
    action: { onClicked: { addListener: () => {} } },
    tabs: { sendMessage: async () => {} }
  };
  const source = fs.readFileSync(path.join(__dirname, "..", "background.js"), "utf8");
  vm.runInNewContext(source, { chrome, fetch: fetchImpl, URL, AbortController,
    setTimeout, clearTimeout, console, Math, Date, Promise }, { filename: "background.js" });
  return {
    storage,
    send: (message) => new Promise((resolve) => messageListener(message, {}, resolve))
  };
}

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
