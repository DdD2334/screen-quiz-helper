# screen-quiz-helper 全面优化实施计划（v2）

> 本文档是给「执行代码编写的模型」的完整施工图。
> 要求：严格按任务编号顺序执行；每个任务都写明了【改哪个文件】【具体怎么改】【验收标准】。
> 不需要自由发挥架构，一切以本文档为准。遇到本文档未覆盖的小细节，选择最简单、最不容易出错的实现。
> 项目根目录：`D:\Users\ff\Desktop\dati`，主工程目录：`D:\Users\ff\Desktop\dati\screen-quiz-helper`（下文所有相对路径均相对主工程目录）。
> 运行环境：Windows 11 + Python 3.13 + PowerShell 7。所有文件一律 UTF-8 编码保存。

---

## 一、项目现状与定位

### 1.1 项目是什么
一个 Windows 常驻小工具：按全局热键截屏 → 把截图发给 OpenAI 兼容协议的视觉大模型 → 模型识别画面中的题目并给出答案/置信度/理由/题型 → 在置顶悬浮窗中逐题展示、可复制。定位为**学习与练习辅助工具**（人工核对后使用，不自动填答）。

### 1.2 现有文件
| 文件 | 职责 | 现状 |
|---|---|---|
| `main.py` | 入口：UI + 热键 + 模型调用 | 有多个致命 bug |
| `capture.py` | mss 截屏 + keyboard 热键 | 有致命 bug，框选未实现 |
| `ui.py` | PySide6 悬浮窗 + 托盘 | 有致命 bug，多数配置项未生效 |
| `agentic.py` | 模型客户端 + 解析 | 有致命 bug，无提示词工程 |
| `server.py` | 可选 FastAPI 通道 | 与主流程重复，降级为可选组件 |
| `config.py` / `config.json` | 配置 | 结构混乱（预设混在 model 段里） |
| `probe_agentic.py` | 离线自检 | 可用，保留并扩充 |
| `start.bat` / `build_exe.ps1` | 启动/打包 | 有小 bug |
| `DESIGN.md` / `README.md` | 文档 | 需更新到 v2 |

根目录 `D:\Users\ff\Desktop\dati` 下的 `agentic.py、b.py、build_a1.py、build_all.py、build_ps1.txt、mk_agentic.py、mk.py、mkproj.py、t.py、t2.py、t3.py、t4.py、t5.py、test_write.py、w.py、w2.py` 全部是早期写文件实验留下的垃圾脚本（内容多为语法错误的残片），与工程无关。

### 1.3 已确认的 bug 清单（必须全部修复，后文任务会引用编号）
| 编号 | 位置 | 问题 |
|---|---|---|
| B1 | `agentic.py` `AgenticClient.ask()` 第 115 行 | 调用 `self.parse_questions(text)`，但 `parse_questions` 是模块级函数、不是类方法 → 每次请求必抛 `AttributeError`，**整个工具当前完全不可用** |
| B2 | `ui.py` `TrayIcon._make_icon()` | 使用了 `QRect` 但未 import → 启动即 `NameError` 崩溃 |
| B3 | `requirements.txt` 第 1~2 行 | 文件开头是 Python 文档字符串 `"""..."""`，pip 会报 Invalid requirement → **依赖装不上** |
| B4 | `main.py` `_on_hotkey._worker()` | 在 keyboard 工作线程里直接调用 `panel.set_questions()/set_error()` 更新 Qt 控件 → 跨线程操作 UI，随机崩溃/卡死 |
| B5 | `main.py` `_worker()` 第 22 行 | 读取 `capture._last_hotkey`，该属性从未定义 → `AttributeError` |
| B6 | `main.py` `client_factory()` | 每次按热键都 new 一个 `AgenticClient` → 最小间隔限流、单飞状态全部失效，连按必触发 429 |
| B7 | `capture.py` `capture_full()/capture_region()` | `mss.tools.to_png(img, img.size)` 参数错误，正确是 `to_png(img.rgb, img.size)` → 截屏即崩 |
| B8 | `capture.py` 末行 | `Callable = Any` 的 hack 写法，且在 `__init__` 注解中下标使用，脆弱易错 |
| B9 | `capture.py` | mss 实例在 `_ensure_sct` 中缓存后被不同线程复用；Windows 上 mss 的 GDI 资源有线程亲和性 → 偶发截屏失败 |
| B10 | `capture.py` `capture_full()` | 默认 `monitor_index=0`，mss 的 monitors[0] 是"所有显示器拼接的虚拟大屏"，与"单显示器"设计矛盾，多屏时截图巨大且答非所问 |
| B11 | `ui.py` `toggle_collapse()` | 折叠用 `setFixedSize(48,48)`，展开只调 `resize(460,300)`，min/max 约束没解除 → **折叠后永远展不开** |
| B12 | `agentic.py` `ask_stream()` | `text = self.ask(...)` 拿到的是 `list[Question]` 却按 str 生成器 yield，类型错误；且流式是假的 |
| B13 | `agentic.py` `ask()` | 提示词只有一句"识别屏幕上所有题目并回答"，**从未告诉模型输出 `===第N题===` 格式** → 解析永远走兜底分支，把整段文本当一题，这是准确率低的最大根源 |
| B14 | `agentic.py` `parse_questions()` | 只认半角冒号 `答案:`，模型常输出全角 `答案：`；不认 Markdown 加粗；理由/答案多行时丢失 |
| B15 | `config.json` | `_presets`、`_note` 混在 `model` 段内部；`extra` 字段声称透传请求体但代码从未实现（Azure 的 api_version 不生效） |
| B16 | `ui.py` | `field_visibility`、`float_mode`、`default_corner`、`show_capture_flash`、`capture_sound` 全部只读配置不实现 |
| B17 | `config.py` | exe 打包后 `Path(__file__).parent` 指向 PyInstaller 临时解包目录，找不到 exe 旁边的 config.json |
| B18 | `start.bat` | `%CMDLEVEL%` 不是真实变量，出错时窗口直接关闭看不到报错 |
| B19 | `main.py` | 防抖拒绝时抛 `CaptureError("debounce: too soon")`，UI 显示"失败: ..."，把正常防抖当错误吓用户 |
| B20 | `ui.py` `_flash_status()` | 1.5 秒后固定把状态改成"已复制"，覆盖掉期间出现的新状态 |

### 1.4 缺失的核心功能（v2 要补齐）
- 框选截屏（现在按 Shift+Alt+D 等于整屏）
- 真正的 SSE 流式输出
- 结构化提示词 + JSON 输出 + 健壮解析（准确率核心）
- 图片压缩缩放（4K 整屏 PNG base64 巨大，慢且贵）
- 应用内设置界面（现在改 key 要手改 JSON）
- 连接测试、历史回看、仅答案速览复制、请求取消（latest-wins）
- 日志文件、单实例、打包可用

