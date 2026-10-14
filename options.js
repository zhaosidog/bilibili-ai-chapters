"use strict";

const PRESETS = {
  deepseek: { endpoint: "https://api.deepseek.com/chat/completions", model: "deepseek-flash" },
  "glm-cn": { endpoint: "https://open.bigmodel.cn/api/paas/v4/chat/completions", model: "glm-4.7-flash" },
  "glm-global": { endpoint: "https://api.z.ai/api/paas/v4/chat/completions", model: "glm-5.3" },
  "qwen-cn": { endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", model: "qwen3.5-35b-a3b" }
};

const $ = (id) => document.getElementById(id);

function feedback(message, error = false) {
  $("feedback").textContent = message;
  $("feedback").classList.toggle("error", error);
}

function validateEndpoint(raw) {
  let url;
  try { url = new URL(raw); } catch { throw new Error("请输入有效的 API 地址。"); }
  if (url.protocol !== "https:" &&
      !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) {
    throw new Error("API 地址必须使用 HTTPS；本机地址可使用 HTTP。");
  }
  if (url.username || url.password || url.hash) throw new Error("API 地址不能包含账户、密码或 # 片段。");
  return url;
}

function originPattern(url) {
  return `${url.protocol}//${url.hostname}/*`;
}

async function saveSettings(event) {
  event?.preventDefault();
  const button = $("save");
  button.disabled = true;
  try {
    const endpoint = validateEndpoint($("endpoint").value.trim());
    const model = $("model").value.trim();
    const apiKey = $("api-key").value.trim();
    if (!model || !apiKey) throw new Error("请填写模型名称和 API Key。");
    const helperOrigin = endpoint.protocol === "http:" && endpoint.hostname === "127.0.0.1";
    const origins = helperOrigin ? [] : [originPattern(endpoint)];
    const granted = origins.length ? await chrome.permissions.request({ origins }) : true;
    if (!granted) throw new Error("浏览器没有授予模型接口的访问权限。");
    await chrome.storage.local.set({
      aiSettings: {
        provider: $("provider").value,
        endpoint: endpoint.href,
        model,
        apiKey,
        autoAnalyze: $("auto-analyze").checked,
        localAsrEnabled: $("local-asr").checked,
        jsonMode: $("json-mode").checked
      }
    });
    feedback("已保存。回到 B 站或 YouTube 视频页，点击“AI 章节”查看结果。");
    return true;
  } catch (error) {
    feedback(error.message || "保存失败。", true);
    return false;
  } finally {
    button.disabled = false;
  }
}

async function testModel() {
  const button = $("test");
  button.disabled = true;
  try {
    if (!await saveSettings()) return;
    feedback("正在测试连接…");
    const response = await chrome.runtime.sendMessage({
      type: "MODEL_CALL",
      final: false,
      messages: [
        { role: "system", content: "请仅返回 JSON。" },
        { role: "user", content: "请返回 {\"summary\":\"连接成功\",\"chapters\":[{\"start\":0,\"title\":\"测试\",\"summary\":\"测试\"}]}。" }
      ]
    });
    if (!response?.ok) throw new Error(response?.error || "连接失败。");
    const content = response.result?.content;
    const text = typeof content === "string" ? content :
      Array.isArray(content) ? content.map((item) => item?.text || "").join("\n") : "";
    const first = text.indexOf("{");
    const last = text.lastIndexOf("}");
    if (first < 0 || last < first) throw new Error("模型已响应，但没有返回章节 JSON。");
    let parsed;
    try { parsed = JSON.parse(text.slice(first, last + 1)); }
    catch { throw new Error("模型已响应，但返回的章节 JSON 无法解析。"); }
    if (!parsed.summary || !Array.isArray(parsed.chapters)) {
      throw new Error("模型已响应，但返回格式与章节生成要求不符。");
    }
    feedback("模型连接成功。");
  } catch (error) {
    feedback(error.message || "连接失败。", true);
  } finally {
    button.disabled = false;
  }
}

async function init() {
  const saved = await chrome.storage.local.get("aiSettings");
  const config = saved.aiSettings || {};
  $("provider").value = config.provider || "glm-cn";
  $("endpoint").value = config.endpoint || PRESETS["glm-cn"].endpoint;
  $("model").value = config.model || PRESETS["glm-cn"].model;
  $("api-key").value = config.apiKey || "";
  $("auto-analyze").checked = config.autoAnalyze !== false;
  $("local-asr").checked = config.localAsrEnabled !== false;
  $("json-mode").checked = config.jsonMode !== false;
  $("provider").addEventListener("change", () => {
    const preset = PRESETS[$("provider").value];
    if (preset) {
      $("endpoint").value = preset.endpoint;
      $("model").value = preset.model;
    }
  });
  $("settings-form").addEventListener("submit", saveSettings);
  $("test").addEventListener("click", testModel);
}

init().catch((error) => feedback(error.message || "无法读取设置。", true));
