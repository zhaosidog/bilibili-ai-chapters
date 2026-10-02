"""Optional isolated-browser smoke test. Requires Python Playwright and Chrome."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BVID = "BV1dRYP6oEtB"
CORS = {
    "access-control-allow-origin": "https://www.bilibili.com",
    "access-control-allow-credentials": "true",
}


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        page.route(
            "https://www.bilibili.com/video/**",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="<html><body><div style='width:900px;height:500px;background:#eee'>"
                "<video style='width:900px;height:500px'></video></div></body></html>",
            ),
        )

        def api(route):
            url = route.request.url
            if "/x/web-interface/view?" in url:
                value = {"code": 0, "data": {"bvid": BVID, "cid": 42,
                    "title": "测试视频", "duration": 100,
                    "pages": [{"cid": 42, "page": 1, "part": "测试视频", "duration": 100}]}}
            elif "/x/player/v2?" in url:
                value = {"code": 0, "data": {"subtitle": {"subtitles": [{
                    "lan": "zh-CN", "lan_doc": "中文",
                    "subtitle_url": "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/test?auth_key=smoke"
                }]}}}
            else:
                value = {"code": 0, "data": {"subtitle": {"subtitles": []}}}
            route.fulfill(status=200, content_type="application/json",
                          headers=CORS, body=json.dumps(value))

        page.route("https://api.bilibili.com/**", api)
        page.route("https://aisubtitle.hdslb.com/**", lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [
                {"from": 0, "to": 4, "content": "介绍主题"},
                {"from": 5, "to": 10, "content": "第一章内容"},
            ]}),
        ))
        page.add_init_script("""
          window.chrome = {runtime: {
            lastError: null,
            onMessage: {addListener: () => {}},
            sendMessage(message, callback) {
              let result = null;
              if (message.type === 'GET_SETTINGS') result = {
                configured: true, autoAnalyze: true, localAsrEnabled: true,
                profileId: 'smoke', model: 'test'
              };
              if (message.type === 'MODEL_CALL') result = {content: JSON.stringify({
                summary: '这是视频总结。',
                chapters: [{start: 5, title: '第一章', summary: '章节内容'}]
              })};
              callback({ok: true, result});
            }
          }};
        """)
        page.goto(f"https://www.bilibili.com/video/{BVID}/")
        page.evaluate("""() => {
          const video = document.querySelector('video');
          Object.defineProperty(video, 'duration', {value: 100});
          Object.defineProperty(video, 'currentTime', {
            get() { return window.__seek || 0; },
            set(value) { window.__seek = value; }
          });
        }""")
        page.add_style_tag(content=(ROOT / "content.css").read_text(encoding="utf-8"))
        page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
        page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))
        page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=10000)
        page.locator(".bili-ai-badge").click()
        assert page.locator(".bili-ai-summary").inner_text() == "这是视频总结。"
        assert page.locator(".bili-ai-chapter-title").inner_text() == "第一章"
        page.locator(".bili-ai-chapter").click()
        assert page.evaluate("window.__seek") == 5
        artifact = ROOT / "artifacts"
        artifact.mkdir(exist_ok=True)
        page.screenshot(path=str(artifact / "ui-smoke.png"), full_page=True)

        long_page = browser.new_page(viewport={"width": 1440, "height": 900})
        long_page.route("https://www.bilibili.com/video/**", lambda route: route.fulfill(
            status=200, content_type="text/html",
            body="<html><body><video></video></body></html>",
        ))
        long_page.route("https://api.bilibili.com/**", api)
        long_page.route("https://aisubtitle.hdslb.com/**", lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [
                {"from": i * 5, "to": i * 5 + 4, "content": "内容" * 900}
                for i in range(12)
            ]}),
        ))
        long_page.add_init_script("""
          window.chrome = {runtime: {
            lastError: null,
            onMessage: {addListener: () => {}},
            sendMessage(message, callback) {
              if (message.type === 'GET_SETTINGS') {
                callback({ok: true, result: {
                  configured: true, autoAnalyze: true, localAsrEnabled: false,
                  profileId: 'long-smoke', model: 'test'
                }});
                return;
              }
              if (message.type === 'MODEL_CALL') {
                const prompt = message.messages[1].content;
                const start = Number(prompt.match(/范围 (\\d+)-/)?.[1] || 0);
                setTimeout(() => callback({ok: true, result: {content: JSON.stringify({
                  summary: '视频总结',
                  chapters: [{start, title: '测试章节', summary: '章节内容'}]
                })}}), message.final ? 1500 : 1100);
                return;
              }
              callback({ok: true, result: null});
            }
          }};
        """)
        long_page.goto(f"https://www.bilibili.com/video/{BVID}/")
        long_page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
        long_page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))
        long_page.locator(".bili-ai-status:has-text('正在整合全片')").wait_for(
            state="attached", timeout=12000)
        merging = long_page.locator(".bili-ai-status").inner_text()
        assert "已完成 3/4 步，正在进行第 4 步" in merging, merging
        assert "预计剩余约" in merging, merging
        long_page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=5000)
        assert long_page.locator(".bili-ai-status").inner_text() == "完成：1 个章节。"
        long_page.close()

        options = browser.new_page(viewport={"width": 1100, "height": 900})
        options.add_init_script("""
          window.chrome = {
            storage: {local: {
              get: async () => ({}),
              set: async (value) => {window.__stored = value;}
            }},
            permissions: {request: async () => true},
            runtime: {sendMessage: async () => ({ok: true, result: {
              content: '{"summary":"连接成功","chapters":[]}'
            }})}
          };
        """)
        options.goto((ROOT / "options.html").as_uri())
        assert options.locator("#model").input_value() == "glm-4.7-flash"
        options.locator("#api-key").fill("test-key")
        options.locator("#save").click()
        assert options.evaluate("window.__stored.aiSettings.model") == "glm-4.7-flash"
        assert options.locator("#feedback").inner_text().startswith("已保存")
        options.locator("#test").click()
        assert options.locator("#feedback").inner_text() == "模型连接成功。"
        options.screenshot(path=str(artifact / "options-smoke.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    run()
    print("UI smoke test passed")