---

## 二、v2 目标定义（完善后的项目宗旨）

1. **开箱即用**：装依赖 → 启动 → 弹出设置向导填 key → 测试连接 → 按热键就能用。全程不需要手改 JSON。
2. **答得准**：结构化提示词 + JSON 模式 + 三级解析兜底 + 图片预处理 + 框选聚焦 + 低置信度标黄提醒。
3. **不崩溃、不坑人**：所有错误在悬浮窗诚实显示原因；限流有倒计时；连按热键自动取消旧请求只保留最新。
4. **通用**：任何 OpenAI 兼容视觉模型改三个字段即可切换，内置 8 家预设。
5. **可交付**：源码一键启动 + PyInstaller 单文件 exe 均能跑；有离线测试套件保证回归。
6. **边界（明确不做）**：不自动填答到输入框；不做对截屏/监考软件隐藏窗口的功能；不做自动周期性偷拍（仅热键触发）；不做多模型自动 fail-over。

---

## 三、目标架构（施工蓝图）

### 3.1 模块与数据流
```
keyboard 热键线程
   │ 触发
   ▼
main.py: AppController（新增，唯一调度中心）
   │ 1. 防抖检查（不过→静默忽略+状态条提示）
   │ 2. 框选热键→先经 Bridge 信号让 UI 线程弹 RegionOverlay，拿到矩形再继续
   │ 3. capture.py 截屏（调用线程内新建 mss，用完即关）
   │ 4. image_utils.py 压缩缩放 → base64
   │ 5. 提交给 RequestManager（latest-wins：递增 generation，旧的作废）
   ▼
agentic.py: AgenticClient（全局唯一实例，启动时创建）
   │ 限流等待(状态条倒计时) → POST /chat/completions (stream=true)
   │ SSE 增量 → Bridge.partial_text(str) 信号 → UI 打字机
   │ 完成 → parsing.py 三级解析 → Bridge.questions_ready(list)
   ▼
ui.py: FloatingPanel（只在 Qt 主线程被信号槽更新）
```

### 3.2 线程铁律（写给执行模型，必须遵守）
- **任何 Qt 控件的方法只能在主线程调用。** 工作线程与 UI 之间只允许通过 `Bridge(QObject)` 的 Signal 通信。
- Bridge 定义（放 `main.py` 或新建 `bridge.py` 均可，推荐新建 `bridge.py`）：
  - `questions_ready = Signal(object)`（载荷 `list[Question]`）
  - `partial_text = Signal(str)`（流式原始文本增量）
  - `status = Signal(str, str)`（消息文本, 级别："info"/"busy"/"warn"/"error"/"ok"）
  - `error = Signal(str)`
  - `request_region = Signal()`（请求 UI 弹框选 overlay）
  - `capture_flash = Signal()`（截屏瞬间闪边框）
- 用 `Signal(object)` 传 list，避免 Qt 类型注册问题。
- 工作线程用 `threading.Thread(daemon=True)` 即可，不需要 QThread。

### 3.3 新增/调整后的文件清单
| 文件 | 动作 | 职责 |
|---|---|---|
| `bridge.py` | 新增 | QObject 信号桥 |
| `parsing.py` | 新增 | 三级解析器（JSON→分隔符→兜底），从 agentic.py 抽出 |
| `prompts.py` | 新增 | 系统提示词、JSON schema 说明、修复提示词常量 |
| `image_utils.py` | 新增 | Pillow 压缩缩放 |
| `overlay.py` | 新增 | 框选截屏全屏遮罩 |
| `settings_dialog.py` | 新增 | 设置对话框（含首次启动向导、测试连接） |
| `presets.py` | 新增 | 8 家 provider 预设常量（从 config.json 挪出来） |
| `request_manager.py` | 新增 | latest-wins 请求调度 + 取消 |
| `cache.py` | 新增（T25） | 截图 sha256 精确缓存（键含 provider/model/prompt_extra，无模糊匹配） |
| `applog.py` | 新增 | 日志初始化（控制台+滚动文件，key 脱敏） |
| `agentic.py` | 重写 | 真 SSE 流式 + 429 退避 + 限流 + extra 透传 |
| `capture.py` | 修复 | mss 正确用法、光标所在屏、每线程实例 |
| `ui.py` | 修复+增强 | 全部配置项生效、历史、速览复制、折叠修复 |
| `main.py` | 重写 | AppController 组装一切 |
| `config.py` / `config.json` | 调整 | v2 schema、frozen 路径、缺省自动生成 |
| `server.py` | 降级 | 保留但改为复用新客户端；依赖挪到 requirements-server.txt |
| `requirements.txt` | 修复 | 合法格式 + 新增 Pillow |
| `requirements-dev.txt` | 新增 | pytest |
| `requirements-server.txt` | 新增 | fastapi/uvicorn（可选） |
| `tests/` | 新增 | pytest 套件（见第八节） |
| `start.bat` / `build_exe.ps1` | 修复 | 见任务 T24 |
| `README.md` / `DESIGN.md` | 重写 | v2 文档 |
| `probe_agentic.py` | 保留 | 改为调用 parsing.py 的函数 |

---

## 四、施工任务（按编号顺序执行，共 5 个里程碑）

> 每个任务完成后必须自测验收标准，通过才做下一个。
> 里程碑 M0 完成后项目必须能启动不崩；M1 完成后核心链路真实可用；M2 完成后准确率方案落地；M3 完成后体验完善；M4 完成后工程收尾。

### ═══ 里程碑 M0：清理与止血（先让它能跑）═══

#### T1 清理垃圾文件
- 在 `D:\Users\ff\Desktop\dati` 下新建 `_archive` 文件夹。
- 把 1.2 节列出的根目录 16 个垃圾脚本**移动**（不是删除）进 `_archive`。根目录只保留 `screen-quiz-helper` 和 `_archive`。
- 删除 `screen-quiz-helper\__pycache__`（可再生缓存，安全）。
- 新增 `screen-quiz-helper\.gitignore`：忽略 `__pycache__/`、`logs/`、`screenshots/`、`build/`、`dist/`、`*.spec`、`.pytest_cache/`。
- 验收：根目录干净；主工程无任何垃圾脚本。

#### T2 修复 requirements（B3）
- `requirements.txt` 重写为纯 pip 格式（# 注释开头），内容：
  ```
  mss>=9.0.0
  keyboard>=0.20.0
  PySide6>=6.6.0
  httpx>=0.28.0
  Pillow>=10.0.0
  ```
- 新增 `requirements-dev.txt`：`pytest>=8.0`
- 新增 `requirements-server.txt`：`fastapi>=0.110`、`uvicorn[standard]>=0.30`
- 验收：`pip install -r requirements.txt` 无报错。

