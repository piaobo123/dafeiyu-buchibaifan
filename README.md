<div align="center">

# 大肥鱼（不吃白饭版）🐋

**住在 Windows 桌面上、由 DeepSeek Harness 真实工作状态驱动的 Agent 伴侣，增强版。**

由 **Piaobo_GZ** 免费自费维护的社区福利插件，供所有人使用与二次修改。

[更新日志](CHANGELOG.md) · [English](README_EN.md)

</div>

> 基于 `dsh-dafeiyu` 深度增强。除了原版的真实状态展示，还加入了**实时余额查询**、
> **浏览器外桌面问答**、**7 套专属动作**、**53 条玩梗留言**。

## ✨ 增强功能一览

| 功能 | 说明 |
|---|---|
| **实时余额显示** | 点击大肥鱼 → 显示 DeepSeek 账户余额（¥ + 赠送/充值明细） |
| **桌面问答** | Agent 提问时在桌面气泡里直接作答：单选/多选/自定义，不用切回浏览器 |
| **逐题作答** | 多问题批次逐题弹出（第 X/Y 题），答完自动下一题，全答完一次提交 |
| **去网页回答** | 一键还原/拉起浏览器中已打开的 DSH 页面（复用原标签，不新开） |
| **7 套专属动作** | 摸摸脸/甩甩手/戳尾巴/拿扫把扫/跺跺脚/生气/开心（专属帧动画） |
| **53 条玩梗** | 按身体部位分区的「吃白饭的蓝色大肥鱼」梗库，同部位第 3 次起全池随机 |
| **气泡卡片 UI** | 圆角白卡 + 指向尾巴 + 下半渐变阴影，跟随位置、屏幕顶部自动翻转下方 |
| **Q 萌化** | 幼圆字体、渐变蓝圆角按钮、圆角输入框、长文本自动换行 |

## 互动规则

| 操作 | 效果 |
|---|---|
| **点击（无任务）** | 第一下显示余额；6 秒内连续点击 → 玩梗留言（按点击部位：头/脸/肚/手/脚/尾） |
| **点击（有任务）** | 第一下显示余额；6 秒内连续点击 → 任务进度（当前待办/阶段/进度） |
| **双击** | 部位适配的随机互动 |
| **拖动** | 重新摆放，位置持久化 |
| **右键菜单** | 大小 / 气泡大小 / 减少动态 / 隐藏 / 关闭 |
| **6 秒冷却** | 超过 6 秒不点击回到待机，下次点击又从余额开始 |

### 桌面问答气泡

Agent 调用 `ask_user_question` 时：

- 大肥鱼头上浮出**圆角气泡卡片**（白色 + 指向尾巴 + 阴影），切换为等待姿势
- **单选** → 圆点选项；**多选** → 复选框；**无选项** → 输入框
- 每题有「跳过此题」和「去网页回答」
- 全部答完一次性提交，Agent 收到完整答案继续

## 系统要求

- Windows 10/11 x64
- DeepSeek Harness WebUI（Node >= 22.19）
- 不需要 Python / PySide6（Helper 已打包在发布包内）

## 安装

```powershell
# 从 npm（已发布为 @piaobo_gz/dafeiyu-buchibaifan）
dsh plugin --profile web add @piaobo_gz/dafeiyu-buchibaifan

# 或本地 .tgz
dsh plugin --profile web add "C:\path\piaobo_gz-dafeiyu-buchibaifan-1.0.1.tgz"
```

安装后重启 DSH，大肥鱼出现在桌面右下角。

## 余额查询配置

余额显示自动复用 DSH 已配置的 `DEEPSEEK_API_KEY`（环境变量或 `~/.dsh/.credentials.yaml`），
无需额外设置。点击大肥鱼即可看到实时余额。

## 开发与构建

```powershell
pnpm install
npm test
py -3 -m unittest discover -s runtime/tests -t .
# 重新打包 Windows Helper（需 Python + PySide6 + PyInstaller）
python -m pip install -r requirements.txt pyinstaller
npm run build:helper:windows
```

## 素材与梗库

- 动作帧：`assets/pet/`（含 7 套用户自绘动作 + 原版帧），`pet-manifest.json` 定义动画轨道
- 玩梗文案：`runtime/helper.py` 顶部的 `PLAYFUL_*` 列表（53 条，可自行增删）
- 想自定义：直接改 `runtime/helper.py` 后重新打包即可

## License

- 代码：MIT
- 素材：免费分发，无商业用途（详见 `ASSET_LICENSE.md`）

本项目为免费社区福利，与 DeepSeek 官方无关。
