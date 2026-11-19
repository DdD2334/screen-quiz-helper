# screen-quiz-helper v2 — 屏幕答题助手（学习练习辅助）

Windows 常驻小工具：按全局热键截屏 → 发给任意 OpenAI 兼容协议的视觉大模型 → 识别画面中的题目并给出**答案 / 置信度 / 理由 / 题型** → 置顶悬浮窗逐题展示、可复制。

> 定位：**学习与练习辅助**。答案需人工核对后使用，本工具不自动填答、不做周期性截屏（仅热键触发）、不做对任何软件隐藏窗口。

## 功能清单（v2 实况）

- 整屏截屏答题（光标所在显示器）+ **框选截屏**（冻结屏幕遮罩，只答框内题）
- 真 SSE 流式输出，悬浮窗打字机预览
- 结构化提示词 + JSON 模式 + 三级解析兜底 + 解析失败自动修复请求
- 图片自动压缩缩放（长边 2048 / JPEG），请求快且省
- 低置信度整卡标黄"建议人工核对"；可选自动带图复核（默认关，省额度）
- latest-wins：连按热键自动取消旧请求，只保留最新结果
- 429 限流退避重试 + 最小调用间隔倒计时（状态条可见）
- 应用内设置向导：8 家预设、测试连接、热键录制，全程不用手改 JSON
- 历史回看（◀ 1/N ▶）、仅答案速览复制（`1.B  2.ACD  3.对`）
- **答案缓存秒回**：同一静止画面重复截屏直接返回上次结果，不调 API 不耗额度（sha256 精确匹配，可在设置里关闭/清空）
- **错题收藏**：每题"收藏"按钮存入 favorites.json；"导出复习笔记"生成按日期分组的 Markdown
- **追问讲解**：每题"追问"按钮让模型详细讲解知识点与解题步骤，讲解卡插在题卡下方
- 日志文件（key 自动脱敏）、单实例保护、托盘常驻、开机自启开关
- 源码一键启动 + PyInstaller 单文件 exe 均可运行

## 安装三步走

```powershell
# 1. 安装依赖（Python 3.11+，推荐 3.13）
pip install -r requirements.txt

# 2. 启动
python main.py        # 或双击 start.bat

# 3. 首次启动自动弹设置向导：选服务商 → 填 API key → 点"测试连接" → 保存
```

之后打开任意含题目的窗口，按热键即可。

## 热键表

| 热键 | 功能 |
|---|---|
| `Shift+Alt+S` | 整屏截屏答题（光标所在屏） |
| `Shift+Alt+D` | 框选截屏答题（拖动框选，Esc 取消） |
| `Shift+Alt+C` | 复制当前批答案速览串 |
| `Shift+Alt+H` | 显示/隐藏悬浮窗 |

热键可在 设置 → 热键 页录制修改。托盘：单击显示/隐藏，双击打开设置，右键菜单退出。

## 内置预设（8 家）

| 预设 | api_base | 默认模型 | 最小间隔 | JSON 模式 |
|---|---|---|---|---|
| Agentic（Agnes） | api.agentic.example.com/v1 | agnes-3.0-flash | 45s | 否 |
| OpenAI | api.openai.com/v1 | gpt-4o | 3s | 是 |
| Azure OpenAI | YOUR_RESOURCE.openai.azure.com/openai | gpt-4o | 5s | 否 |
| 通义千问 VL | dashscope.aliyuncs.com/compatible-mode/v1 | qwen-vl-max | 10s | 是 |
| Gemini | generativelanguage.googleapis.com/v1beta/openai | gemini-1.5-flash | 10s | 是 |
| Moonshot（Kimi） | api.moonshot.cn/v1 | moonshot-v1-8k | 10s | 否 |
| Ollama（本地） | localhost:11434/v1 | llava | 1s | 否 |
| OpenRouter | openrouter.ai/api/v1 | openai/gpt-4o | 5s | 是 |

选预设自动带出 api_base / 模型名 / 最小间隔；任何其它 OpenAI 兼容服务选"自定义"填三个字段即可。
Azure 的 `api_version` 在预设 extra 里，自动拼为 URL query。

**限流说明**：`最小调用间隔` 从上次请求完成时刻起算，等待期间状态条倒计时；429 时按 Retry-After（无则 1/2/4s）退避重试最多 3 次。免费额度服务商请把间隔调大。

## 常见问题

| 现象 | 处理 |
|---|---|
| 失败: API key 无效或未填写（401） | 设置 → 模型页检查 key，点测试连接 |
| 失败: api_base 或模型名不对（404） | 核对 api_base 结尾（多数要带 /v1）与模型名 |
| 限流中，N 秒后重试…（429） | 正常退避；频繁出现请调大最小间隔 |
| 模型响应超时 | 设置 → 模型页调大超时；大图可减小"图片长边上限" |
| 热键无效 | keyboard 库需要权限：以管理员身份运行；或检查热键冲突 |
| 框选坐标偏移 | 确认显示缩放设置；工具已按物理像素换算，多屏混合 DPI 也支持 |
| 悬浮窗没出现 | float_mode=出答案时弹出：按热键出答案/错误才弹；托盘单击可手动显示 |
| exe 无报错窗口 | 看 exe 旁 `logs\app.log`（key 已脱敏） |

## 打包 exe

```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

产物在 `dist\`：`screen-quiz-helper.exe`（约 38MB）+ `config.json` + `start-exe.bat`。
把 dist 拷到任意干净文件夹双击 exe 即可；首次运行在 exe 旁自动生成配置并弹向导。

打包由 `pack.spec` 定义并裁剪：只带 Qt Core/Gui/Widgets/Network 与中文翻译，
去掉 QtQml/Quick/Pdf/Svg/虚拟键盘、软件 OpenGL（opengl32sw，19.7MB）和 313 个多余语言包。
要分享 exe 给别人，先删掉 `dist\config.json`（里面有你的 API key，删了对方首次启动会自动生成）。

> 注意：单文件 exe 启动时要把自身解压到临时目录。若在受管控目录（如本工程的 `dati` 沙箱目录）
> 里直接双击，部分环境会拦截解压并报 `Could not create temporary directory!`。
> 把 exe 拷到桌面等普通文件夹再运行即可；用 `start.bat` 跑源码不受此影响。

> 打包踩坑：PATH 上若装有 MySQL 8（自带 OpenSSL 3.0），PyInstaller 会把它的
> `libssl-3-x64.dll` / `libcrypto-3-x64.dll` 解析进包，与 Python 3.13 的 `_ssl`（OpenSSL 3.5）
> 不兼容，运行时报 `DLL load failed while importing _ssl: 找不到指定的程序`。
> `pack.spec` 已强制改回 Python 自带 OpenSSL，换机器打包也无需手工处理。

## 测试

```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q     # 全部离线，不依赖网络/真实 key/显示器
python probe_agentic.py       # 离线自检
```

## 可选 server 通道

主程序不依赖 server.py。需要 HTTP 接口时：

```powershell
pip install -r requirements-server.txt
python server.py              # /health /init /ask（非流式）
```

## 已知限制

- 框选只在光标所在单屏内进行
- server.py 的 /ask 为非流式
- 低置信度自动复核默认关闭（开启会多耗一次额度）