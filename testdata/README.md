# 测试数据与验收清单

## 文件
| 文件 | 用途 |
|---|---|
| `quiz_page.png` | 整页 5 道题：热键 `Shift+Alt+S` 整屏截屏测试 |
| `quiz_single.png` | 单题大图：热键 `Shift+Alt+D` 框选测试（只框这道题） |

打开图片后用看图软件全屏（或缩放合适），再按热键。

## 预期答案（核对用）

### quiz_page.png（5 题）
| 题号 | 题型 | 正确答案 | 说明 |
|---|---|---|---|
| 1 | 单选 | B | TCP 三次握手：SYN → SYN+ACK → ACK |
| 2 | 单选 | C | MySQL 是关系型；Redis 键值、MongoDB 文档、HBase 列族 |
| 3 | 多选 | ACD | HTTP/DNS/FTP 应用层，TCP 是传输层 |
| 4 | 判断 | 对 | HTTPS 默认 443 |
| 5 | 单选 | B | 时间片用完 → 运行态转就绪态（A 是转阻塞，D 是终止） |

### quiz_single.png（1 题）
| 题号 | 题型 | 正确答案 |
|---|---|---|
| 1 | 多选 | AB（TCP/UDP 传输层；HTTP 应用层；IP 网络层） |

## 验收步骤
1. **整屏**：图片全屏 → `Shift+Alt+S` → 悬浮窗应在数秒内逐题出卡，答案与上表一致
2. **框选**：`Shift+Alt+D` → 拖框只圈住题目区域 → 应只返回框内题目
3. **速览复制**：`Shift+Alt+C` → 剪贴板应为 `1.B  2.C  3.ACD …` 格式
4. **缓存**：画面不变再按一次 `Shift+Alt+S` → 状态条显示"缓存命中，未消耗额度"，秒回
5. **收藏/导出**：任选一题点"收藏" → 底部"导出复习笔记" → 生成 `exports/复习笔记_YYYYMMDD.md` 并自动打开
6. **追问**：任一题点"追问" → 下方出现讲解卡（分步骤讲解）
7. **低置信度样式**：若某题置信度低于阈值，整卡淡黄；可在设置打开"自动复核"再测一次（会多一次带图调用）

## 自动化测试（无需图片）
```powershell
cd D:\Users\ff\Desktop\dati\screen-quiz-helper
python -m pytest tests -q      # 54 个离线用例
python probe_agentic.py        # 解析/流式/重试探针
```
测试全部走 MockTransport，不消耗 API 额度。