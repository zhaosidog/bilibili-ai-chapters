# AI 视频章节：B 站与 YouTube

这是一个适用于 Chrome 和 Edge 的浏览器扩展。在 B 站或 YouTube 普通视频页，它可以读取字幕，生成中文视频总结和可点击的章节目录；也可以同步高亮字幕、下载字幕或下载视频。点击章节时间或字幕行，播放器会跳到对应位置。

仓库地址：<https://github.com/zhaosidog/bilibili-ai-chapters>

## 开始前：你需要哪些东西？

| 想使用的功能 | 需要准备 |
| --- | --- |
| 查看同步字幕、下载 SRT/TXT 字幕 | 安装扩展；视频本身有可读取的字幕时，无需模型 API Key |
| 生成总结和章节 | 安装扩展；配置一个兼容 Chat Completions 的模型 API 和自己的 API Key；视频需有足够的字幕或转写文字 |
| 为无字幕视频生成文字 | 运行可选的本地 `helper`；它下载音轨并在本机转写 |
| 下载 MP4 视频 | 运行可选的本地 `helper`；无需模型 API Key |

建议第一次先找一个**已有字幕的普通视频**试用。这样只需安装扩展并配置模型，不必先安装 Python 或 FFmpeg。支持的视频地址形如 `https://www.bilibili.com/video/BV...` 和 `https://www.youtube.com/watch?v=...`。

## 1. 下载并安装扩展

