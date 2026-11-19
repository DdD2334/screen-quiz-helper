# 屏幕答题助手 — 设计文档（v2）

> 一句话：Windows 常驻小工具，按热键截屏，把画面发给可配置的 OpenAI 兼容视觉大模型，流式逐题返回答案/置信度/理由/题型，在置顶悬浮窗显示、可复制。定位为**学习与练习辅助**（人工核对后使用）。

## 1. 目标与边界

目标：开箱即用、答得准、不崩溃不坑人、模型通用、可交付（源码 + exe + 离线测试）。

**边界（明确不做）**：
- 不自动填答到输入框
- 不做对截屏/监考软件隐藏窗口的功能
- 不做自动周期性偷拍（仅热键触发）
- 不做多模型自动 fail-over

## 2. 模块与数据流

```
keyboard 热键线程
   │ 触发
   ▼
main.py: AppController（唯一调度中心）
   │ 1. 防抖检查（全局唯一一层；不过→静默忽略+状态条提示）
   │ 2. 框选热键→Bridge.request_region → 主线程弹 RegionOverlay
   │ 3. capture.py 截屏（热键线程内同步截，调用线程内新建 mss 用完即关）
   │ 4. image_utils.py 压缩缩放 → base64
   │ 5. 提交 RequestManager（latest-wins：递增 generation，旧的作废）
   ▼
agentic.py: AgenticClient（全局唯一实例）
   │ 限流等待(状态条倒计时) → POST /chat/completions (stream=true)
   │ SSE 增量 → Bridge.partial_text → UI 打字机
   │ 完成 → parsing.py 三级解析 →（可选 repair）→ Bridge.questions_ready
   │（可选）低置信度 → 带原图复核 → 覆盖 UI
   ▼
ui.py: FloatingPanel（只在 Qt 主线程被信号槽更新）
```

### 线程铁律
- 任何 Qt 控件方法只在主线程调用；工作线程与 UI 之间只通过 `bridge.py: Bridge(QObject)` 的 Signal 通信（AutoConnection 自动排队）。
- Bridge 信号：questions_ready(object) / partial_text(str) / status(str,str) / error(str) / request_region() / capture_flash() / copy_answers() / toggle_panel()。
- 工作线程用 threading.Thread(daemon=True)，不用 QThread。
- generation 过滤覆盖三处：partial_text、最终 questions、error；旧请求的错误不许弹到新请求界面。

### 实现后的实际差异（相对施工蓝图）
- **截屏在热键回调线程内同步执行**（蓝图允许"起线程截屏"）：实测两个独立截屏线程会乱序 submit，导致旧请求反而成为"最新"。同步截屏保证 submit 顺序 = 热键顺序。
- CaptureResult 增加 `origin` 字段（所截显示器物理左上角）：框选回调返回截图内坐标，AppController 加 origin 得绝对屏幕坐标，多屏负坐标也正确。
- AgenticClient 增加 `transport` 构造参数：仅供测试注入 httpx.MockTransport。
- Azure 预设额外发送 `api-key` 头（Azure 原生鉴权），其余 provider 只用 Bearer。
- 框选物理尺寸用坐标差计算（QRect 含端点会多 1px）。

## 3. 文件清单