#### T3 修复 agentic.py 致命 bug（B1、B12 临时处理）
- 把模块级 `parse_questions` 挂到类上：在 `AgenticClient` 内加 `parse_questions = staticmethod(parse_questions)`（注意定义顺序），或直接把 `ask()` 里的 `self.parse_questions(text)` 改成模块函数调用 `parse_questions(text)`。**推荐后者，最简单。**
- `ask_stream()` 暂时改为：`yield from [chunk for chunk in ...]` 不用做，直接删掉这个假方法（M2 的 T12 会写真的）。
- 修正 `parse_questions` 的怪异缩进（函数体 8 空格改 4 空格）。
- 验收：`python probe_agentic.py` 全部 PASS。

#### T4 修复 ui.py 致命 bug（B2、B11、B20）
- import 行补上 `QRect`（来自 PySide6.QtCore）；顺手删掉重复导入的 `QBrush`、无用的 `QSizePolicy as _`。
- `toggle_collapse()` 重写逻辑：
  - 折叠：记住当前尺寸 `self._normal_size = self.size()`；`self.setMinimumSize(0,0)`、`self.setMaximumSize(16777215,16777215)` 后再 `setFixedSize(48,48)`；隐藏 header/status/scroll/footer 中除"展开"按钮外的一切。折叠态只显示一个 48×48 的"答"字按钮（用一个专用 QPushButton，点击展开）。
  - 展开：`setMinimumSize(360,180)`、`setMaximumSize(16777215,16777215)`，`resize(self._normal_size)`，恢复所有控件显示。
- `_flash_status(msg)`：先用局部变量记住当前状态文本和样式，1.5 秒后恢复**记忆的那份**；若期间状态被其他调用改过（比较当前文本是否仍等于 flash 文本），不改。
- 验收：手动运行 ui.py 独立入口，折叠→展开尺寸正常；托盘图标出现不崩。

#### T5 修复 capture.py（B7、B8、B9、B10、B19）
- 删除末行 `Callable = Any`，改为顶部 `from typing import Callable`。
- `capture_full()` / `capture_region()`：
  - `mss.tools.to_png(img.rgb, img.size)`（B7）。
  - **不再缓存 mss 实例**：每次截屏 `with mss.mss() as sct: ...`，删除 `_ensure_sct`、`_sct`、`_sct_lock`（B9）。
  - `capture_full(monitor: int | None = None)`：monitor=None 时截取**鼠标光标所在显示器**。实现：用 `keyboard` 不可靠，改用 ctypes 调 `GetCursorPos` 拿物理坐标，遍历 `sct.monitors[1:]` 找包含该点的矩形；找不到就用 `sct.monitors[1]`（主屏）。**绝不用 monitors[0]**（B10）。
- **防抖彻底移出 capture 层**：删除 `_debounce_ok`、`set_debounce`、`_last_capture_ts`、`_debounce_seconds`。`capture_full()` / `capture_region()` 每次调用都真实截屏、永远返回 CaptureResult（失败抛 CaptureError）。防抖全局只留 AppController 热键入口一层（见 T6），被防抖拒绝时由 AppController 静默忽略并状态条提示"触发太快，已忽略"（B19 在此解决）。这样 T14 框选的"冻结背景"截图不会被刚按过的整屏热键误伤。
- 验收：写一个临时脚本间隔 <1s 连续调用 capture_full 两次，两次都返回 CaptureResult 且 png_bytes 非空；PNG 能被 Pillow 打开。

#### T6 修复 main.py 线程与客户端问题（B4、B5、B6）
- 新建 `bridge.py`：按 3.2 节定义 `Bridge(QObject)` 全部信号。
- `main.py` 重构：
  - 启动时创建**唯一** `AgenticClient`（删掉 client_factory 每次新建的写法）。
  - 新建 `AppController` 类持有 cfg/capture/client/bridge/panel。热键回调只做：防抖判断 → 起 daemon 线程执行截屏+请求。**防抖全局唯一一层就在这里**：读 `cfg.capture.debounce_ms`，距上次热键触发不足间隔 → 忽略本次并 `bridge.status.emit("触发太快，已忽略","info")`。注意：框选 overlay 完成后的续跑流程（T14 回调→submit）**不再过防抖**——防抖只针对"按下热键"这个事件，不针对请求链路的中间步骤。
  - 工作线程内所有 UI 更新一律 `bridge.xxx.emit(...)`；主线程里 `bridge.questions_ready.connect(panel.set_questions)` 等逐一接线。
  - 删除 `capture._last_hotkey` 引用（B5）；框选热键暂时也走整屏（M2 的 T14 接 overlay）。
  - 请求进行中再次按热键：暂用简单策略——`threading.Lock` + busy 标志，busy 时忽略并 `bridge.status.emit("上一次请求还在进行…","busy")`（M2 的 T13 升级为取消旧请求）。
- 验收：启动 `python main.py`，窗口+托盘出现；按 Shift+Alt+S（无 key 时）悬浮窗显示 HTTP 401 错误而**不是崩溃**；连按两次不崩、第二次显示 busy 提示。

**M0 总验收：装依赖→启动→按热键→出错误提示（无 key）或出答案（有 key），全程不崩。**

### ═══ 里程碑 M1：配置与基础设施 ═══

#### T7 config v2（B15、B17）
- `presets.py` 新增：`PRESETS: dict[str, dict]`，8 家预设（agentic/openai/azure/qwen-vl/gemini/moonshot/ollama/openrouter），字段：`label`（中文名）、`api_base`、`model`、`min_interval_seconds`、`extra`、`supports_json_mode`（openai/qwen/gemini/openrouter 为 True，其余 False，ollama False）。数值沿用现 config.json `_presets` 段。
- `config.json` v2 结构（完整示例，执行模型照抄结构）：
  ```json
  {
    "autostart": false,
    "hotkeys": {
      "capture_fullscreen": "shift+alt+s",
      "capture_region": "shift+alt+d",
      "copy_answers": "shift+alt+c",
      "toggle_panel": "shift+alt+h"
    },
    "model": {
      "provider": "openai",
      "api_key": "",
      "api_base": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "timeout_seconds": 60,
      "low_confidence_threshold": 0.6,
      "min_interval_seconds": 3,
      "json_mode": "auto",
      "verify_low_confidence": false,
      "prompt_extra": "",
      "extra": {}
    },
    "capture": {
      "debounce_ms": 1000,
      "keep_local_screenshot": false,
      "monitor": "cursor",
      "max_image_side": 2048,
      "image_format": "jpeg",
      "jpeg_quality": 85
    },
    "ui": {
      "float_mode": "on_answer",
      "default_corner": "bottom-right",
      "show_capture_flash": true,
      "capture_sound": false,
      "history_size": 10,
      "field_visibility": {"answer": true, "confidence": true, "reasoning": true, "topic": true}
    },
    "parse": {"repair_pass": true},
    "log": {"level": "INFO", "to_file": true}
  }
  ```
