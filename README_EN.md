<div align="center">

# BigFish: No Free Lunch Edition 🐋

**An agent companion that lives on your Windows desktop and is driven by the real work state
of DeepSeek Harness — enhanced edition.**

Free community welfare maintained by **Piaobo_GZ**, for everyone to use and remix.

[Changelog](CHANGELOG.md) · [中文说明](README.md)

</div>

> Deeply enhanced from `dsh-dafeiyu`. On top of the original live status display, it adds
> **real-time balance queries**, **out-of-browser desktop Q&A**, **7 custom animations** and
> **53 meme lines**.

## ✨ Enhancements

| Feature | Description |
|---|---|
| **Real-time balance** | Click BigFish → shows your DeepSeek account balance (¥ + granted/topped-up breakdown) |
| **Desktop Q&A** | When the agent asks a question, answer right in the desktop bubble: single-choice / multi-choice / free input — no need to switch back to the browser |
| **One question at a time** | Multi-question batches pop one by one (question X/Y); answer each and the next appears, then everything is submitted at once |
| **Answer in browser** | One click restores/raises the DSH browser window (reuses the existing tab, never opens a new one) |
| **7 custom animations** | Touch face / wave hand / tail poke / sweep / stomp foot / angry / happy (dedicated frame animations) |
| **53 meme lines** | Body-part themed "blue big fish who eats free rice" meme pool; from the 3rd click on the same part it draws from the whole pool |
| **Bubble card UI** | Rounded white card + pointing tail + soft drop shadow, follows the pet, flips below when near the screen top |
| **Cute rounded look** | 幼圆 (Yuanti) font, gradient rounded buttons, rounded input fields, long text auto-wraps |

## Interaction rules

| Action | Effect |
|---|---|
| **Click (idle)** | First click shows the balance; further clicks within 6 s show meme lines (by body part: head / face / belly / hand / foot / tail) |
| **Click (working)** | First click shows the balance; further clicks within 6 s show task progress (current todo / phase / progress) |
| **Double-click** | Random part-matched interaction |
| **Drag** | Reposition the pet; position is persisted |
| **Right-click menu** | Size / bubble size / reduce motion / hide / quit |
| **6-second cooldown** | After 6 s without clicks the pet returns to idle; the next click starts from the balance again |

### Desktop Q&A bubble

When the agent calls `ask_user_question`:

- A rounded bubble card (white + pointing tail + shadow) appears above BigFish, which switches to a waiting pose
- **Single choice** → radio options; **multi-choice** → checkboxes; **no options** → text input
- Every question offers "skip" and "answer in browser"
- Once all questions are answered, everything is submitted in one request and the agent continues

## Requirements

- Windows 10/11 x64
- DeepSeek Harness WebUI (Node >= 22.19)
- No Python / PySide6 needed (the Helper is bundled in the published package)

## Install

```powershell
# From npm (published as @piaobo_gz/dafeiyu-buchibaifan)
dsh plugin --profile web add @piaobo_gz/dafeiyu-buchibaifan

# Or from a local .tgz
dsh plugin --profile web add "C:\path\piaobo_gz-dafeiyu-buchibaifan-1.0.1.tgz"
```

Restart DSH after installing — BigFish appears at the bottom-right of the desktop.

## Balance configuration

The balance display automatically reuses the `DEEPSEEK_API_KEY` already configured in DSH
(environment variable or `~/.dsh/.credentials.yaml`). No extra setup needed. Click BigFish to
see the live balance.

## Development & build

```powershell
pnpm install
npm test
py -3 -m unittest discover -s runtime/tests -t .
# Rebuild the Windows Helper (requires Python + PySide6 + PyInstaller)
python -m pip install -r requirements.txt pyinstaller
npm run build:helper:windows
```

## Assets & meme pool

- Animation frames: `assets/pet/` (7 custom-drawn animations + the original frames); `pet-manifest.json` defines the animation tracks
- Meme lines: the `PLAYFUL_*` lists at the top of `runtime/helper.py` (53 lines — feel free to add your own)
- To customize: edit `runtime/helper.py` and rebuild the Helper

## License

MIT — free community welfare. Use it, remix it, share it.
