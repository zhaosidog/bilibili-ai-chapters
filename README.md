# AI 视频章节：B站与 YouTube

一个 Chrome / Edge Manifest V3 浏览器扩展：在普通 B 站和 YouTube 视频页生成中文总结与可点击的主题章节。打开面板还能查看随播放高亮的字幕，点击章节或字幕都会跳到对应位置，也可以下载带时间轴的字幕。

## 安装扩展

1. 打开 Chrome 的 `chrome://extensions` 或 Edge 的 `edge://extensions`。
2. 如果使用压缩包，先解压。打开“开发者模式”，选择“加载已解压的扩展程序”，选中包含 `manifest.json` 的目录。
3. 打开扩展设置，选择智谱 GLM、阿里云百炼千问、DeepSeek 或其他兼容 Chat Completions 的服务，填写对应平台的 API Key 并保存。
4. 打开普通 B 站视频（`https://www.bilibili.com/video/BV...`）或 YouTube 视频（`https://www.youtube.com/watch?v=...`），点击右侧“AI 章节”。默认会自动分析，也可在设置中关闭自动分析。

## 同步字幕

面板上方的“总结与章节 / 同步字幕”按钮切换同一内容区域，每次只显示一种。选择“同步字幕”后，当前句会随视频播放高亮并自动滚动。点击任意字幕可跳转到它的开始时间；点“定位当前”可立即回到正在播放的句子。手动滚动字幕时，自动跟随会暂停 8 秒，随后继续。

同步字幕和字幕下载使用同一份 B 站或 YouTube 字幕，必要时可使用本地语音转写；这两项功能不要求模型 API Key。总结来自缓存或关闭自动分析时，打开面板仍会单独读取字幕。若字幕明显只覆盖视频开头，会尝试已启用的本地转写；没有可靠文字时显示原因。

## 下载字幕

在视频页打开“AI 章节”，选择 `SRT` 或 `TXT`，点击“下载字幕”。SRT 保留毫秒时间码，可导入播放器；TXT 每行带播放时间，方便阅读和搜索。文件名含视频标题和平台视频 ID，B 站分 P 视频还会标记 P 序号。中文文件使用 UTF-8 编码。

下载复用当前视频已经读取的字幕或本地语音转写。即使总结来自缓存，也可以单独下载字幕；下载不调用 AI 模型，也不要求先填写模型 API Key。若字幕明显只覆盖视频开头，扩展会尝试已启用的本地语音转写；没有取得足够字幕时会显示原因，不会把明显不完整的片段当作全片字幕下载。本地语音转写需要先启动 helper。

## 模型配置

新安装默认选择国内智谱免费模型 [`glm-4.7-flash`](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash)，需自行申请 API Key。千问预设使用阿里云百炼北京地域的 [`qwen3.5-35b-a3b`](https://help.aliyun.com/zh/model-studio/qwen3-5-35b-a3b) 和兼容地址 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。阿里云[推荐业务空间专属域名](https://help.aliyun.com/zh/model-studio/beijing-access-information)；可在设置中将请求地址改为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`，用百炼控制台显示的实际 WorkspaceId 替换占位符。北京地域的 API Key 与其他地域不能混用。千问为计费模型，价格以百炼控制台为准。

DeepSeek 预设仍使用 `deepseek-flash`。模型名称、请求地址和 JSON 输出模式都可以修改。千问预设开启 JSON 输出模式时，会同时关闭思考模式，以符合[百炼的结构化输出要求](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。智谱 `glm-4.7-flash` 和 DeepSeek `deepseek-flash` 请求会关闭默认思考，避免短输出上限被思考内容占用；这是两家[智谱](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode)和[DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/)官方支持的参数。已有用户保存的模型设置不会被新默认值覆盖。服务需兼容 OpenAI Chat Completions 的 `model/messages/stream` 请求与 `choices[0].message.content` 回复。

## 无字幕视频

扩展会先读取当前视频可用的 B 站或 YouTube 字幕。没有可读取字幕时，可选用 [`helper/README.md`](helper/README.md) 中的本地语音转写服务。它需要 Python、`ffmpeg`、`yt-dlp` 和 `faster-whisper`，在 `127.0.0.1:8765` 运行。扩展会轮询转写进度，再把文字交给配置的模型生成总结。

支持 B 站普通字幕与 AI 字幕，以及 YouTube 普通字幕与自动字幕。YouTube 字幕读取依赖其网页播放器使用的接口，该接口可能变化；遇到空字幕时扩展会尝试其他可用字幕轨道，再按设置尝试本地转写。更新扩展文件后，请在浏览器的扩展管理页点击本扩展的“重新加载”，再刷新视频页。

如果安装的是此前解压的副本，GitHub 源码更新不会自动替换那份文件。请先用新版文件覆盖 Chrome 加载的目录，再点“重新加载”，并确认扩展卡片显示版本 `0.2.0`。从源码生成安装包可运行 `python scripts/package_extension.py`，输出到 `dist/bilibili-ai-chapters.zip`。

如果扩展在本地转写过程中被更新或重新加载，旧视频页会失去扩展连接。面板会提供“刷新页面继续”按钮；helper 内正在运行的转写会继续，刷新后插件会接续同一任务或读取已完成的缓存。

长视频会先逐段提炼，再额外调用一次模型整合全片。面板会显示已完成的步骤数、当前步骤和已等待时间；完成第一段后，会根据最近几次模型请求的耗时显示粗略剩余时间。模型响应速度波动时，估计会调整或暂时隐藏。

扩展会检查字幕时间是否覆盖视频的主要部分，以及生成的章节是否覆盖足够的播放范围。明显不完整的字幕会改用已启用的本地转写；若无法取得完整文字，或模型只为长视频开头生成章节，面板会说明原因并丢弃该结果。旧缓存中的此类异常章节也不会继续显示。时间覆盖检查能拦截明显的错配，但不能保证识别所有字幕内容错误；遇到提示时可对照其中显示的字幕首句检查来源。

给出的示例 `BV1dRYP6oEtB` 时长约 94 分钟。匿名访问时，B 站接口没有返回字幕或现成章节，所以首次分析通常需要登录后可见的字幕，或运行本地转写服务。转写速度取决于本机硬件，长视频可能需要较久。付费、受地区或权限限制的视频，不保证能下载音轨进行本地转写。

## 数据与限制

- 字幕或转写文本会发送到你设置的模型 API；API Key 保存在本机的 `chrome.storage.local`，浏览器扩展存储不加密。扩展阻止内容脚本读取该存储，模型请求只在扩展后台发送。
- 成功的总结按视频分 P 与模型配置缓存。点“生成总结与章节”会重新分析。
- B 站和 YouTube 的字幕及视频信息来自各自网页使用的接口，网站改版后可能需要更新扩展。
- 当前支持 B 站普通 `/video/BV...` 与 YouTube 普通 `/watch?v=...` 视频页；番剧、Shorts、直播和嵌入播放器暂不在此版本范围内。

## 开发验证

无需构建工具。运行 `node --test tests/*.test.js` 检查解析、时间、权限及模型请求。运行 `python -m unittest discover -s helper/tests` 检查本地转写服务的请求处理。