- `config.py` 对应改动：
  - dataclass 增加上述全部新字段，默认值与示例一致；`json_mode` 取值 `"auto"|"on"|"off"`。
  - `PROJECT_DIR` 改为函数 `app_dir() -> Path`：`getattr(sys, "frozen", False)` 为真时返回 `Path(sys.executable).parent`，否则 `Path(__file__).resolve().parent`（B17）。config/logs/screenshots 全部基于 `app_dir()`。
  - **config.json 不存在时不再抛 FileNotFoundError**：自动用默认值生成一份写入磁盘，`Config.load()` 返回对象并带标志 `cfg.is_first_run = True`（普通属性，不入 JSON）。
  - 兼容旧文件：读到 model 段里的 `_presets`/`_note` 直接忽略；`extra` 里的 `_note` 剔除。
  - 新增 `Config.save(path=None)`：把当前配置序列化为 v2 JSON 写回（indent=2, ensure_ascii=False），未知字段丢弃。
- 验收：删掉 config.json 启动能自动生成；旧版 config.json 能被读取不崩；`Config.load()` 后 `save()` 再 `load()` 字段一致（写进 tests）。

#### T8 日志 applog.py
- `setup_logging(cfg)`：logging.basicConfig 控制台 + `RotatingFileHandler(app_dir()/"logs"/"app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")`。
- 加一个 `logging.Filter`：把消息中形如 `sk-` 开头长 token、`Bearer xxx` 的内容替换为 `***`（正则 `sk-[A-Za-z0-9_\-]{8,}` 和 `Bearer\s+\S+`）。
- httpx 的 logger 级别设为 WARNING（避免请求体刷屏）。
- main.py 启动最先调用它。
- 验收：跑一次后 logs/app.log 存在，里面搜不到完整 api_key。

#### T9 单实例保护
- main.py 里用 `QLocalServer`：启动时 `QLocalSocket` 尝试连接名为 `"screen-quiz-helper-single"` 的本地服务；连接成功说明已有实例 → 向旧实例发送 `"show"` 后退出（旧实例收到后把悬浮窗 show+raise）；连接失败则 `QLocalServer.removeServer` 同名残留并 listen。
- 验收：开两个 `python main.py`，第二个进程自动退出，第一个的窗口弹到前面。

### ═══ 里程碑 M2：准确率核心（本计划最重要部分）═══

#### T10 提示词工程 prompts.py（修 B13 的根）
- 新增 `prompts.py`，包含三个常量。`SYSTEM_PROMPT` 全文如下（照抄，不许缩水）：
  ```
  你是一个严谨的答题助手。用户会发给你一张屏幕截图，图中可能包含一道或多道题目（选择题、多选题、判断题、填空题、简答题、计算题等）。你的任务是识别所有题目并给出正确答案。

  输出要求（必须严格遵守）：
  1. 只输出一个 JSON 对象，不要输出任何其它文字、解释或 Markdown 代码块标记。
  2. JSON 结构固定为：
  {"questions":[{"index":1,"type":"单选","question":"题干一句话摘要","answer":"B","confidence":0.92,"reason":"一到三句话的解题依据"}]}
  3. 字段规则：
     - index：从 1 开始的题号，按截图中从上到下、从左到右的顺序。
     - type：只能是 单选/多选/判断/填空/简答/计算 之一。
     - question：题干的简短摘要（不超过 40 字），便于用户对应是哪道题。
     - answer：单选题只输出选项字母（如 B）；多选题输出全部正确选项字母、按字母序连写（如 ACD）；判断题输出 对 或 错；填空题多空用 ①②③ 编号分隔；简答/计算题给出最终结论，计算题可附关键算式。
     - confidence：0 到 1 的小数，表示你对该答案的真实把握。拿不准就如实给低值，不许虚高。
     - reason：简明解题依据，一到三句话。
  4. 图中没有题目时输出 {"questions":[],"note":"未识别到题目"}。
  5. 题目文字模糊或被遮挡而无法辨认时，该题 confidence 给 0.3 以下并在 reason 中说明看不清。
  6. 认真读题干和每个选项再作答；多选题逐项判断每个选项的对错，不要漏选或多选。
  7. 全部用简体中文（题目本身是英文的，answer 保留英文原文，reason 用中文）。
  ```
- `REPAIR_PROMPT`（解析失败后的纯文本修复请求用）：
  ```
  下面是一段答题结果文本，请把它原样转换为规定格式的 JSON 对象后输出，不要改变答案内容，不要输出 JSON 以外的任何文字。格式：{"questions":[{"index":1,"type":"单选","question":"...","answer":"...","confidence":0.9,"reason":"..."}]}。缺失的字段用空字符串或 null。待转换文本：\n
  ```
- `build_system_prompt(cfg) -> str`：返回 SYSTEM_PROMPT + （cfg.model.prompt_extra 非空时追加 `"\n\n补充背景："` + prompt_extra）。
- `USER_PROMPT = "请识别截图中的全部题目并按规定 JSON 格式作答。"`
- 验收：字符串常量存在；build_system_prompt 拼接正确（写进 tests）。

#### T11 三级解析器 parsing.py（修 B14）
- 新增 `parsing.py`，把 `Question` dataclass 从 agentic.py 挪到这里（agentic.py `from parsing import Question` 保持旧导入路径兼容：agentic.py 里保留 `from parsing import Question, parse_questions` 的 re-export）。
- `Question` 增加字段 `question: str = ""`（题干摘要），`to_dict()` 同步。
- `parse_questions(text: str) -> list[Question]` 三级策略，**按顺序尝试，成功即返回**：
  - **第 1 级 JSON**：
    1. strip 后若以 ```` ``` ```` 开头，剥掉首尾代码围栏行（正则 `^```[a-zA-Z]*\s*` 与 `\s*```$`）。
    2. 找第一个 `{` 到最后一个 `}` 的子串，`json.loads`。
    3. 取 `obj["questions"]` 列表；每项构造 Question：index 缺省用序号；type→topic；answer 转 str；confidence 尝试 float 并 clamp 到 [0,1]，失败置 None；reason→reasoning；question→question。
    4. 列表为空且 obj 有 note → 返回空列表（调用方显示 note）。
    5. 任何异常 → 进入第 2 级。
  - **第 2 级分隔符**（兼容旧格式和模型不听话的情况）：
    1. 分隔正则放宽为 `r"[=＝]{2,}\s*第\s*(\d+)\s*题\s*[=＝]{2,}"`，另兼容 Markdown 标题式 `r"^#{1,4}\s*第\s*(\d+)\s*题"` 和裸行 `r"^第\s*(\d+)\s*题\s*[:：]?\s*$"`（.MULTILINE）。
    2. 每段内逐行找字段，键名匹配规则：先去掉行首的 `*`、`#`、`-`、空格，再匹配 `^(题型|类型|答案|置信度|理由|解析|题目|题干)\s*[:：]\s*(.*)$`（**半角全角冒号都认**）。
    3. 字段值支持续行：某字段行之后、下一个字段行之前的非空行，追加到该字段（用 `\n` 连接）——修 B14 的多行丢失。
    4. 置信度解析：提取字符串中第一个 `\d*\.?\d+`，若 >1 视为百分制除以 100，clamp [0,1]。
  - **第 3 级兜底**：整段文本塞进一个 `Question(index=1, answer=text.strip())`；文本为空白则返回空列表（不再造一题空答案）。