| 文件 | 职责 |
|---|---|
| main.py | 入口 + AppController 调度 + 单实例（QLocalServer） |
| bridge.py | QObject 信号桥 |
| capture.py | mss 截屏（光标所在屏/绝对坐标框选）+ keyboard 热键；无防抖 |
| image_utils.py | Pillow 压缩缩放（长边上限/JPEG 质量） |
| overlay.py | 框选冻结遮罩（逻辑→物理坐标按 pixmap/window 比例换算） |
| agentic.py | 真 SSE 流式 + 429 退避 + 限流倒计时 + json_mode 回退 + extra 透传 + repair + test_connection |
| prompts.py | SYSTEM_PROMPT（JSON 强约束）/ REPAIR_PROMPT / 复核与讲解提示词 |
| parsing.py | Question + 三级解析（JSON→分隔符→兜底）+ answers_digest |
| request_manager.py | latest-wins generation 调度与取消 |
| pack.spec | 精简打包定义：剔除 QtQml/Quick/Pdf/Svg/虚拟键盘/opengl32sw 与多余翻译 |
| cache.py | T25 答案缓存：sha256 精确匹配（禁止模糊），LRU 200 条落盘 cache.json |
| ui.py | 悬浮窗（历史/速览复制/流式/标黄/折叠/停靠角）+ 托盘 |
| settings_dialog.py | 四页设置 + 首次向导 + 测试连接 + 热键录制 + 开机自启 |
| presets.py | 8 家 provider 预设 |
| config.py / config.json | v2 schema；app_dir() 处理 frozen；缺省自动生成；原子写 |
| applog.py | 控制台 + 滚动文件日志，sk-/Bearer 脱敏 |
| server.py | 可选 FastAPI 通道（非流式），主程序不依赖 |
| tests/ | pytest 离线套件 |
| probe_agentic.py | 离线自检 |
| start.bat / build_exe.ps1 | 启动 / PyInstaller 单文件打包 |

## 4. 准确率方案

| 措施 | 解决的问题 |
|---|---|
| 强约束系统提示词 + JSON 格式 | 字段结构化可靠提取，不再整段文本当一题 |
| temperature=0.2 + 多选题逐项判断指令 | 降随机性；多选题漏选是 VLM 最常见错误 |
| 三级解析 + 修复请求 | 模型不听话也能救回 |
| 框选截屏 | 去掉整屏干扰元素，模型注意力集中 |
| 缩放到 2048 + JPEG | 避免服务端二次压缩糊字，请求快 |
| confidence 如实给低值 + 标黄/复核 | 错题至少被标出来 |
| prompt_extra 背景注入 | 领域背景提升专业题准确率 |

## 5. 关键实现细节

1. mss 坐标是物理像素，Qt 是逻辑像素；启动最早处 SetProcessDpiAwareness(2)（失败降级 SetProcessDPIAware）。框选换算用 pixmap/window 比例，不硬乘 devicePixelRatio。
2. SSE：空行与 `:` 注释行跳过；`data: [DONE]` 结束；单行坏 JSON 容错跳过。
3. json_mode=auto 查 presets.supports_json_mode；自定义/未知 provider 保守不带 response_format；400 含 response_format 字样时去字段重发一次并记住。
4. 防抖只针对"按下热键"事件；框选 overlay 完成后的续跑不过防抖。
5. config.save() 原子写（tmp + os.replace）；日志 key 脱敏；所有 except 分支走 bridge.error/status 显示（unhook 清理除外）。
6. 限流间隔从上次请求完成时刻起算，0.5s 步进倒计时可取消；429 读 Retry-After。
7. 技术栈固定：PySide6 + httpx + mss + keyboard + Pillow，不引入其它第三方依赖。

## 6. T25 扩展（缓存 / 错题本 / 讲解）

- **缓存键** = sha256( sha256(预处理后图片字节) + provider + model + sha256(prompt_extra) )。只做精确匹配：同网站同布局但题目不同的截图感知哈希可能相近，模糊命中会误答，宁可不命中。画面任何变化（时钟跳动等）不命中属预期。缓存的是最终结果（含复核后版本）；命中时状态条显示"缓存命中，未消耗额度"。设置高级页可开关/清空。
- **收藏**：题卡"收藏"→ favorites.json（题目全字段 + ts）；"导出复习笔记"按日期分组生成 exports/复习笔记_YYYYMMDD.md，状态条显示路径并直接打开。
- **追问讲解**：题卡"追问"→ RequestManager 提交纯文本请求（EXPLAIN_SYSTEM_PROMPT，受限流约束）→ explanation_ready 信号 → 讲解卡插在该题卡下方，可复制。新请求会取消进行中的讲解（latest-wins 一致语义）。