1. [下载仓库 ZIP](https://github.com/zhaosidog/bilibili-ai-chapters/archive/refs/heads/main.zip) 并解压，或用 Git 克隆仓库。请把解压后的文件夹留在固定位置，浏览器会从该目录加载扩展。
2. 在 Chrome 打开 `chrome://extensions`，或在 Edge 打开 `edge://extensions`。
3. 打开右上角的“开发者模式”，点击“加载已解压的扩展程序”。
4. 选择**直接包含 `manifest.json`** 的文件夹（GitHub ZIP 解压后通常名为 `bilibili-ai-chapters-main`）。不要选择 ZIP 文件，也不要选择外层下载目录。
5. 扩展列表应出现“AI 视频章节：B站与 YouTube”。如果视频页此前已经打开，请刷新视频页。

扩展按 Chrome/Edge 的跨平台接口编写，可在 Mac 和 Windows 上尝试；不支持 Safari。Mac 上的扩展和本地 `helper` 尚未做实机验证，见下文的手动启动方式。

## 2. 配置模型（生成总结和章节时需要）

1. 打开一个受支持的视频页，点击页面右侧的“AI 章节”，再点面板右上角的 **⚙**。
2. 选择模型服务，填写该服务提供的 **API Key**。预设会填入请求地址和模型名称；使用自定义服务时，请填写兼容 OpenAI Chat Completions 的完整请求地址和模型名称。
3. 点击“保存设置”。浏览器若弹出访问该模型接口域名的权限请求，请点“允许”；否则无法保存这项模型配置。可以再点击“测试模型连接”；测试会发送一次简短的模型请求，服务商可能计费。
4. 默认勾选“打开视频时自动总结”。若想自己决定何时调用模型，请取消勾选，之后在视频面板点“生成总结与章节”。

设置页提供智谱 GLM、阿里云百炼千问、DeepSeek、Z.AI GLM 和自定义接口。不同平台的 Key、地域和计费规则由对应服务商决定；千问北京地域的预设地址与其他地域的 Key 不一定通用。模型接口需要 HTTPS，本机模型接口可使用 `http://127.0.0.1` 或 `http://localhost`。API Key 保存在当前浏览器的本机扩展存储中，**不会写进这个 GitHub 仓库**。

只看同步字幕或下载已有字幕时，不需要配置模型 Key。若面板提示设置 API Key，该提示针对总结功能。

## 3. 在视频页使用

打开普通 B 站或 YouTube 视频后，点击页面右侧“AI 章节”按钮，或点击浏览器工具栏中的扩展图标。面板顶部显示当前视频标题和处理状态。

| 操作 | 用法 |
| --- | --- |
| 总结与章节 | 查看自动生成的结果，或点“生成总结与章节”手动重新生成。点击章节时间或标题跳转到该段。手动重新生成会再次调用模型。 |
| 同步字幕 | 点“同步字幕”标签。当前句会随播放高亮并滚动；点击某句跳转到它的开始时间，“定位当前”回到正在播放的句子。手动滚动后自动跟随会暂停约 8 秒。 |
| 下载字幕 | 在面板选择 `SRT` 或 `TXT`，点“下载字幕”。文件由浏览器保存到其下载位置，不调用模型。 |
| 下载视频 | 先启动下文的本地 `helper`，再点“下载视频”。完成后可在 `~/Downloads/AI视频章节` 找到 MP4。 |

扩展会优先读取网站字幕。若字幕只有视频开头一小段，或完全没有字幕，并且已启用本地转写，就会尝试使用 `helper`。字幕未达到最低时间覆盖要求时，扩展会说明原因并拒绝用这段文字生成总结；覆盖检查仍可能漏掉内容错配或中间缺失。长视频会分段处理，可能调用模型多次并花费较长时间。

## 4. 可选：启动本地 helper

**什么时候需要？** 无可读字幕或字幕明显不完整的视频需要它来转写；“下载视频”也需要它。视频有完整可读字幕时，总结、同步字幕和字幕下载不需要启动它。

先安装 Python **3.11 或 3.12** 与 [FFmpeg](https://ffmpeg.org/download.html)。在终端确认 Python 和 `ffmpeg -version` 可运行。若要让 helper 处理 **YouTube 无字幕视频或下载 YouTube 视频**，还需安装 [Deno](https://docs.deno.com/runtime/getting_started/installation/) 并确认 `deno --version` 可运行；[yt-dlp 的 YouTube 支持说明](https://github.com/yt-dlp/yt-dlp/wiki/EJS)列出了这项依赖。只读取 YouTube 网站现成字幕时不需要 Deno。

下面的命令都从**仓库根目录**开始；依赖安装只需做一次，之后直接运行最后一行启动。使用扩展期间要让该终端保持运行。

### Windows（PowerShell）

```powershell
cd helper
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py
```

之后也可在 `helper` 目录运行 `.\start.ps1`。如果 `python` 指向 Anaconda 等环境而转写模型无法加载，请改用标准 CPython 3.11/3.12 创建虚拟环境。

### Mac（终端）

```bash
cd helper
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python server.py
```

如果安装的是 Python 3.11，把第一行命令里的 `python3.12` 改成 `python3.11`。Mac 不使用 `start.ps1`；再次启动时，进入 `helper` 目录后运行 `./.venv/bin/python server.py`。转写默认在 CPU 上运行；第一次使用会下载语音模型，长视频可能很慢。Mac 本地流程尚未做实机验证，遇到依赖安装问题请附上终端错误信息。

Mac 用户如果已经安装 Homebrew，可用 `brew install ffmpeg deno` 准备这两个命令行工具；没有 Homebrew 时按上面的 FFmpeg、Deno 官方安装说明操作。只处理 B 站视频时不要求安装 Deno。

**确认已启动：**终端应显示 `Video helper listening on http://127.0.0.1:8765`。用浏览器打开 <http://127.0.0.1:8765/health>，应看到 `"status": "ok"` 和 `"videoDownload": true`。若浏览器提示无法连接，请检查终端是否仍在运行。更新仓库中的 `helper/server.py` 后，需要停止旧进程并重启。

更多依赖、模型参数和接口说明见 [helper/README.md](helper/README.md)。

## 文件保存在哪里？

| 内容 | 位置 |
| --- | --- |
| 下载的字幕 | 浏览器设置的下载文件夹；文件名含标题和视频 ID |
| 下载的 MP4 | Mac：`~/Downloads/AI视频章节`；Windows：`%USERPROFILE%\Downloads\AI视频章节` |
| 本地转写缓存 | Mac：`~/.cache/bili-ai-summary/asr-cache`；Windows：`%LOCALAPPDATA%\bili-ai-summary\asr-cache` |
| 总结缓存和 API Key | 当前浏览器的 `chrome.storage.local`，不会上传到此仓库 |

本地转写缓存是未加密的 JSON，**不会自动过期**；删除上述 `asr-cache` 目录可清除它。视频文件只保存在本机，不会发送给模型；生成总结时，视频标题与字幕或转写文本会发送给你配置的模型服务。扩展面板展示的字幕和总结也可能被当前视频网站的页面脚本读取；请谨慎处理包含敏感内容的视频。关闭自动总结可避免打开视频后立即产生模型请求。

## 更新和常见问题

更新扩展：下载新版源码，替换浏览器正在加载的文件夹内容；然后在扩展管理页点击本扩展的“重新加载”，最后刷新视频页。更新本地 `helper` 后还要重启终端里的服务。仅在 GitHub 上看到新版本，不会自动更新已加载的本地文件。

| 看到的情况 | 处理方法 |
| --- | --- |
| “请先设置模型 API 与 Key” | 打开面板右上角 ⚙，填入自己的 Key 并保存；只用字幕功能可忽略该总结提示。 |
| “没有连接到本地语音转写服务”或视频下载服务 | 按第 4 节启动 `helper`，打开 `/health` 检查，再刷新视频页。 |
| “helper 不支持视频下载”或 `unknown request field` | 更新本地仓库文件，停止旧 `helper` 进程并用新版 `server.py` 重启。 |
| `Extension context invalidated`／“扩展连接已失效” | 扩展刚被更新或重新加载；刷新视频页后继续。 |
| 字幕只覆盖开头，无法生成总结 | 启用本地语音转写并启动 `helper`；若视频无法取得音轨或转写仍失败，就无法可靠总结。 |
| YouTube 首页没有视频面板 | 先打开 `/watch?v=...` 普通视频页，再点击扩展。 |
| YouTube 视频页点击图标后出现“暂时无法打开视频面板” | 检查浏览器是否允许本扩展访问 YouTube 网站，然后重新加载扩展并刷新视频页。 |

当前范围是 B 站普通 `/video/BV...` 和 YouTube 普通 `/watch?v=...` 视频。番剧、Shorts、直播和嵌入播放器尚未支持；付费、地区受限、需要额外登录或受保护的视频也可能无法转写或下载。字幕接口可能随网站改版而失效。

## 开发者

扩展是 Manifest V3，无需构建即可加载。运行 `node --test tests/*.test.js` 检查解析和后台逻辑；运行 `python -m unittest discover -s helper/tests` 检查本地服务。生成只包含扩展所需文件的 ZIP：`python scripts/package_extension.py`，输出到 `dist/bilibili-ai-chapters.zip`。