- `answers_digest(questions) -> str`：速览串，形如 `1.B  2.ACD  3.对  4.①x=2 ②y=3`（每题 `index.answer`，answer 超过 20 字截断加 `…`，空格分隔）。
- 验收：第八节 test_parsing 全部用例通过。

#### T12 agentic.py 重写：真流式 + 健壮请求（修 B12、B15）
- 保持类名 `AgenticClient` 与构造参数兼容，新增参数 `provider: str = ""`（json_mode=auto 时据此查 presets 的 supports_json_mode；AppController 传 `cfg.model.provider`）、`json_mode: str = "auto"`、`extra: dict | None = None`、`on_status: Callable[[str], None] | None = None`（回调用于限流倒计时，由 AppController 接到 bridge.status）。
- `ask(image_b64, prompt="", system="") -> list[Question]`：内部改为消费 `ask_stream` 聚合全文后 `parse_questions`。保留此同步接口给 server.py 和测试用。
- `ask_stream(image_b64, prompt="", system="", cancel_event: threading.Event | None = None) -> Iterator[str]`：
  1. 组请求体：model、messages（system + user[text, image_url data URI]）、`stream: true`、`temperature: 0.2`、`max_tokens: 4096`。
  2. json_mode 处理：`"on"` 或（`"auto"` 且当前 provider 在 presets 中 supports_json_mode=True）时加 `"response_format": {"type": "json_object"}`。若服务器返回 400 且响应文本含 `response_format`（大小写不敏感），**去掉该字段原样重发一次**，并把实例内 `self._json_mode_works = False` 记住，后续不再带。
  3. `extra` 透传：`body.update(self.extra)`；特殊键 `api_version` 从 body 拿出，作为 URL query `?api-version=...` 拼到 endpoint（Azure 支持，修 B15）。
  4. 用 `httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10))` + `client.stream("POST", url, json=body, headers=...)`；逐行读 SSE：以 `data: ` 开头 → strip 前缀 → `[DONE]` 结束 → `json.loads` 取 `choices[0].delta.content`，非空则 yield。某行 JSON 解析失败跳过该行（容错）。
  5. 每次循环检查 `cancel_event.is_set()` → 立即 return（生成器关闭时 httpx with 块自动断连接）。
  6. 429：读 `Retry-After` 响应头（有则用它，无则用 1/2/4s 表），`on_status(f"限流中，{wait:.0f} 秒后重试…")`，sleep 后重试，最多 3 次；期间检查 cancel_event。
  7. 网络错误（ConnectError/ReadTimeout 等）：同样按 1/2/4s 重试最多 3 次；最终失败抛出带**人话信息**的异常：401→"API key 无效或未填写"；404→"api_base 或模型名不对"；400→"请求被拒绝：{响应体前 200 字}"；超时→"模型响应超时（{timeout}s），可在设置中调大"；连接失败→"无法连接服务器，检查网络或 api_base"。定义 `class ModelError(RuntimeError)` 承载这些信息，UI 直接显示 str(e)。
  8. `_throttle()`：保持最小间隔逻辑，但把 `time.sleep(wait)` 拆成 0.5s 步进循环，每步 `on_status(f"距下次可调用还需 {remaining:.0f}s")` 并检查 cancel_event；间隔从**上次请求完成时刻**起算。
  9. 流式聚合结束后若全文为空白 → 抛 ModelError("模型返回了空内容，请重试或换模型")。
- 修复请求（配合 T11）：`repair(raw_text: str) -> list[Question]`——纯文本调用（无图），system 用 REPAIR_PROMPT 拼接原文，非流式即可，结果走 parse_questions；失败返回第 3 级兜底。由 AppController 在 `cfg.parse.repair_pass=True` 且第 1、2 级都失败（判定：解析结果只有 1 题且 answer 长度>200 或含 "{"）时调用一次。
- `test_connection() -> str`：发一个极小纯文本请求（"回复 OK 两个字"，max_tokens=8，timeout=10，**绕过 min_interval**），成功返回模型回复文本，失败抛 ModelError。给设置对话框用。
- 验收：tests 里用 httpx.MockTransport 模拟 SSE/429/400 response_format/401，全部通过；`probe_agentic.py` 仍 PASS。

#### T13 latest-wins 请求调度 request_manager.py
- `RequestManager`：
  - `submit(fn)`：`self._generation += 1`；若存在旧的 `cancel_event` → set()（旧线程在下一个检查点退出）；创建新 `threading.Event`，起 daemon 线程跑 `fn(generation, cancel_event)`。
  - 回调前检查 `generation == self._generation`，不等则丢弃结果（旧请求即使跑完也不许污染 UI）。
  - AppController 把"截屏后→ask_stream→聚合→解析→(可选 repair)→emit"整段包成 fn。截屏本身在提交前做（热键线程内同步截，很快）。
  - 流式期间：每收到增量 `bridge.partial_text.emit(chunk)`；被取消的旧 generation 的增量在 AppController 侧同样按 generation 过滤。
- 验收：连续快速触发两次热键（防抖设 0 测试），UI 最终只显示第二次的结果；日志可见第一次被取消。

