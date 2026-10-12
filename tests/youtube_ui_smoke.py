"""Isolated YouTube UI smoke test. Requires Python Playwright and Chrome."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIRST_ID = "AbCdEfGhI12"
NEXT_ID = "ZyXwVuTsR98"
API_KEY = "AIzaSyYoutubeSmokeKey1234567890"


def player_response(video_id, title, with_captions=True, caption_base_url=None):
    response = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {
            "videoId": video_id,
            "title": title,
            "lengthSeconds": "100",
        },
    }
    if with_captions:
        response["captions"] = {"playerCaptionsTracklistRenderer": {
            "captionTracks": [{
                "baseUrl": caption_base_url or
                           f"https://www.youtube.com/api/timedtext?v={video_id}&lang=en&kind=asr",
                "languageCode": "en",
                "name": {"simpleText": "English (auto-generated)"},
                "kind": "asr",
            }],
        }}
    return response


def watch_html(response, api_key=False):
    title = response["videoDetails"]["title"]
    encoded = json.dumps(response, ensure_ascii=False)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title} - YouTube</title>"
        f"<script id='yt-player-response'>var ytInitialPlayerResponse = {encoded};</script>"
        + (f'<script>ytcfg.set({{"INNERTUBE_API_KEY":"{API_KEY}"}});</script>'
           if api_key else "") +
        "</head><body><ytd-watch-flexy>"
        f"<h1>{title}</h1>"
        "<video style='width:900px;height:500px'></video>"
        "</ytd-watch-flexy></body></html>"
    )


def caption_data(video_id):
    second_line = "第二段字幕内容" if video_id == NEXT_ID else "第一章主题内容"
    return {"events": [
        {"tStartMs": 0, "dDurationMs": 4000, "segs": [{"utf8": "视频开场"}]},
        {"tStartMs": 5000, "dDurationMs": 93000, "segs": [{"utf8": second_line}]},
    ]}


def runtime_script(cached=None):
    return """
      window.__modelCalls = 0;
      window.__cacheWrites = [];
      window.__modelPrompts = [];
      window.chrome = {runtime: {
        lastError: null,
        onMessage: {addListener: () => {}},
        sendMessage(message, callback) {
          if (message.type === 'GET_SETTINGS') return callback({ok: true, result: {
            configured: true, autoAnalyze: true, localAsrEnabled: false,
            profileId: 'youtube-smoke', model: 'test'
          }});
          if (message.type === 'GET_CACHE') return callback({ok: true, result: CACHED_RESULT});
          if (message.type === 'MODEL_CALL') {
            window.__modelCalls++;
            const prompt = message.messages[1].content;
            window.__modelPrompts.push(prompt);
            const next = prompt.includes('第二个 YouTube 视频');
            return callback({ok: true, result: {content: JSON.stringify({
              summary: next ? '第二段总结' : 'YouTube 视频总结',
              chapters: [{start: 5, title: next ? '新视频章节' : '第一章', summary: '章节内容'}]
            })}});
          }
          if (message.type === 'PUT_CACHE') window.__cacheWrites.push(message);
          callback({ok: true, result: null});
        }
      }};
    """.replace("CACHED_RESULT", json.dumps(cached, ensure_ascii=False))


def install_fixture(page, captions=True, cached=None, api_key=True,
                    caption_base_url=None, panel_captions=False):
    network = {"player_calls": [], "caption_fetches": 0, "panel_calls": []}

    def watch(route):
        video_id = route.request.url.split("v=")[-1].split("&")[0]
        title = "第二个 YouTube 视频" if video_id == NEXT_ID else "测试 YouTube 视频"
        route.fulfill(status=200, content_type="text/html",
                      body=watch_html(player_response(video_id, title, captions,
                                                      caption_base_url), api_key))

    def player(route):
        request = route.request.post_data_json
        network["player_calls"].append(request)
        video_id = request["videoId"]
        title = "第二个 YouTube 视频" if video_id == NEXT_ID else "测试 YouTube 视频"
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(player_response(video_id, title, captions,
                                                      caption_base_url), ensure_ascii=False))

    def timedtext(route):
        network["caption_fetches"] += 1
        video_id = route.request.url.split("v=")[-1].split("&")[0]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(caption_data(video_id), ensure_ascii=False))

    def panel(route):
        network["panel_calls"].append(route.request.post_data_json)
        segments = [{"transcriptSegmentViewModel": {"timestamp": "0:00", "simpleText": "转写文稿开头"}},
                    {"transcriptSegmentViewModel": {"timestamp": "1:35", "simpleText": "转写文稿结尾"}}] \
            if panel_captions else []
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"content": {"items": segments}}, ensure_ascii=False))

    page.route("https://www.youtube.com/watch?*", watch)
    page.route("https://www.youtube.com/youtubei/v1/player?*", player)
    page.route("https://www.youtube.com/youtubei/v1/get_panel", panel)
    page.route("https://www.youtube.com/api/timedtext?*", timedtext)
    page.add_init_script(runtime_script(cached))
    return network


def inject_extension(page):
    page.evaluate("""() => {
      const video = document.querySelector('video');
      window.__seek = 0;
      Object.defineProperty(video, 'duration', {value: 100, configurable: true});
      Object.defineProperty(video, 'currentTime', {
        get() { return window.__seek; },
        set(value) { window.__seek = value; }, configurable: true
      });
    }""")
    page.add_style_tag(content=(ROOT / "content.css").read_text(encoding="utf-8"))
    page.add_script_tag(content=(ROOT / "lib/core.js").read_text(encoding="utf-8"))
    page.add_script_tag(content=(ROOT / "content.js").read_text(encoding="utf-8"))


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        network = install_fixture(page)
        page.goto(f"https://www.youtube.com/watch?v={FIRST_ID}")
        inject_extension(page)
        page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=10000)
        page.locator(".bili-ai-badge").click()
        assert page.locator(".bili-ai-summary").inner_text() == "YouTube 视频总结"
        assert page.locator(".bili-ai-chapter-title").inner_text() == "第一章"
        assert page.evaluate("window.__modelCalls") == 1
        assert len(network["player_calls"]) == 1
        assert network["player_calls"][0]["videoId"] == FIRST_ID
        assert network["player_calls"][0]["context"]["client"]["clientName"] == "VISIONOS"
        assert "第一章主题内容" in page.evaluate("window.__modelPrompts[0]")
        assert not page.locator(".bili-ai-transcript-column").is_visible()

        page.locator(".bili-ai-chapter").click()
        assert page.evaluate("window.__seek") == 5
        page.locator(".bili-ai-view-tab[data-view='transcript']").click()
        assert not page.locator(".bili-ai-main-column").is_visible()
        assert page.locator(".bili-ai-transcript-line").count() == 2
        page.locator(".bili-ai-transcript-line[data-index='1'][data-active='true']").wait_for()
        page.locator(".bili-ai-transcript-line[data-index='0']").click()
        assert page.evaluate("window.__seek") == 0
        with page.expect_download() as download_event:
            page.locator(".bili-ai-download").click()
        download = download_event.value
        assert download.suggested_filename.endswith(f"_{FIRST_ID}.srt")
        srt = Path(download.path()).read_bytes().decode("utf-8-sig")
        assert "00:00:05,000 --> 00:01:38,000" in srt
        assert "第一章主题内容" in srt
        page.locator(".bili-ai-download-format").select_option("txt")
        with page.expect_download() as txt_event:
            page.locator(".bili-ai-download").click()
        assert Path(txt_event.value.path()).read_bytes().decode("utf-8-sig") == (
            "[0:00] 视频开场\r\n[0:05] 第一章主题内容\r\n")

        # A YouTube SPA changes the watch URL while the original inline player
        # response can remain stale. The new video must come from its own ID.
        page.evaluate("history.pushState(null, '', '/watch?v=ZyXwVuTsR98')")
        page.locator(".bili-ai-transcript-line:has-text('第二段字幕内容')").wait_for(timeout=10000)
        assert page.locator(".bili-ai-transcript-line:has-text('第一章主题内容')").count() == 0
        page.locator(".bili-ai-view-tab[data-view='summary']").click()
        page.locator(".bili-ai-summary:has-text('第二段总结')").wait_for(timeout=10000)
        assert page.locator(".bili-ai-chapter-title").inner_text() == "新视频章节"
        assert page.evaluate("window.__modelCalls") == 2
        assert [call["videoId"] for call in network["player_calls"]] == [FIRST_ID, NEXT_ID]
        page.wait_for_function("window.__cacheWrites.length === 2")
        cache_keys = page.evaluate("window.__cacheWrites.map(message => message.key)")
        assert cache_keys[0] != cache_keys[1]
        assert FIRST_ID in cache_keys[0] and NEXT_ID in cache_keys[1]
        page.evaluate("history.pushState(null, '', '/')")
        page.wait_for_function("document.querySelector('#bili-ai-chapters-root').hidden")
        assert not page.locator(".bili-ai-badge").is_visible()
        assert not page.locator(".bili-ai-panel").is_visible()
        page.evaluate(f"history.pushState(null, '', '/watch?v={FIRST_ID}')")
        page.wait_for_function("!document.querySelector('#bili-ai-chapters-root').hidden")
        page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=10000)
        page.locator(".bili-ai-badge").click()
        page.locator(".bili-ai-summary:has-text('YouTube 视频总结')").wait_for(timeout=10000)
        page.close()

        cached = {"title": "测试 YouTube 视频", "source": "YouTube 字幕（English）",
                  "result": {"summary": "缓存的总结", "chapters": [{"start": 5, "title": "缓存章节"}]}}
        cached_page = browser.new_page(accept_downloads=True)
        install_fixture(cached_page, cached=cached, api_key=False)
        cached_page.goto(f"https://www.youtube.com/watch?v={FIRST_ID}")
        inject_extension(cached_page)
        cached_page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=10000)
        cached_page.locator(".bili-ai-badge").click()
        assert cached_page.locator(".bili-ai-summary").inner_text() == "缓存的总结"
        assert cached_page.evaluate("window.__modelCalls") == 0
        cached_page.locator(".bili-ai-view-tab[data-view='transcript']").click()
        cached_page.locator(".bili-ai-transcript-line").first.wait_for(timeout=10000)
        assert cached_page.locator(".bili-ai-transcript-line").count() == 2
        cached_page.close()

        no_caption_page = browser.new_page()
        install_fixture(no_caption_page, captions=False, api_key=False)
        no_caption_page.goto(f"https://www.youtube.com/watch?v={FIRST_ID}")
        inject_extension(no_caption_page)
        no_caption_page.locator(".bili-ai-badge[data-kind='error']").wait_for(timeout=10000)
        assert no_caption_page.evaluate("window.__modelCalls") == 0
        no_caption_page.locator(".bili-ai-badge").click()
        assert no_caption_page.locator(".bili-ai-summary").inner_text() == ""
        assert "字幕" in no_caption_page.locator(".bili-ai-status").inner_text()
        no_caption_page.close()

        invalid_track_page = browser.new_page()
        network = install_fixture(invalid_track_page,
                                  caption_base_url="https://www.youtube.com/api/timedtext"
                                                   "?v=WrongVideo1&lang=en",
                                  api_key=False)
        invalid_track_page.goto(f"https://www.youtube.com/watch?v={FIRST_ID}")
        inject_extension(invalid_track_page)
        invalid_track_page.locator(".bili-ai-badge[data-kind='error']").wait_for(timeout=10000)
        assert "字幕地址不属于当前 YouTube 视频" in (
            invalid_track_page.locator(".bili-ai-status").inner_text())
        assert invalid_track_page.evaluate("window.__modelCalls") == 0
        assert network["caption_fetches"] == 0
        invalid_track_page.close()

        panel_page = browser.new_page()
        panel_network = install_fixture(panel_page, captions=False, api_key=False, panel_captions=True)
        panel_page.goto(f"https://www.youtube.com/watch?v={FIRST_ID}")
        inject_extension(panel_page)
        panel_page.locator(".bili-ai-badge[data-kind='ready']").wait_for(timeout=10000)
        assert len(panel_network["panel_calls"]) == 1
        panel_page.locator(".bili-ai-badge").click()
        panel_page.locator(".bili-ai-view-tab[data-view='transcript']").click()
        assert panel_page.locator(".bili-ai-transcript-line").count() == 2
        assert "转写文稿结尾" in panel_page.locator(".bili-ai-transcript-line").last.inner_text()
        panel_page.close()
        browser.close()


if __name__ == "__main__":
    run()
    print("YouTube UI smoke test passed")
