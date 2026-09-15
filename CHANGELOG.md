# Changelog

## 1.0.6 — 气泡卡面不透明修复

> 修复「提问气泡卡面透明、桌面内容透出来」的回归：1.0.0 修过一次（改用 QSS 白卡），1.0.5 换成手绘云朵气泡（自绘 paintEvent）后又出现。

- **卡面封实**：手绘底图 `assets/bubble.png` 的内芯 alpha 只有 214（84% 不透明），直接 9-slice 拉伸会让桌面/浏览器内容透过卡面文字。改为在底图轮廓内叠绘到 alpha 饱和（214 → 255），轮廓外的柔和羽边保持原样，手绘边缘不被硬切
- **影响范围**：提问提示气泡与状态/余额气泡共用 `BubbleCard`，两者同时受益
- **为什么只有提问气泡明显**：9-slice 只在上下各 30px 用原图，卡越高中间那条 84% 平铺占比越大——提问气泡约 71%，状态卡约 53%，所以提问气泡透得最刺眼
- 修正 `QuestionBubble` 的文档字符串（原文描述的是已废弃的 QSS 白卡实现）

## 1.0.5 — 云朵手绘气泡、自动收泡、独立化

> 桌面问答与状态气泡全新手绘质感 + 交互打磨；并移除对基座 `dsh-dafeiyu` 的依赖，本包可独立发布/安装。

- **手绘云朵气泡**：提问提示气泡与平时状态气泡改为手绘云朵底图（9-slice 拉伸，文字始终在壳内、随内容伸缩）
- **自动收泡**：网页端作答后，桌面提问气泡自动收起（无需手动关）；命中非等待状态即收
- **复用已有标签页**：「去网页作答」优先查找并激活已打开的 DSH 页面（按 `DSH`/主机标题匹配浏览器窗口），不再每次开新页
- **独立化**：`files` 加入 `assets/bubble.png`；移除对 `dsh-dafeiyu` 基座的依赖，本包自包含
- 框体、字号、按钮风格、内芯不透明度等按反馈微调

## 1.0.4 — 边角收缩、独立状态卡片、大小持久化

> 一批交互与视觉修复，并新增可回滚配置。

- **边角收缩**：桌宠拖到屏幕底角自动向下缩进，只露头顶（眼睛+呆毛）探出屏幕底；鼠标划过（150ms 防抖）弹出，移开/4 秒无交互自动回缩
- **可回滚状态卡片**：新增 `useSeparateCard` 开关（默认 `true`）——状态/余额卡片改用**独立悬浮窗口**（始终在屏幕内，不被桌宠窗口裁切）；设为 `false` 则回滚为旧的窗口内手绘卡片
- **卡片钳屏**：卡片/问答气泡在四个角落都强制显示在屏幕内，不再被吞
- **大小持久化**：右键"小/标准/大"改的大小，经宿主写回设置，重启后保持；"小"调整为 0.55
- **大小自愈**（随宿主新版）：settings 命名空间对齐，重启不再回退到最大
- **可拖到贴近顶部**：顶部限制放宽
- 宿主端新增 helper→host 的 `settings_config` 通道（右键改大小经此持久化）

## 1.0.3 — 宿主重启后余额自愈

> 修复 DSH 重启后余额失效的问题（插件启动早于凭据服务，key 解析为空且不重试）。

- **自愈机制**：插件启动时若 DeepSeek API key 尚未就绪，自动延时重试（每 4 秒，最多 6 次），一旦解析到 key 立即重启桌宠补上，无需手动禁用/启用
- 清理定时器生命周期，插件卸载时不留残留

## 1.0.2 — 余额查询体验修复

> 修复余额查询导致的卡顿，并大幅提速。

- **不再卡顿**：余额查询改到后台线程，查询期间桌宠动画照常播放，不再冻结 5-6 秒
- **秒出余额**：绕过本地代理直连 DeepSeek API（约 0.2s），并加入 60 秒缓存 + 启动预取，点击立即显示
- **不打断玩梗**：查询期间若你继续点击，查询结果只进缓存，不覆盖正在播放的玩梗/进度

## 1.0.1 — 文档修正

> 修正发布包内的安装说明：npm 包名统一为 `@piaobo_gz/dafeiyu-buchibaifan`。

## 1.0.0 — @piaobo_gz/dafeiyu-buchibaifan（Piaobo_GZ 社区福利版）

> 基于 `dsh-dafeiyu 0.1.0-alpha.8` 深度增强，作者 Piaobo_GZ 免费自费维护，
> 供社区使用与二次修改。新包名：`@piaobo_gz/dafeiyu-buchibaifan`。

### ✨ 新功能

- **实时余额显示**：点击大肥鱼第一下（或 6 秒冷却后）显示 DeepSeek 账户余额（¥ + 赠送/充值明细），直接查询官方 `/user/balance` 接口
- **浏览器外桌面问答**：Agent 调用 `ask_user_question` 时，在桌面气泡里直接作答——单选 / 多选 / 自定义输入全部支持，无需切回浏览器
  - 逐题弹出（第 X/Y 题），答完自动下一题，全部答完一次提交
  - 「跳过此题」可跳过当前问题
  - 「去网页回答」一键拉起/还原浏览器中已打开的 DSH 页面（复用原标签，不新开）
