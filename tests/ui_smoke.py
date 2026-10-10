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
        with page.expect_download() as srt_event:
            page.locator(".bili-ai-download").click()
        srt = srt_event.value
        assert srt.suggested_filename == f"测试视频_{BVID}.srt"
        srt_text = Path(srt.path()).read_bytes().decode("utf-8-sig")
        assert "1\r\n00:00:00,000 --> 00:00:04,000\r\n介绍主题" in srt_text
        page.locator(".bili-ai-download-format").select_option("txt")
        with page.expect_download() as txt_event:
            page.locator(".bili-ai-download").click()
        txt = txt_event.value
        assert txt.suggested_filename == f"测试视频_{BVID}.txt"
        assert Path(txt.path()).read_bytes().decode("utf-8-sig") == (
            "[0:00] 介绍主题\r\n[0:05] 第一章内容\r\n")
        artifact = ROOT / "artifacts"
        artifact.mkdir(exist_ok=True)
        page.screenshot(path=str(artifact / "ui-smoke.png"), full_page=True)

        cached_page = browser.new_page(viewport={"width": 1440, "height": 900})
        cached_page.route("https://www.bilibili.com/video/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<html><body><video></video></body></html>",
        ))
        cached_page.route("https://api.bilibili.com/**", api)
        cached_page.route("https://aisubtitle.hdslb.com/**", lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [
                {"from": 0, "to": 4, "content": "缓存视频开场"},
                {"from": 90, "to": 98, "content": "缓存视频结尾"},
            ]}),
        ))
        cached_page.add_init_script("""
          window.__modelCalls = 0;
          window.chrome = {runtime: {
            lastError: null,
            onMessage: {addListener: () => {}},
            sendMessage(message, callback) {
              if (message.type === 'GET_SETTINGS') return callback({ok: true, result: {
                configured: true, autoAnalyze: true, localAsrEnabled: false,
                profileId: 'cached-smoke', model: 'test'
              }});
              if (message.type === 'GET_CACHE') return callback({ok: true, result: {
                title: '测试视频', source: 'B 站字幕（中文）', result: {
                  summary: '缓存的总结', chapters: [{start: 0, title: '开场'}]
                }
              }});
              if (message.type === 'MODEL_CALL') window.__modelCalls++;
              callback({ok: true, result: null});
            }
          }};
        """)
        cached_page.goto(f"https://www.bilibili.com/video/{BVID}/")
        cached_page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
        cached_page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))
        cached_page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=10000)
        cached_page.locator(".bili-ai-badge").click()
        assert cached_page.locator(".bili-ai-summary").inner_text() == "缓存的总结"
        with cached_page.expect_download() as cached_event:
            cached_page.locator(".bili-ai-download").click()
        cached_text = Path(cached_event.value.path()).read_bytes().decode("utf-8-sig")
        assert "缓存视频结尾" in cached_text
        assert cached_page.evaluate("window.__modelCalls") == 0
        cached_page.close()

        keyless_page = browser.new_page(viewport={"width": 1440, "height": 900})
        keyless_page.route("https://www.bilibili.com/video/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<html><body><video></video></body></html>",
        ))
        keyless_page.route("https://api.bilibili.com/**", api)
        keyless_page.route("https://aisubtitle.hdslb.com/**", lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [{"from": 0, "to": 90, "content": "无需模型密钥的字幕"}]}),
        ))
        keyless_page.add_init_script("""
          window.chrome = {runtime: {
            lastError: null,
            onMessage: {addListener: () => {}},
            sendMessage(message, callback) {
              if (message.type === 'GET_SETTINGS') return callback({ok: true, result: {
                configured: false, autoAnalyze: true, localAsrEnabled: false
              }});
              if (message.type === 'MODEL_CALL') throw new Error('download called model');
              callback({ok: true, result: null});
            }
          }};
        """)
        keyless_page.goto(f"https://www.bilibili.com/video/{BVID}/")
        keyless_page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
        keyless_page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))
        keyless_page.locator(".bili-ai-badge[data-kind='error']").wait_for(timeout=10000)
        keyless_page.locator(".bili-ai-badge").click()
        with keyless_page.expect_download() as keyless_event:
            keyless_page.locator(".bili-ai-download").click()
        assert "无需模型密钥的字幕" in Path(keyless_event.value.path()).read_bytes().decode("utf-8-sig")
        keyless_page.close()

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

        wrong_bvid = "BV1SUhe6xEM2"
        wrong_title = "【硬核】俄乌打了四年多，到底谁在买单？"
        broken_page = browser.new_page(viewport={"width": 1440, "height": 900})
        broken_page.route("https://www.bilibili.com/video/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<html><body><video></video></body></html>",
        ))

        def broken_api(route):
            if "/x/web-interface/view?" in route.request.url:
                value = {"code": 0, "data": {"bvid": wrong_bvid, "cid": 42069067290,
                    "title": wrong_title, "duration": 1744}}
            else:
                value = {"code": 0, "data": {"subtitle": {"subtitles": [{
                    "lan": "zh-CN", "lan_doc": "中文",
                    "subtitle_url": "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/test?auth_key=smoke"
                }]}}}
            route.fulfill(status=200, content_type="application/json",
                          headers=CORS, body=json.dumps(value))

        broken_page.route("https://api.bilibili.com/**", broken_api)
        subtitle_pattern = "https://aisubtitle.hdslb.com/**"
        broken_page.route(subtitle_pattern, lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [
                {"from": 0, "to": 30, "content": "冬季温差影响心脑血管"},
                {"from": 70, "to": 80, "content": "注意保暖"},
            ]}),
        ))
        broken_page.add_init_script(f"""
          window.__modelCalls = 0;
          window.__cacheWrites = 0;
          window.chrome = {{runtime: {{
            lastError: null,
            onMessage: {{addListener: () => {{}}}},
            sendMessage(message, callback) {{
              if (message.type === 'GET_SETTINGS') return callback({{ok: true, result: {{
                configured: true, autoAnalyze: true, localAsrEnabled: false,
                profileId: 'wrong-smoke', model: 'test'
              }}}});
              if (message.type === 'GET_CACHE') return callback({{ok: true, result: {{
                title: {json.dumps(wrong_title)}, source: 'B 站字幕（中文）',
                result: {{summary: '冬季心血管风险', chapters: [
                  {{start: 0, title: '导入'}}, {{start: 80, title: '保暖'}}
                ]}}
              }}}});
              if (message.type === 'MODEL_CALL') {{
                window.__modelCalls++;
                return callback({{ok: true, result: {{content: JSON.stringify({{
                  summary: '冬季心血管风险', chapters: [
                    {{start: 0, title: '导入'}}, {{start: 80, title: '保暖'}}
                  ]
                }})}}}});
              }}
              if (message.type === 'PUT_CACHE') window.__cacheWrites++;
              callback({{ok: true, result: null}});
            }}
          }}}};
        """)
        broken_page.goto(f"https://www.bilibili.com/video/{wrong_bvid}/")
        broken_page.add_style_tag(content=(ROOT / "content.css").read_text(encoding="utf-8"))
        broken_page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
        broken_page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))
        broken_page.locator(".bili-ai-status:has-text('B 站字幕仅覆盖')").wait_for(
            state="attached", timeout=10000)
        assert "视频长 29:04" in broken_page.locator(".bili-ai-status").inner_text()
        assert broken_page.evaluate("window.__modelCalls") == 0

        broken_page.unroute(subtitle_pattern)
        broken_page.route(subtitle_pattern, lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [
                {"from": 0, "to": 30, "content": "俄罗斯与乌克兰战争的背景"},
                {"from": 900, "to": 930, "content": "战争带来的经济成本"},
                {"from": 1700, "to": 1720, "content": "谁在为战争买单"},
            ]}),
        ))
        broken_page.locator(".bili-ai-badge").click()
        broken_page.locator(".bili-ai-analyze").click()
        broken_page.locator(".bili-ai-status:has-text('模型生成的章节仅覆盖')").wait_for(
            timeout=10000)
        assert broken_page.evaluate("window.__modelCalls") == 1
        assert broken_page.evaluate("window.__cacheWrites") == 0
        assert broken_page.locator(".bili-ai-summary").inner_text() == ""
        broken_page.screenshot(path=str(artifact / "mismatch-smoke.png"), full_page=True)
        broken_page.close()

        reload_bvid = "BV1P1Yk6EEX9"
        reload_page = browser.new_page(viewport={"width": 1440, "height": 900})
        reload_page.route("https://www.bilibili.com/video/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<html><body><video></video></body></html>",
        ))

        def reload_api(route):
            if "/x/web-interface/view?" in route.request.url:
                value = {"code": 0, "data": {"bvid": reload_bvid, "cid": 123,
                    "title": "minimaxH3教程", "duration": 1077,
                    "pages": [{"cid": 123, "page": 1, "part": "本地部署", "duration": 1077}]}}
            else:
                value = {"code": 0, "data": {"subtitle": {"subtitles": [{
                    "lan": "zh-CN", "lan_doc": "中文",
                    "subtitle_url": "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/test?auth_key=smoke"
                }]}}}
            route.fulfill(status=200, content_type="application/json",
                          headers=CORS, body=json.dumps(value))

        reload_page.route("https://api.bilibili.com/**", reload_api)
        reload_page.route("https://aisubtitle.hdslb.com/**", lambda route: route.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body=json.dumps({"body": [
                {"from": 3, "to": 15, "content": "俺姓张名飞字翼德"},
            ]}),
        ))
        reload_page.add_init_script("""
          window.chrome = {runtime: {
            lastError: null,
            onMessage: {addListener: () => {}},
            sendMessage(message, callback) {
              if (message.type === 'GET_SETTINGS') return callback({ok: true, result: {
                configured: true, autoAnalyze: true, localAsrEnabled: true,
                profileId: 'reload-smoke', model: 'test'
              }});
              if (message.type === 'GET_CACHE') return callback({ok: true, result: null});
              if (message.type === 'LOCAL_ASR' && message.action === 'start') {
                return callback({ok: true, result: {
                  job_id: 'test-job', status: 'running', progress: 25, stage: 'transcribing'
                }});
              }
              if (message.type === 'LOCAL_ASR' && message.action === 'poll') {
                throw new Error('Extension context invalidated.');
              }
              callback({ok: true, result: null});
            }
          }};
        """)
        reload_page.goto(f"https://www.bilibili.com/video/{reload_bvid}/")
        reload_page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
        reload_page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))
        reload_page.locator(".bili-ai-status:has-text('扩展连接已失效')").wait_for(
            state="attached", timeout=10000)
        reload_page.locator(".bili-ai-badge").click()
        assert "本地语音转写未完成" not in reload_page.locator(".bili-ai-status").inner_text()
        assert reload_page.locator(".bili-ai-analyze").inner_text() == "刷新页面继续"
        with reload_page.expect_navigation(wait_until="domcontentloaded"):
            reload_page.locator(".bili-ai-analyze").click()
        assert reload_page.evaluate("performance.getEntriesByType('navigation')[0].type") == "reload"
        reload_page.close()

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
