# B站 AI 视频章节

一个 Chrome / Edge Manifest V3 浏览器扩展：在普通 B 站视频页生成中文总结和可点击的主题章节。点击章节时间会直接跳到视频对应位置。

## 安装扩展

1. 打开 Chrome 的 `chrome://extensions` 或 Edge 的 `edge://extensions`。
2. 如果使用压缩包，先解压。打开“开发者模式”，选择“加载已解压的扩展程序”，选中包含 `manifest.json` 的目录。
3. 打开扩展设置，选择智谱 GLM、阿里云百炼千问、DeepSeek 或其他兼容 Chat Completions 的服务，填写对应平台的 API Key 并保存。
4. 打开任意普通 B 站视频 URL（`https://www.bilibili.com/video/BV...`），点击右侧“AI 章节”。默认会自动分析，也可在设置中关闭自动分析。

新安装默认选择国内智谱免费模型 [`glm-4.7-flash`](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash)，需自行申请 API Key。千问预设使用阿里云百炼北京地域的 [`qwen3.5-35b-a3b`](https://help.aliyun.com/zh/model-studio/qwen3-5-35b-a3b) 和兼容地址 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。阿里云[推荐业务空间专属域名](https://help.aliyun.com/zh/model-studio/beijing-access-information)；可在设置中将请求地址改为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`，用百炼控制台显示的实际 WorkspaceId 替换占位符。北京地域的 API Key 与其他地域不能混用。千问为计费模型，价格以百炼控制台为准。

DeepSeek 预设仍使用 `deepseek-flash`。模型名称、请求地址和 JSON 输出模式都可以修改。千问预设开启 JSON 输出模式时，会同时关闭思考模式，以符合[百炼的结构化输出要求](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。智谱 `glm-4.7-flash` 和 DeepSeek `deepseek-flash` 请求会关闭默认思考，避免短输出上限被思考内容占用；这是两家[智谱](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode)和[DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/)官方支持的参数。已有用户保存的模型设置不会被新默认值覆盖。服务需兼容 OpenAI Chat Completions 的 `model/messages/stream` 请求与 `choices[0].message.content` 回复。

## 无字幕视频

扩展会先用浏览器现有的 B 站登录状态读取字幕。没有可读取字幕时，可选用 [`helper/README.md`](helper/README.md) 中的本地语音转写服务。它需要 Python、`ffmpeg`、`yt-dlp` 和 `faster-whisper`，在 `127.0.0.1:8765` 运行。扩展会轮询转写进度，再把文字交给配置的模型生成总结。

普通字幕与 B 站 AI 字幕均可读取。更新扩展文件后，请在浏览器的扩展管理页点击本扩展的“重新加载”，再刷新视频页。

如果扩展在本地转写过程中被更新或重新加载，旧视频页会失去扩展连接。面板会提供“刷新页面继续”按钮；helper 内正在运行的转写会继续，刷新后插件会接续同一任务或读取已完成的缓存。

长视频会先逐段提炼，再额外调用一次模型整合全片。面板会显示已完成的步骤数、当前步骤和已等待时间；完成第一段后，会根据最近几次模型请求的耗时显示粗略剩余时间。模型响应速度波动时，估计会调整或暂时隐藏。

扩展会检查字幕时间是否覆盖视频的主要部分，以及生成的章节是否覆盖足够的播放范围。明显不完整的 B 站字幕会改用已启用的本地转写；若无法取得完整文字，或模型只为长视频开头生成章节，面板会说明原因并丢弃该结果。旧缓存中的此类异常章节也不会继续显示。时间覆盖检查能拦截明显的错配，但不能保证识别所有字幕内容错误；遇到提示时可对照其中显示的字幕首句检查来源。

给出的示例 `BV1dRYP6oEtB` 时长约 94 分钟。匿名访问时，B 站接口没有返回字幕或现成章节，所以首次分析通常需要登录后可见的字幕，或运行本地转写服务。转写速度取决于本机硬件，长视频可能需要较久。付费、受地区或权限限制的视频，不保证能下载音轨进行本地转写。

## 数据与限制

- 字幕或转写文本会发送到你设置的模型 API；API Key 保存在本机的 `chrome.storage.local`，浏览器扩展存储不加密。扩展阻止内容脚本读取该存储，模型请求只在扩展后台发送。
- 成功的总结按视频分 P 与模型配置缓存。点“生成总结与章节”会重新分析。
- B 站字幕和视频元数据接口属于网站接口，未来如有变更，扩展可能需要更新。
- 当前支持普通 `/video/BV...` 视频页；番剧播放页与直播页不在此版本范围内。

## 开发验证

无需构建工具。运行 `node --test tests/*.test.js` 检查解析、时间、权限及模型请求。运行 `python -m unittest discover -s helper/tests` 检查本地转写服务的请求处理。