- **7 套专属动作素材**：摸摸脸 / 甩甩手 / 戳尾巴 / 拿扫把扫 / 跺跺脚 / 生气 / 开心（用户自绘帧 + 程序化动画）
- **53 条玩梗留言**：围绕「吃白饭的蓝色大肥鱼」的社区梗，按身体部位分区（头/脸/肚/手/脚/尾/通用），同部位第 3 次点击起从全池随机
- **点击会话模型**：6 秒窗口内连续点击延续互动（余额→玩梗/任务进度），超时回到待机
- **任务进度显示**：任务进行中点击显示当前待办/阶段/进度

### 🎨 UI / 视觉

- **气泡卡片化**：问题以圆角白卡 + 指向尾巴 + 下半渐变阴影的气泡显示，跟随大肥鱼位置，屏幕顶部时自动翻转到下方
- **Q 萌化**：幼圆字体、渐变蓝圆角按钮、圆角输入框
- **长文本自动换行**：超过单行的台词/问题自动换行完整显示，气泡高度自适应

### 🔧 修复

- **mux 传输修复**：`/api/events.mux` 只支持 WebSocket（普通 GET 返回 426），改用 Node 原生 WebSocket 连接并带断线重连，桌面问答不再丢答案
- **气泡透明修复**：放弃自绘 paintEvent（PyInstaller 打包后不可靠），改用 QSS 卡片 + QGraphicsDropShadowEffect 标准渲染
- **尾巴与卡片无缝**：三角形改为预渲染 pixmap + 舌头重叠卡片边缘，颜色统一
- **白底素材去底**：7 套动作 PNG 自动洪水填充去白底（保留鱼身白色高光）

### 📦 安装

```powershell
dsh plugin --profile web add @piaobo_gz/dafeiyu-buchibaifan
```

### ⚠️ 注意

- 本包包含 Windows x64 预构建 Helper（46.9 MB）
- 素材含用户自绘动作与社区梗，免费分发，无商业用途
- 作者信息：Piaobo_GZ

## 0.1.0-alpha.8

Packaging and DSH event-state hotfix release.

### Fixed

- Restored the Windows visual Helper after `0.1.0-alpha.7` was published without PySide6/Qt
- Stopped thinking-card copy from changing on every streamed assistant chunk ([#5](https://github.com/QCYTSN/dsh-dafeiyu/issues/5))
- Added real DSH `tool/result` call-ID paths so completed tools no longer leave stale working stages ([#6](https://github.com/QCYTSN/dsh-dafeiyu/issues/6))
- Added a dedicated waiting state for `ask_user_question`, `request_user_input`, and equivalent user-question tools ([#6](https://github.com/QCYTSN/dsh-dafeiyu/issues/6))

### Release safeguards

- The Windows build now fails before packaging unless the selected Python can import both PyInstaller and PySide6
- Every packaged Helper must start, complete the protocol handshake, render a real Qt snapshot with bundled assets, and shut down cleanly
- The public incident and resolution are tracked in [#7](https://github.com/QCYTSN/dsh-dafeiyu/issues/7)

### Update

Fully exit DSH, then run:

```powershell
dsh plugin --profile web update dsh-dafeiyu@alpha
```

Restart DSH after the update. Existing `0.1.0-alpha.7` users should update directly to this version.

## 0.1.0-alpha.7

> **Known broken release:** the published Windows Helper omitted PySide6/Qt. The WebUI settings
> panel loads, but the desktop companion cannot appear. Use `0.1.0-alpha.6` or update to
> `0.1.0-alpha.8`. See [#7](https://github.com/QCYTSN/dsh-dafeiyu/issues/7).

Animation and live-settings refinement release.

### Highlights

- 50 FPS standard rendering with 25 FPS retained for reduced-motion mode
- Subpixel positioning and smooth pixmap transforms for less stepped movement
- Short, non-flashing crossfades between larger pose and animation-frame changes
- Light procedural bob, sway, rotation, and breathing motion
- Multi-frame actions run roughly 10% faster while retaining readable character acting
- Independent live controls for character and status-card scale without restarting the Helper
- Live subagent preference changes preserve the active top-level project state

### Update

Fully exit DSH, then run:

```powershell
dsh plugin --profile web update dsh-dafeiyu@alpha
```

For a local DSH installation, run the equivalent command from its directory:

```powershell
pnpm exec dsh plugin --profile web update dsh-dafeiyu@alpha
```

Restart DSH after the update. Whole-package hot replacement is not supported by the current
DSH Host; live configuration changes remain available without restarting.

## 0.1.0-alpha.6

First public Windows Alpha of DSH BigFish / DSH 大肥鱼.

### Highlights

- Native transparent, frameless, always-on-top Windows companion owned by DSH
- Real DSH session states: idle, thinking, working, waiting, success, and error
- Project status card with project directory, current phase, active todo, and real todo progress
- Friendly Simplified Chinese status copy and 49-frame character runtime
- DSH WebUI settings for enable/disable, scale, activity, reduced motion, and subagents
- Helper heartbeat, crash restart, snapshot replay, and automatic exit with the DSH Host
- Bilingual Chinese/English GitHub documentation

### Install the Alpha

```powershell
dsh plugin --profile web add dsh-dafeiyu@alpha
```

If DSH is installed locally rather than globally:

```powershell
pnpm exec dsh plugin --profile web add dsh-dafeiyu@alpha
```

### Current limitations

- Windows 10/11 x64 only
- Settings and desktop status copy are currently Simplified Chinese
- Numeric progress requires a structured todo list from DSH
- Community Electron clients are not part of the supported compatibility scope

Code is MIT-licensed. Bundled character artwork has separate terms documented in
[ASSET_LICENSE.md](ASSET_LICENSE.md). This is an unofficial fan-made project and is not
affiliated with or endorsed by DeepSeek.