#### T14 框选截屏 overlay.py
- `RegionOverlay(QWidget)`：
  1. 触发时**先截一张光标所在屏的整屏图**（capture_full），把 PNG 转 QPixmap 作为遮罩背景显示——实现"冻结屏幕"效果，框选期间画面不动。capture 层无防抖（T5），刚按过整屏热键也不影响本次冻结截图。
  2. 窗口：FramelessWindowHint | WindowStaysOnTopHint，geometry 设为该屏幕的 `QScreen.geometry()`（逻辑坐标），背景画 pixmap（按 devicePixelRatio 缩放到窗口大小）。
  3. 半透明黑色蒙层 + 鼠标拖拽矩形高亮（QPainter 画亮色边框 + 清除蒙层区域），左上角实时显示 `宽×高` 像素提示；顶部居中一行说明文字"拖动框选题目区域，松开确认，Esc 取消"。
  4. 鼠标释放：把逻辑坐标矩形换算回**截图像素坐标**（乘 `pixmap.width()/window.width()` 比例），通过回调 `on_done(left, top, w, h)` 交回 AppController；宽高任一 <20 像素视为误触，取消。Esc 或右键取消。
  5. overlay 必须在主线程创建/销毁：热键线程 `bridge.request_region.emit()` → 主线程槽函数创建 overlay；回调里再走 T13 的 submit 流程，用 `capture.capture_region(...)`（注意 capture_region 收物理像素坐标，overlay 算出的就是物理像素，不要再加 monitors[0] 偏移——**capture.py 的 capture_region 改为直接使用传入的绝对屏幕坐标**，删掉现在加 mon["left"] 的逻辑）。
- 验收：按 Shift+Alt+D 出现冻结遮罩，框选后仅框内内容被发给模型（开 keep_local_screenshot 验证截图范围）；Esc 取消无副作用；125%/150% 显示缩放下坐标准确。

#### T15 图片预处理 image_utils.py
- `prepare_image(png_bytes: bytes, max_side: int, fmt: str, quality: int) -> tuple[str, str]`：
  - Pillow 打开 PNG；若长边 > max_side，等比 LANCZOS 缩到 max_side。
  - fmt="jpeg"：转 RGB 存 JPEG(quality=quality, optimize=True)，返回 (base64, "image/jpeg")；fmt="png" 保持 PNG。
  - agentic 的 data URI 前缀用返回的 mime（不再写死 image/png）。
- AppController 在截屏后、请求前调用，参数来自 cfg.capture。
- 验收：4K 测试图处理后长边 ≤2048、体积 < 原 PNG 的 1/5；tests 覆盖。

#### T16 低置信度与可选复核
- UI：confidence < 阈值的题卡片整体淡黄背景 + "建议人工核对"（现有逻辑保留，扩展到卡片背景）。
- `cfg.model.verify_low_confidence=True` 时：首批结果里存在低置信题 → 自动追加一次**带原图的复核请求**：消息内容 = 原截图（同一张 base64 图）+ 首批全部题目的 JSON（index/question/answer/reason），system 提示"重新审视截图中每道题与下面给出的首批答案，逐题核对，如有错误给出修正，仍按规定的 JSON 格式输出全部题目"。不带图模型无法重新看题，**必须带图**。结果覆盖 UI 并状态条注明"已复核"。默认 False（省额度）。复核也走 RequestManager（同一 generation 内串行，不算新请求）。
- 验收：开关关闭时不产生第二次调用；开启时低置信题触发复核（MockTransport 测试）。

**M2 总验收：真实 key 下，对一张含 3 道题的截图按热键，悬浮窗流式出 3 张卡片，字段齐全、选项字母干净、复制速览串正确；框选只对框内答题。**

### ═══ 里程碑 M3：易用性 ═══

#### T17 设置对话框 settings_dialog.py（含首次向导）
- `SettingsDialog(cfg, client, parent)`，QDialog + QTabWidget 四页：
  - **模型页**：预设下拉框（presets.py 的 8 家 + "自定义"）；选择预设自动填 api_base/model/min_interval；api_key（QLineEdit.Password，带"显示"勾选）；model、api_base、timeout、min_interval、low_confidence_threshold（QDoubleSpinBox 0~1）、json_mode 下拉（auto/on/off）、verify_low_confidence 勾选、prompt_extra 多行框（placeholder："可填背景，如：这是计算机网络方向的测评题"）。**"测试连接"按钮**：调 client.test_connection()（用对话框当前值临时构造客户端），结果弹 QMessageBox 成功/失败原因；测试期间按钮禁用显示"测试中…"（放 threading 线程 + 信号回 UI，遵守线程铁律）。
  - **热键页**：4 个热键（整屏/框选/复制速览/显示隐藏面板）。每个用只读 QLineEdit + "录制"按钮：点击后 grabKeyboard，keyPressEvent 记录修饰键+主键拼成 `shift+alt+s` 格式，Esc 取消录制；保存前用 `keyboard.parse_hotkey` 校验合法性，非法弹提示。
  - **显示页**：float_mode（always/on_answer）、default_corner 四角下拉、field_visibility 四个勾选、capture_flash、capture_sound、history_size、折叠启动勾选（可选）。
  - **高级页**：monitor（cursor/primary）、max_image_side、image_format、jpeg_quality、debounce_ms、keep_local_screenshot、repair_pass、日志级别、"打开日志文件夹"按钮（os.startfile）。
- 底部：保存 / 取消。保存 → cfg 更新 + `cfg.save()` → 发回调让 AppController 重建 client、重注册热键（先 unhook_all 再注册）。
- **首次启动向导**：cfg.is_first_run 或 api_key 为空时，启动即弹本对话框并在顶部显示醒目提示"第一步：选择模型服务商并填入 API key，然后点测试连接"。用户点取消也允许进入主界面（悬浮窗状态条持续提示"未配置 API key，双击托盘打开设置"）。
- 托盘菜单加"设置"项；悬浮窗 header 右侧加一个小"⚙"按钮。
- 验收：全流程不改 JSON 完成配置；改热键立即生效；错误 key 测试连接给出人话报错。

#### T18 悬浮窗增强 ui.py（修 B16 全部）
- **field_visibility 真正生效**：_make_card 按开关决定要不要创建 confidence/reasoning/topic 控件；answer 永远显示（开关置灰并注明"答案不可隐藏"）。
- **float_mode**：`on_answer` 时启动隐藏窗口（托盘常驻），首批答案到达时 show+raise；`always` 常显。收到错误也要 show（用户需要看到失败原因）。
- **default_corner**：showEvent 首次按 `QGuiApplication.primaryScreen().availableGeometry()` 把窗口放到配置角（边距 16px）。用户拖动过之后不再自动挪。
- **capture_flash**：bridge.capture_flash → 窗口边框变亮青色 300ms 后恢复（QTimer + stylesheet）；capture_sound=True 时 `QApplication.beep()`。
- **流式显示**：请求期间状态条"模型思考中…"，下方一个临时 QLabel 逐字追加 partial_text（最多显示最后 500 字符，防卡顿）；questions_ready 到达后移除临时 label 换成卡片。
- **历史回看**：`self._history: list[list[Question]]`，上限 cfg.ui.history_size；header 加 `◀ 1/3 ▶` 导航（当前批索引/总数），翻页只切换显示不清历史；新批到达自动跳到最新。
- **速览复制**：footer 加"复制答案"按钮 → 剪贴板写入 `answers_digest()`；新热键 `shift+alt+c` 全局触发同一功能（bridge 信号到主线程执行），状态条 flash"已复制：1.B 2.ACD…"。
- **卡片题干**：标题行显示 `第N题 · 单选 · 题干摘要…`（question 字段截 30 字）。
- **状态条级别配色**：info 灰 / busy 蓝 / warn 黄 / error 红 / ok 绿，由 bridge.status 的第二参数决定。
- `shift+alt+h` 热键：显示/隐藏悬浮窗。
- 验收：逐个配置项改动后行为符合上表；断网按热键窗口自动弹出显示人话错误。

