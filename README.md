# ai-desktop-monitor（AI 桌面监控）

一个 Windows 常驻桌面小工具，把三件事合到一处：

- **悬浮面板（HUD）**：始终置顶的赛博朋克风格小面板——默认显示状态，逐会话展示 opencode / DeepSeek Harness 的会话进度（哪个在跑、哪个在等你、哪个已完成）；内置 QUOTA 折叠按钮，点击展开两级额度进度条
- **托盘图标**：实时显示智谱 AI / Z.ai 的 5 小时额度百分比仪表盘

整体为 Terminal HUD 深色风格：霓虹青/品红/终端绿、等宽字体、扫描线纹理、切角面板。

## 功能特性

### 悬浮面板（HUD，常驻置顶）

```
┌─ AGENT//STATUS ────────────── ◉ ALERT ─┐
│ ▌ [OC] 深度调研论文       ALERT Q1     │
│ ▎ [DSH] 论文修改            RUN···     │
│ ▏ [DSH] 环影运营            DONE       │
│ ░ · STANDBY ·                          │
│ :: OC 0 · DSH 3                 +1     │
│ ▸ QUOTA ────────────────────── 42%     │   ← 点击展开/收起
│ ▾ QUOTA                        42%     │
│   TOKEN · 5H                  42%      │   ← 展开后
│   ▮▮▮▮▮▮▮▮▮▮░░░░░░░░░░░░               │
│   RESET 09/08 18:00                    │
│   WEEKLY                      17%      │
│   ▮▮▮░░░░░░░░░░░░░░░░░░                │
└────────────────────────────────────────┘
```

- **状态区（默认显示）**：逐会话槽位（默认 3 槽，可配 1–6），按 状态优先级（告警 > 运行 > 完成）+ 最近活跃排序；`[OC]`/`[DSH]` 来源标签 + 会话名 + 状态标签 + `Q/P` 待决计数
- **赛博朋克视觉**：右上切角面板、扫描线纹理、霓虹青（运行，`RUN···` 动画点 + 脉冲）、霓虹品红（告警，边框闪烁）、暗绿（完成）、`· STANDBY ·`（空槽）
- **额度区（默认收起）**：点击 `▸ QUOTA` 折叠条展开——`TOKEN · 5H` / `WEEKLY` 分段方块进度条（余量色阶）+ 重置时间 + 错误行；折叠条右侧常显 5h 百分比
- **交互**：拖拽定位（右下角初始）、双击切换额度区、右键菜单（显示/收起额度 · 隐藏面板 · 设置）；托盘菜单「显示状态面板」随时开关
- 有会话溢出时状态区底部显示 `+N MORE`

### Agent 状态判定（opencode + DSH 双源）

| 状态 | 含义 |
|------|------|
| 🔴 ALERT 需要关注 | 有会话在提问或等待审批/权限（可气泡提醒） |
| 🟦 RUN 运行中 | Agent 正在处理（动画点 + 脉冲） |
| 🟢 DONE 已完成 | 会话空闲，任务结束 |
| ⚫ 未连接 | 两个来源均无活动会话 |

- **零配置**：自动检测 `~\.local\share\opencode\log` 与 `~\.dsh\sessions`，均可自定义
- **opencode 新旧日志格式兼容**
- **DSH 状态判定**：解析 `session.jsonl.zstd`（多 zstd frame JSONL）——`ask_user_question` 未闭环 = 提问待答，`approval/asked` 未配对 = 审批待决，`turn/start` 晚于 `turn/end` = 运行中；等待响应的会话不会因无写入而消失

### 额度监控

- **托盘图标仪表盘**：圆盘直接显示 5 小时额度整数百分比，颜色随余量变化（绿 → 橙 → 红）
- **HUD 额度区**：`TOKEN · 5H` / `WEEKLY` 两条 24 段方块进度条（与余量同色阶）+ 重置时间
- **定时刷新**：60–3600 秒可配，后台线程请求
- **多平台**：智谱开放平台（open.bigmodel.cn）与 Z.ai（api.z.ai）
- 额度查询失败时 HUD 额度区显示 `ERR:` 行，不影响状态监控；目录/依赖缺失亦有提示行

### 其他

- **单实例保护**、**崩溃日志**（`%APPDATA%\ai-desktop-monitor\crash.log`）

## 安装使用

```bash
pip install -r requirements.txt
python main.py
```

首次启动弹出设置窗口：填入 API Key 开始额度监控（留空则仅监控状态）。DSH 解析依赖 `zstandard` 库。

### 打包 exe

