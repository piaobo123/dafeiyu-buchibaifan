<div align="center">

# BigFish：大肥鱼（不吃白饭版）

一个常驻 Windows 桌面的 AI 助手小伙伴，由 DeepSeek Harness 的真实工作状态驱动——增强版。

由 Piaobo_GZ 维护的免费社区福利，欢迎所有人使用与二次创作。

[更新日志](CHANGELOG.md) · [English](README_EN.md)

</div>

> 在 `dsh-dafeiyu` 的基础上深度增强。除原有的实时状态展示外，还新增了
> 余额实时查询、浏览器之外的桌面问答、7 套自定义动画以及 "53 条梗图台词"。

## ✅ 新增功能

| 功能 | 说明 |
|---|---|
| **余额实时查询** | 点击小肥鱼 → 显示你的 DeepSeek 账户余额（¥ + 赠送/充值明细） |
| **桌面问答** | 当 AI 助手向你提问时，直接在桌面气泡中作答：单选 / 多选 / 自由输入——无需切回浏览器 |
| **逐题作答** | 多题批处理时逐题弹出（第 X/Y 题）；答完一题再出下一题，全部答完后一次性提交 |
| **浏览器内作答** | 一键恢复/置顶 DSH 浏览器窗口（复用已有标签页，绝不新开窗口） |
| **7 套自定义动画** | 摸脸 / 挥手 / 戳尾巴 / 扫除 / 跺脚 / 生气 / 开心（专属逐帧动画） |
| **53 条梗图台词** | 以身体部位为主题的"吃白食的蓝色胖鱼"梗库；同一部位从第 3 次点击起从全库抽取 |
| **气泡卡片 UI** | 白色圆角卡片 + 指向气泡的尾巴 + 柔和阴影，跟随宠物移动，靠近屏幕顶部时自动翻到下方 |
| **圆润可爱外观** | 幼圆字体、渐变圆角按钮、圆角输入框、长文本自动换行 |

## 交互规则

| 操作 | 效果 |
|---|---|
| **单击（空闲时）** | 首次点击显示余额；6 秒内继续点击显示梗图台词（按身体部位：头 / 脸 / 肚子 / 手 / 脚 / 尾巴） |
| **单击（工作中）** | 首次点击显示余额；6 秒内继续点击显示任务进度（当前待办 / 阶段 / 进度） |
| **双击** | 随机触发身体部位互动 |
| **拖拽** | 可调整宠物位置，位置会被记住 |
| **右键菜单** | 大小 / 气泡大小 / 减少动效 / 隐藏 / 退出 |
| **6 秒冷却** | 超过 6 秒未点击则恢复空闲；下一次点击重新从显示余额开始 |

### 桌面问答气泡

当 AI 助手调用 `ask_user_question` 时：

- 小肥鱼上方会出现白色圆角气泡卡片（带指向尾巴和阴影），小肥鱼同时切换到等待姿势
- **单选** → 单选按钮；**多选** → 复选框；**无选项** → 文本输入
- 每个问题都提供"跳过"和"在浏览器中作答"
- 全部问题答完后，一次性统一提交，AI 助手继续运行

## 环境要求

- Windows 10/11 x64
- DeepSeek Harness WebUI（Node >= 22.19）
- 无需 Python / PySide6（发布包中已内置 Helper）

## 安装

```powershell
# 通过 npm 安装（发布名为 @piaobo_gz/dafeiyu-buchibaifan）
dsh plugin --profile web add @piaobo_gz/dafeiyu-buchibaifan

# 或通过本地 .tgz 文件安装
dsh plugin --profile web add "C:\path\piaobo_gz-dafeiyu-buchibaifan-1.0.2.tgz"
```

安装后重启 DSH —— 小肥鱼会出现在桌面右下角。

## 余额配置

余额显示会自动复用 DSH 中已配置的 `DEEPSEEK_API_KEY`（环境变量或
`~/.dsh/.credentials.yaml`），无需额外设置。点击小肥鱼即可查看实时余额。

## 开发与构建

```powershell
pnpm install
npm test
py -3 -m unittest discover -s runtime/tests -t .
# 重新构建 Windows Helper（需要 Python + PySide6 + PyInstaller）
python -m pip install -r requirements.txt pyinstaller
npm run build:helper:windows
```

## 资源与梗库

- 动画帧：`assets/pet/`（7 套自定义绘制的动画 + 原始帧）；`pet-manifest.json` 定义动画轨道
- 梗图台词：`runtime/helper.py` 顶部的 `PLAYFUL_*` 列表（53 条——欢迎自行添加）
- 自定义方式：编辑 `runtime/helper.py` 并重新构建 Helper

## 许可证

MIT —— 免费社区福利。随意使用、二次创作、分享。