#### T19 server.py 降级对齐
- 保留文件与 /health /init /ask 路由，内部改用新 AgenticClient（含 json_mode/extra 参数）与 parsing.py；/ask 支持 `stream` 可选参数暂不做（文档注明非流式）。
- 文件头注释注明"可选组件，主程序不依赖；pip install -r requirements-server.txt 后可用"。
- 验收：不装 fastapi 时 `python main.py` 正常（main 不 import server）；装后 `python server.py` 可启动且 /health 返回 ok。

### ═══ 里程碑 M4：工程收尾 ═══

#### T20 测试套件 tests/
- 按第八节用例表实现 pytest；运行方式 `python -m pytest tests -q`，全部不依赖网络/真实 key/显示器（UI 测试仅测纯逻辑函数，不实例化 QWidget）。
- probe_agentic.py 改 import parsing 并保持可独立运行。
- 验收：全套绿色；CI 无需（本地跑）。

#### T21 打包修复 build_exe.ps1
- PyInstaller 命令追加：`--hidden-import keyboard --collect-submodules mss --add-data "config.json;."` 不需要（config 用 exe 旁外置文件，见 T7 frozen 路径）；追加 `--icon NONE` 可省。关键点：
  - 打包后目录结构：dist\screen-quiz-helper.exe + config.json（脚本已复制，保留）。
  - 因为 T7 的 app_dir() 已处理 frozen，exe 首次运行会在 exe 旁生成/读取 config.json。
  - `--windowed` 下 stdout 不可见：applog 的文件日志成为唯一排障渠道（T8 已保证）。
  - 脚本末尾输出验收提示文案。
- start.bat 修复（B18）：结尾无条件 `pause`（或 `if not "%~1"=="--nopause" pause`），删掉 CMDLEVEL 假变量。
- 验收：本机执行 build_exe.ps1 产出 exe；把 dist 拷到另一个文件夹双击 exe 能启动并在旁边生成 config.json。

#### T22 文档重写
- README.md：项目简介、功能清单（v2 实况）、安装三步走、首次配置向导说明、热键表（4 个）、8 家预设表、限流说明（min_interval 按预设自动带出）、常见问题（401/404/429/超时/热键无效→以管理员运行/框选坐标偏移→显示缩放）、打包步骤、测试命令。
- DESIGN.md：更新为 v2 架构（照抄本计划第三节并补充实现后的实际差异），保留"边界不做"清单。
- 验收：新用户只读 README 能独立完成安装到出答案。

#### T23 开机自启（可选开关，默认关）
- cfg.autostart=True 时：在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 写入 `"ScreenQuizHelper"` 值 = 启动命令（源码模式：`"pythonw.exe 完整路径\main.py"`；frozen：exe 完整路径）。False 时删除该值。用 winreg 标准库，只动 HKCU 不需要管理员。设置对话框高级页加勾选。
- 验收：勾选后注册表出现该值，取消后消失。

#### T24 终验（执行模型自查清单）
1. `pip install -r requirements.txt` 成功。
2. `python -m pytest tests -q` 全绿。
3. `python probe_agentic.py` PASS。
4. 删除 config.json → `python main.py` → 自动生成配置 + 弹设置向导。
5. 填入真实 key → 测试连接成功 → 保存。
6. 打开任意含题目的窗口 → Shift+Alt+S → 流式出卡片，字段齐全。
7. Shift+Alt+D 框选 → 只答框内题。
8. Shift+Alt+C → 剪贴板为速览串。
9. 连按热键 → 旧请求取消、只出最新结果、无崩溃。
10. 拔网线按热键 → 人话错误提示。
11. 折叠→展开正常；拖动正常；历史翻页正常。
12. 第二个实例启动 → 自动退出并唤起第一个。
13. logs/app.log 存在且无明文 key。
14. build_exe.ps1 打包 → exe 在干净目录可运行。

#### T25 可选增强：缓存秒回 + 错题本 + 追问讲解（M4 之后做，均为学习练习向功能）
- **答案缓存（省额度、重复题秒回；只做精确匹配，杜绝误答）**：
  - 新增 `cache.py`：缓存键 = `sha256( sha256(预处理后图片字节).hexdigest() + provider + model + sha256(prompt_extra).hexdigest() )`。**禁止做 dhash/感知哈希等任何模糊匹配**——同网站同布局但题目文字不同的截图，感知哈希很可能相近，模糊命中会把上一题答案错当本题答案，宁可不命中也不许误答。
  - 命中规则：键完全相等才命中；命中则直接 `bridge.questions_ready.emit(缓存结果)`，状态条注明"缓存命中，未消耗额度"，跳过模型调用。换 provider、换模型、改 prompt_extra 后键自然不同，不会回旧答案。
  - 存储：内存 dict + 落盘 `app_dir()/"cache.json"`（上限 200 条，超出按 LRU 淘汰；保存原子写）。设置高级页加"启用答案缓存"勾选（默认开）和"清空缓存"按钮。
  - 说明：只有画面完全静止的重复截屏才会字节一致（任务栏时钟跳动、光标闪烁都会导致不命中，属预期行为，安全侧优先）。框选图与整屏图字节不同，天然分开。
- **错题本 / 复习导出**：
  - 每张答案卡片加"收藏"小按钮；收藏批次存入 `app_dir()/"favorites.json"`（题目摘要、答案、理由、置信度、时间戳）。
  - 悬浮窗 footer 加"导出复习笔记"按钮：把收藏内容写成 Markdown（按日期分组，每题一节：题干摘要 / 我的答案 / 解析），保存到 `app_dir()/"exports"/复习笔记_YYYYMMDD.md`，完成后状态条显示路径并可直接打开文件。
- **追问讲解（把题真正弄懂）**：
  - 每张卡片加"追问"按钮：把该题的 question/answer/reason 组成纯文本请求（system："你是耐心的老师，请详细讲解这道题的知识点和解题步骤，用简体中文，分步骤说明"），走 RequestManager（取消其它进行中请求），结果以讲解卡片形式追加在该题下方，可复制。
  - 讲解请求同样受 min_interval 限流与 429 退避约束。