```bash
# 生成图标（可选，仓库已包含）
python generate_icon.py

pyinstaller --onefile --noconsole --icon "icons/app.ico" --add-data "icons/app.ico;icons" --name "ai-desktop-monitor" main.py
```

## 配置说明

配置保存在 `%APPDATA%\ai-desktop-monitor\config.json`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `api_key` | 空 | API Key（Base64 编码存储），留空则仅监控状态 |
| `platform` | `zhipu` | `zhipu`（智谱）或 `zai`（Z.ai） |
| `refresh_interval` | `300` | 额度刷新间隔（秒） |
| `opencode_log_dir` | 空 | opencode 日志目录，留空自动检测 |
| `dsh_sessions_dir` | 空 | DeepSeek Harness 会话目录，留空自动检测 |
| `notify_on_attention` | `true` | 变为需要关注时托盘气泡提醒 |
| `show_hud` | `true` | 悬浮面板开关 |
| `hud_slots` | `3` | HUD 会话槽位数（1–6） |

> **安全说明**：API Key 仅保存在本机配置文件中，不会上传到任何服务器。

## 操作速查

| 操作 | 效果 |
|------|------|
| 拖拽 HUD | 移动位置（常驻置顶） |
| 点击 `▸ QUOTA` 折叠条 / 双击 HUD | 展开 / 收起额度区 |
| 左键托盘 | 唤回 HUD 并展开额度区 |
| 右键 HUD | 菜单（显示/收起额度 / 隐藏面板 / 设置） |
| 右键托盘 | 菜单（状态行 / 刷新 / 查看额度 / 面板开关 / 设置 / 退出） |
| 悬停托盘 | Tooltip 显示两级额度百分比 |

## 项目结构

```
ai-desktop-monitor/
├── main.py                    入口：单实例、崩溃日志、全局字体
├── config.py                  配置读写（API Key Base64 编码）
├── app/
│   ├── tray.py                托盘主控制器：仪表盘图标、线程编排、气泡提醒
│   ├── status_hud.py          悬浮面板（状态槽位 + 可折叠额度区，赛博朋克风）
│   ├── settings_dialog.py     设置弹窗（额度 / 状态 / HUD）
│   ├── frameless.py           无边框弹窗基类（圆角 + 实色背景）
│   └── theme.py               Terminal HUD 主题与状态配色
├── services/
│   ├── quota_service.py       智谱 / Z.ai API 客户端与 Worker
│   ├── agent_watcher.py       双源目录扫描、逐会话明细与聚合
│   ├── log_tailer.py          opencode 单文件尾随与新旧日志格式解析
│   └── dsh_parser.py          DSH session.jsonl.zstd 解析
├── generate_icon.py           应用图标生成脚本
└── requirements.txt
```

## 状态判定细节

### opencode（新旧两种日志格式）

| 事件 | 新格式 | 旧格式 |
|------|--------|--------|
| Agent 循环开始 | `message=loop … step=N` | `step=N loop` |
| Agent 循环结束 | `message="exiting loop"` | `type=session.idle` |
| 提问 | `message=asking … que_` | `type=question.asked` |
| 提问回复 | `message=replied … que_` | `type=question.replied` |
| 权限请求 | `message=asking … per_` | `type=permission.asked` |
| 权限解决 | `message=evaluated … external_directory` | `type=permission.replied` |

### DeepSeek Harness（session.jsonl.zstd 事件）

| 事件 | 判定 |
|------|------|
| `tool/call`(ask_user_question) ↔ `tool/result` | 未闭环 = 提问待答 |
| `approval/asked` ↔ `approval/decided` | 未配对 = 审批待决 |
| `turn/start` / `turn/end` | start 晚于 end = 运行中 |
| `session/title` | 会话显示名 |

## 常见问题

**HUD 面板不见了？** 托盘右键勾选「显示状态面板」即可唤回。

**托盘图标数字是什么？** 5 小时窗口的已用额度百分比。颜色规则：<25% 绿、25–50% 亮绿、50–75% 橙、≥75% 红。

**槽位一直 STANDBY？** opencode 与 DSH 都没有活动会话（10 分钟内有写入才算活跃；DSH 中等待你回答/审批的会话除外），或目录配置错误，展开额度区查看提示行。

**DSH 显示"未连接"？** 确认 `~\.dsh\sessions` 存在且安装了 `zstandard`（`pip install zstandard`）。

**额度查询失败？** 检查 API Key 与网络；错误显示在托盘通知与 HUD 额度区 `ERR:` 行，不影响状态监控。

## License

[MIT](./LICENSE)