- 验收：同一静止画面连续截两次，第二次不调 API 直接出结果；换模型或改 prompt_extra 后不命中；收藏→导出 md 内容完整；追问返回讲解且不影响其它题卡片。

---

## 五、关键实现细节备忘（执行模型易错点）

1. **Qt 信号跨线程**：Bridge 实例必须在主线程创建；connect 默认 AutoConnection 即可自动排队到主线程，不要显式 DirectConnection。
2. **keyboard 库热键回调运行在它自己的线程**，回调里只做轻量调度，重活全部丢线程池/线程。
3. **mss 坐标是物理像素，Qt 坐标是逻辑像素**，Windows 显示缩放（125%/150%）下两者不同。框选换算统一在 overlay 内用 pixmap/window 尺寸比例完成，别用 devicePixelRatio 硬乘（多屏混合 DPI 会错）。另外 main.py 启动最早处调用 `ctypes.windll.shcore.SetProcessDpiAwareness(2)`（用 try/except 包住，失败降级 `user32.SetProcessDPIAware()`），保证 mss 拿到真实物理分辨率。
4. **SSE 解析**：httpx `iter_lines()` 产出 str；空行跳过；`data: [DONE]` 结束；有的 provider 一行里带 `: keep-alive` 注释行（以冒号开头）也要跳过。
5. **json_mode=auto 的判定**：查 presets 里当前 provider 的 supports_json_mode；provider="自定义"或不在预设中 → 保守不带 response_format，靠提示词 + 三级解析。
6. **generation 过滤**要覆盖三处：partial_text、最终 questions、error。旧请求的错误不许弹到新请求界面上。
7. **config.save() 原子写**：先写 `config.json.tmp` 再 `os.replace`，防止写一半断电损坏配置。
8. **所有 except 分支必须走 bridge.error/status 显示**，禁止裸 `except: pass` 吞错（unhook 清理除外）。
9. **字符串资源全部简体中文**；代码注释中文或英文均可；不要引入本文档之外的第三方依赖。
10. **不要重构本文档没让动的东西**（比如把 PySide6 换 tkinter、把 httpx 换 requests），保持技术栈稳定。

---

## 六、准确率提升逻辑总结（为什么这样改会准）

| 措施 | 解决的问题 |
|---|---|
| T10 强约束系统提示词 + JSON 格式 | 现在模型不知道输出格式，解析全靠兜底 → 字段全丢；改后答案/置信度/理由结构化可靠提取 |
| T10 temperature=0.2 + 多选题逐项判断指令 | 降低随机性；多选题漏选是 VLM 最常见错误 |
| T11 三级解析 + 修复请求 | 模型偶尔不听话也能救回来，不再把整段文本当一题 |
| T14 框选截屏 | 整屏干扰元素多（导航栏/广告/其它题），框选后模型注意力集中，识别率和答题准确率都升 |
| T15 缩放到 2048 + JPEG | 超大图会被服务端二次压缩反而糊；主动控制尺寸让文字清晰且请求快 |
| T10 confidence 如实给低值 + T16 标黄/复核 | 错的题至少被标出来，用户知道哪些要人工核对 |
| T7 prompt_extra 背景注入 | 用户可注入"这是计算机网络测评"等领域背景，专业题准确率提升 |

---

## 七、交付物清单

1. 修复+增强后的 `screen-quiz-helper` 全部源码（第三节文件清单）。
2. `tests/` pytest 套件 + 更新版 probe_agentic.py。
3. 三个 requirements 文件、修复版 start.bat / build_exe.ps1。
4. v2 README.md / DESIGN.md。
5. `_archive/` 归档的旧垃圾脚本（不删除）。
6. 可运行的 dist exe（本机执行 T21 产出）。

---

## 八、测试用例表（tests/ 必须覆盖）

### test_parsing.py
| 用例 | 输入 | 期望 |
|---|---|---|
| JSON 标准 | `{"questions":[{"index":1,"type":"单选","question":"...","answer":"B","confidence":0.92,"reason":"..."}]}` | 1 题，字段全对 |
| JSON 带围栏 | ```` ```json\n{...}\n``` ```` | 同上 |
| JSON 前后废话 | `好的，以下是结果：{...} 希望有帮助` | 提取成功 |
| JSON 空题 | `{"questions":[],"note":"未识别到题目"}` | 返回 [] |
| confidence 越界 | confidence=1.5 / -0.2 / "92%" | clamp 到 1 / 0 / 0.92 |
| 分隔符全角冒号 | `===第1题===\n题型：单选\n答案：B\n置信度：0.9\n理由：xxx` | 字段全对 |
| 分隔符 Markdown 粗体 | `**答案**: B` | answer=B |
| 多行理由 | 理由行后跟两行续文 | reasoning 含三行 |
| Markdown 标题分隔 | `## 第1题\n答案: A\n## 第2题\n答案: C` | 2 题 |
| 兜底 | `这看起来是一道数学题…`（无格式） | 1 题 answer=原文 |
| 空输入 | `""` / 纯空白 | [] |
| 旧 probe 用例 | probe_agentic.py 现有三组断言 | 全过 |
| answers_digest | 单选B+多选ACD+判断对 | `1.B  2.ACD  3.对` |

### test_config.py
- 缺文件自动生成默认；load→save→load 幂等；旧版含 _presets 的 config 兼容；frozen 路径分支（monkeypatch sys.frozen / sys.executable）。

### test_agentic.py（httpx.MockTransport，无网络）
- SSE 正常流聚合；429 两次后成功（Retry-After=0 加速测试）；429 四次最终失败抛 ModelError；400 含 response_format 字样 → 自动去字段重发成功；401 → ModelError 文案含"API key"；cancel_event 置位 → 流提前结束；extra.api_version → URL 含 `api-version=`；空流 → ModelError。

### test_image_utils.py
- 3000×2000 PNG → 长边 2048；jpeg 体积 < png；mime 正确；小图不放大。

### test_request_manager.py
- 快速连续 submit 两次，慢的第一次结果被丢弃，只有第二次回调生效（用 Event 控制时序）。

### test_cache.py
- 同字节+同 provider/model/prompt_extra → 命中；图片字节差 1 个字节 → 不命中；换 model → 不命中；改 prompt_extra → 不命中；超过 200 条 LRU 淘汰最旧；落盘再加载后仍命中。

---

## 九、执行顺序与汇报要求

- 严格按 T1→T25 顺序；每个里程碑结束跑一次该里程碑验收并简述结果。
- 全部完成后：跑 T24 终验清单，逐项报告通过/失败；对失败项修复后复测。
- 最终向用户汇报：改了什么、准确率方案怎么生效、怎么启动使用、已知限制（框选单屏、非流式 server、复核默认关）。