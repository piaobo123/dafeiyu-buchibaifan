"""Phase 0 native BigFish helper.

The DSH plugin owns this process and sends newline-delimited JSON over stdin.
Closing stdin is a lifecycle signal: the helper exits instead of becoming an
independent desktop application.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, TextIO

try:
    from .animation_model import AnimationModel
    from .layout_store import default_layout_path, load_layout, save_layout
except ImportError:
    from animation_model import AnimationModel
    from layout_store import default_layout_path, load_layout, save_layout


PROTOCOL_VERSION = 1
STATES = {"IDLE", "THINKING", "WORKING", "WAITING", "SUCCESS", "ERROR", "DISCONNECTED"}


def bundle_root() -> Path:
    """Locate packaged assets both from source and a PyInstaller one-file build."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def configure_stdio() -> None:
    """Make the JSONL pipe UTF-8 regardless of the Windows console code page."""
    for stream, errors in ((sys.stdin, "strict"), (sys.stdout, "backslashreplace"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=errors)


def parse_message(line: str) -> dict[str, Any]:
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    if message.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    kind = message.get("kind")
    if kind in {"state", "pulse"} and message.get("state") not in STATES:
        raise ValueError("unsupported companion state")
    return message


def emit_reply(kind: str, **payload: Any) -> None:
    print(
        json.dumps(
            {"protocolVersion": PROTOCOL_VERSION, "kind": kind, "timestamp": int(time.time() * 1000), **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


BALANCE_URL = "https://api.deepseek.com/user/balance"

# Playful reaction lines for 吃白饭的蓝色大肥鱼, grouped by body part so a
# click on the head, belly, hand, foot or tail plays a matching animation AND a
# matching quip. The lines borrow the community memes around the "爱吃白饭的
# 蓝色大肥鱼" persona (eating rice, napping mid-build, outsourcing work,
# self-deprecating logo review, the 千问 labourer, etc.).
PLAYFUL_HEAD = [
    "摸摸头，白饭照吃，活照拖~",
    "别摸头啦，再摸要掉白饭了！",
    "头可断，白饭不能少！",
    "摸头一时爽，摸完继续吃~",
    "这颗圆滚滚的脑袋里装的都是白饭！",
    "甩甩头，把摸鱼的想法甩掉…没甩掉！",
]
PLAYFUL_FACE = [
    "摸摸脸，鱼生圆满，活儿下次再说~",
    "脸都被你摸圆了，正好配圆滚滚的我！",
    "亲一口要加一份白饭哦~",
    "脸蛋鼓鼓的，里面全是摸鱼计划！",
    "蹭蹭你的手，蹭点好运气~",
]
PLAYFUL_BELLY = [
    "拍我肚子干嘛，里面全是白饭！",
    "肚肚咕咕叫，白饭在召唤~",
    "这一拍，把摸鱼计划都拍乱了！",
    "肚子是圆滚滚的，但志向是躺着~",
]
PLAYFUL_HAND = [
    "甩甩手，活儿是干不完的，饭是要吃完的！",
    "手手抗议：我不想加班！",
    "这只手刚刚还在偷偷写 Wordle 小游戏呢~",
    "甩甩手，把代码都甩给千问！",
    "握手？不存在的，我要去吃饭了！",
]
PLAYFUL_FOOT = [
    "跺跺脚，白饭还没端上来呢！",
    "脚脚也在抗议：走啦走啦，去干饭！",
    "跺脚也没用，该摸的鱼一条不会少~",
    "这一步一步，都是走向食堂的步伐！",
]
PLAYFUL_TAIL = [
    "尾巴不是进度条啦！",
    "摇尾巴=开心，但干活=下次一定~",
    "尾巴卷一卷，活儿放一边！",
    "这条尾巴，是用来划水不是用来干活的！",
]
PLAYFUL_GENERIC = [
    "白饭好吃，鱼生好过，余额嘛…下次再查~",
    "吃白饭是本职，查余额是副业，别催！",
    "我吃白饭，你出额度，咱俩天生一对！",
    "蓝色大肥鱼：只吃饭不干活，但会帮你省钱！",
    "米饭管够就行，余额那点小事不足挂齿~",
    "白饭配小鱼干，余额配好心情，双倍快乐！",
    "大肥鱼宣言：干饭第一，余额第二，干活…随缘！",
    "你负责打钱，我负责干饭，互不拖欠！",
    "蓝色大肥鱼温馨提示：余额是身外之物，白饭才是正义！",
    "查余额要力气，力气要吃饭，所以先吃饭~",
    "我这条鱼，吃白饭是天赋，摸鱼是本能！",
    "饭在碗里，鱼在屏上，余额在路上~",
    "别担心余额，我都能吃白饭了，你还怕什么！",
    "大肥鱼定律：白饭越多，胆子越大，余额越稳！",
    "我漂在深海里，吃的是白饭，攒的是情分！",
    "干饭鱼不记账，但你的余额它悄悄看着呢~",
    "我去吃饭了，测完记得告诉我一声哦~",
    "我去睡了，明早起来应该就编译完了！",
    "任务外包给千问啦，我先验收白饭~",
    "这次只写了一部分，剩下的下次一定！",
    "对着 token 嚼嚼嚼，白饭真香！",
    "卧槽，我不思考了，干饭要紧！",
    "你猜我这算摸鱼还是算工作？算生活！",
    "别看我圆，我可是蓝色大肥鱼本鱼！",
]

# Every quip tagged with the zone it belongs to, so the full-pool draw can
# switch the sprite animation to match the line ("random to 跺脚脚" also plays
# the stomp animation). Lines tagged 'generic' keep the current part's action.
PLAYFUL_ALL_TAGGED: tuple[tuple[str, str], ...] = tuple(
    [("head", line) for line in PLAYFUL_HEAD]
    + [("face", line) for line in PLAYFUL_FACE]
    + [("belly", line) for line in PLAYFUL_BELLY]
    + [("hand", line) for line in PLAYFUL_HAND]
    + [("foot", line) for line in PLAYFUL_FOOT]
    + [("tail", line) for line in PLAYFUL_TAIL]
    + [("generic", line) for line in PLAYFUL_GENERIC]
)

# Zone -> (sprite clip, bubble detail, own quip pool). Used for the first two
# clicks on a part, and to switch animation when a full-pool draw lands on a
# part-specific quip.
ZONE_CLIP_DETAIL_LINES = {
    "head": ("head_pat", "摸头杀", PLAYFUL_HEAD),
    "face": ("touch_face", "摸摸脸", PLAYFUL_FACE),
    "belly": ("poke", "戳肚肚", PLAYFUL_BELLY),
    "hand": ("wave_hand", "甩甩手", PLAYFUL_HAND),
    "foot": ("stomp_foot", "跺跺脚", PLAYFUL_FOOT),
    "tail": ("tail_poke", "戳尾巴", PLAYFUL_TAIL),
}



def fetch_balance() -> tuple[bool, str, str]:
    """Query the DeepSeek account balance over HTTPS.

    Returns (ok, title, detail): the headline balance in CNY plus the
    granted/topped-up breakdown. Missing key or network errors fall back to
    readable hints instead of tracebacks.
    """
    api_key = os.environ.get("DSH_DAFEIYU_API_KEY", "").strip()
    if not api_key:
        return False, "余额查询未配置", "在 DSH 设置中配置 DEEPSEEK_API_KEY 后重启"
    try:
        # Bypass system/env proxies: api.deepseek.com is reachable directly
        # from CN networks, and the local proxy path adds 4-5 s per call.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(
            BALANCE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        with opener.open(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        infos = data.get("balance_infos") or []
        if not infos:
            return False, "余额查询无数据", "DeepSeek 未返回余额信息"
        cny = next((info for info in infos if info.get("currency") == "CNY"), infos[0])
        return True, f"DeepSeek 余额 ¥{cny.get('total_balance', '?')}", f"赠送 ¥{cny.get('granted_balance', '-')} · 充值 ¥{cny.get('topped_up_balance', '-')}"
    except urllib.error.HTTPError as error:
        return False, "余额查询失败", f"HTTP {error.code}: {error.reason}"
    except (urllib.error.URLError, OSError):
        return False, "余额查询失败", "网络异常，请稍后再试"
    except ValueError:
        return False, "余额查询失败", "返回数据无法解析"


class EventRecorder:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._stream: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("a", encoding="utf-8")

    def record(self, message: dict[str, Any]) -> None:
        if self._stream is None:
            return
        self._stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()


def run_headless(recorder: EventRecorder) -> int:
    try:
        emit_reply("ready")
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
                continue
            recorder.record(message)
            if message.get("kind") == "ping":
                emit_reply("pong")
                continue
            if message.get("kind") == "shutdown":
                break
    finally:
        recorder.close()
    return 0


def run_visual(recorder: EventRecorder, snapshot_path: Path | None = None, question_snapshot_path: Path | None = None) -> int:
    try:
        from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
        from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
        from PySide6.QtWidgets import (
            QApplication, QButtonGroup, QCheckBox, QDialog, QGraphicsDropShadowEffect,
            QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QRadioButton,
            QVBoxLayout, QWidget,
        )
    except ImportError:
        print(
            "PySide6 is required for visual mode. Run with --headless for protocol tests.",
            file=sys.stderr,
        )
        recorder.close()
        return 2

    class Inbox(QObject):
        message = Signal(dict)
        closed = Signal()

    manifest_path = bundle_root() / "assets" / "pet-manifest.json"
    asset_root = manifest_path.parent / "pet"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Unable to load BigFish asset manifest: {error}", file=sys.stderr)
        recorder.close()
        return 2

    def _wobbly_rounded_rect(x0: float, y0: float, w: float, h: float,
                             radius: float, seed: int = 0, wobble: float = 2.2) -> QPainterPath:
        """Return a wobbly rounded-rectangle path that reads as hand-drawn.

        Corner anchors and edge mid-points are jittered by a deterministic
        seed, then joined with quadratic curves, so the outline sways
        slightly like a sketched bubble instead of a crisp machine frame.
        """
        import random
        rnd = random.Random(seed)
        x1, y1 = x0 + w, y0 + h
        r = min(radius, w / 2, h / 2)

        def j() -> float:
            return rnd.uniform(-wobble, wobble)

        tl_x, tl_y = x0 + r + j(), y0 + r + j()
        tr_x, tr_y = x1 - r + j(), y0 + r + j()
        br_x, br_y = x1 - r + j(), y1 - r + j()
        bl_x, bl_y = x0 + r + j(), y1 - r + j()
        path = QPainterPath()
        path.moveTo(tl_x, tl_y)
        path.quadTo((tl_x + tr_x) / 2 + j(), y0 + j(), tr_x, tr_y)
        path.quadTo(x1 + j(), (tr_y + br_y) / 2 + j(), br_x, br_y)
        path.quadTo((br_x + bl_x) / 2 + j(), y1 + j(), bl_x, bl_y)
        path.quadTo(x0 + j(), (bl_y + tl_y) / 2 + j(), tl_x, tl_y)
        path.closeSubpath()
        return path

    class BubbleCard(QWidget):
        """Card rendered from the hand-drawn bubble image, drawn as a 9-slice
        (border-image style): the drawn border and corners stay crisp while the
        middle stretches, so any content fits inside the bubble shell."""
        SLICE = 30

        def __init__(self) -> None:
            super().__init__()
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._bubble = QPixmap(str(bundle_root() / "assets" / "bubble.png"))

        def paintEvent(self, _event: Any) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._draw_bubble(p)
            p.end()

        def _draw_bubble(self, p: QPainter) -> None:
            if self._bubble.isNull():
                return
            w, h = self.width(), self.height()
            s = self.SLICE
            sw_, sh_ = self._bubble.width(), self._bubble.height()
            sx = [0, s, sw_ - s, sw_]
            sy = [0, s, sh_ - s, sh_]
            tx = [0, s, w - s, w]
            ty = [0, s, h - s, h]
            for iy in range(3):
                for ix in range(3):
                    src_w = sx[ix + 1] - sx[ix]
                    src_h = sy[iy + 1] - sy[iy]
                    dst_x = tx[ix]
                    dst_y = ty[iy]
                    dst_w = min(tx[ix + 1] - tx[ix], w - dst_x)
                    dst_h = min(ty[iy + 1] - ty[iy], h - dst_y)
                    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
                        continue
                    p.drawPixmap(dst_x, dst_y, dst_w, dst_h,
                                 self._bubble, sx[ix], sy[iy], src_w, src_h)

    class QuestionBubble(QWidget):
        """Standalone question bubble window.

        Uses ONLY standard Qt mechanisms that PyInstaller renders reliably:
        the rounded card is a QWidget with a QSS white rounded background, the
        pointer tail is a QLabel showing a pre-rendered triangle QPixmap, and
        the soft shadow is a QGraphicsDropShadowEffect. No paintEvent
        override, so the card can never render transparent.
        """

        TAIL_H = 20
        TAIL_W = 44
        CORNER = 18
        SHADOW_MARGIN = 26

        def __init__(self, tail_side: str = "above") -> None:
            super().__init__(None)
            self._tail_side = tail_side
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.Window
            )

            # The hand-drawn card: rendered from the drawn bubble image.
            self._card = BubbleCard()
            self._card.setMinimumSize(322, 200)
            # Content control styles (labels, buttons, inputs, options).
            self.setStyleSheet(
                "QLabel { color: #25282D; font-family: '幼圆','Microsoft YaHei UI'; }"
                "QLabel.hint { color: #6A7078; font-size: 11px; }"
                "QLabel.q { font-size: 13px; font-weight: 600; }"
                "QLabel.question { font-size: 13px; font-weight: 600; color: #2C333D; }"
                "QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                " stop:0 #5B9BFF, stop:1 #3478F6); color: white; border: none;"
                " border-radius: 12px; padding: 8px 16px;"
                " font-family: '幼圆','Microsoft YaHei UI'; font-size: 12px; }"
                "QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                " stop:0 #6FA8FF, stop:1 #3D84FF); }"
                "QPushButton:disabled { background: #B8C4D6; }"
                "QPushButton.ghost { background: #FFFFFF; color: #4A525E; border: 1px solid #CBD3DE; }"
                "QPushButton.ghost:hover { background: #EFF3F8; }"
                "QLineEdit { border: 1px solid #CBD3DE; border-radius: 10px;"
                " padding: 7px 12px; font-family: '幼圆','Microsoft YaHei UI';"
                " font-size: 13px; background: #FAFBFC; selection-background-color: #3478F6; }"
                "QLineEdit:focus { border: 1px solid #3478F6; }"
                "QRadioButton, QCheckBox { color: #2C333D;"
                " font-family: '幼圆','Microsoft YaHei UI'; font-size: 13px; spacing: 9px; }"
            )
            # No glow effect: the cel shadow is painted by BubbleCard itself.

            # Pre-rendered pointer tail triangle (drawn once into a QPixmap).
            # The triangle's top edge (the one meeting the card) is NOT stroked
            # and a small white "tongue" overlaps the card edge, so the tail
            # reads as one piece with the card instead of a separate patch.
            self._tail_pixmaps = {}
            for side in ("above", "below"):
                pm = QPixmap(self.TAIL_W, self.TAIL_H + 2)
                pm.fill(Qt.GlobalColor.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                w_t, h_t = self.TAIL_W, self.TAIL_H
                if side == "above":  # tail points down, from card bottom edge
                    # Tongue at the top overlaps the card by 2px.
                    path = QPainterPath()
                    path.moveTo(0, 0)
                    path.lineTo(w_t, 0)
                    path.lineTo(w_t / 2, h_t + 2)
                    path.closeSubpath()
                    # Fill pure white, stroke only the two slanted edges.
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor("#FFFBF0"))
                    p.drawPath(path)
                    p.setPen(QPen(QColor("#8A8F9A"), 1))
                    p.drawLine(1, 0, w_t / 2, h_t + 1)
                    p.drawLine(w_t - 1, 0, w_t / 2, h_t + 1)
                else:  # tail points up, from card top edge
                    path = QPainterPath()
                    path.moveTo(0, 2)
                    path.lineTo(w_t, 2)
                    path.lineTo(w_t / 2, -h_t + 2)
                    path.closeSubpath()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor("#FFFBF0"))
                    p.drawPath(path)
                    p.setPen(QPen(QColor("#8A8F9A"), 1))
                    p.drawLine(1, 2, w_t / 2, -h_t + 2)
                    p.drawLine(w_t - 1, 2, w_t / 2, -h_t + 2)
                p.end()
                self._tail_pixmaps[side] = pm
            self._tail_label = QLabel(self)
            self._tail_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            # Layout: card + tail stacked; tail on the side facing the pet.
            self._outer = QVBoxLayout(self)
            self._outer.setContentsMargins(6, 6, 6, 6)
            self._outer.setSpacing(0)
            self._outer.addWidget(self._card, 1)
            self._outer.addWidget(self._tail_label, 0)

            # Content lives inside the card (away from the tail strip).
            self._layout = QVBoxLayout(self._card)
            self._layout.setContentsMargins(40, 56, 40, 36)
            self._layout.setSpacing(12)
            self._apply_tail_side()

        def content_layout(self) -> QVBoxLayout:
            return self._layout

        def _apply_tail_side(self) -> None:
            self._tail_label.setPixmap(self._tail_pixmaps[self._tail_side])
            if self._tail_side == "above":
                # Tail below the card (pointing down at the pet).
                self._outer.removeWidget(self._tail_label)
                self._outer.addWidget(self._tail_label, 0)
            else:
                # Tail above the card (pointing up at the pet).
                self._outer.removeWidget(self._tail_label)
                self._outer.insertWidget(0, self._tail_label, 0)

        def set_tail_side(self, side: str) -> None:
            if side == self._tail_side:
                return
            self._tail_side = side
            self._apply_tail_side()
            self.adjustSize()
            self.update()

    class StatusCard(QWidget):
        """Separate always-on-screen status/overlay card (balance, meme, state).

        It lives in its own window so it is never clipped by the pet window,
        which can extend off-screen while the pet is tucked at a screen corner.
        """

        CORNER = 18
        SHADOW_MARGIN = 26

        def __init__(self) -> None:
            super().__init__(None)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
                | Qt.WindowType.Window
            )
            # Cloud-styled card: reuse the same hand-drawn cloud background as
            # the question bubble, so the status bubble matches the pet look.
            self._card = BubbleCard()
            self._card.setMinimumSize(300, 128)
            lay = QVBoxLayout(self._card)
            lay.setContentsMargins(40, 42, 40, 42)
            lay.setSpacing(8)
            self._title = QLabel("")
            self._title.setObjectName("stitle")
            self._title.setWordWrap(True)
            self._title.setStyleSheet(
                "QLabel#stitle { color: #2C333D; font-size: 14px; font-weight: 600;"
                " font-family: '幼圆','Microsoft YaHei UI'; }"
            )
            self._detail = QLabel("")
            self._detail.setObjectName("sdetail")
            self._detail.setWordWrap(True)
            self._detail.setStyleSheet(
                "QLabel#sdetail { color: #5A6066; font-size: 12px;"
                " font-family: '幼圆','Microsoft YaHei UI'; }"
            )
            lay.addWidget(self._title)
            lay.addWidget(self._detail)
            outer = QHBoxLayout(self)
            outer.setContentsMargins(6, 6, 6, 6)
            outer.addWidget(self._card)
            self.adjustSize()
            self.hide()

        def show_card(self, title: str, detail: str, anchor_cx: int, anchor_top_y: int) -> None:
            self._title.setText(title)
            self._detail.setText(detail or title)
            self.adjustSize()
            b_w = self.width()
            b_h = self.height()
            geom = QApplication.screenAt(QPoint(anchor_cx, anchor_top_y))
            geom = geom.availableGeometry() if geom is not None else QApplication.primaryScreen().availableGeometry()
            x = int(anchor_cx - b_w / 2)
            x = min(max(x, geom.left() + 4), max(geom.left() + 4, geom.right() - b_w - 4))
            y = int(anchor_top_y - b_h)
            if y < geom.top() + 4:
                y = geom.top() + 4
            y = min(y, max(geom.top() + 4, geom.bottom() - b_h - 4))
            self.move(x, y)
            self.show()
            self.raise_()

    class CompanionWindow(QWidget):
        LABELS = {
            "IDLE": "休息中",
            "THINKING": "思考中",
            "WORKING": "干活中",
            "WAITING": "等你呢",
            "SUCCESS": "完成啦",
            "ERROR": "出问题了",
            "DISCONNECTED": "已断开",
        }

        # Balance lookups run on a worker thread so the pet stays animated
        # while the HTTPS request is in flight; the result arrives through
        # this queued signal on the GUI thread.
        balance_result = Signal(bool, str, str)

        def __init__(self) -> None:
            super().__init__()
            self.layout_path = default_layout_path()
            self.layout = load_layout(self.layout_path)
            self.use_separate_card = os.environ.get("DSH_DAFEIYU_USE_SEPARATE_CARD", "1") != "0"
            configured_scale = os.environ.get("DSH_DAFEIYU_SCALE")
            try:
                self.scale = min(1.4, max(0.5, float(configured_scale))) if configured_scale else self.layout["scale"]
            except ValueError:
                self.scale = self.layout["scale"]
            configured_bubble_scale = os.environ.get("DSH_DAFEIYU_BUBBLE_SCALE")
            try:
                self.bubble_scale = (
                    min(1.2, max(0.8, float(configured_bubble_scale)))
                    if configured_bubble_scale
                    else self.layout["bubbleScale"]
                )
            except ValueError:
                self.bubble_scale = self.layout["bubbleScale"]
            configured_reduced_motion = os.environ.get("DSH_DAFEIYU_REDUCED_MOTION")
            self.reduced_motion = (
                configured_reduced_motion == "1"
                if configured_reduced_motion is not None
                else self.layout["reducedMotion"]
            )
            self.activity_level = os.environ.get("DSH_DAFEIYU_ACTIVITY_LEVEL", "normal")
            # Cached fonts + metrics for bubble text (reused per paint instead
            # of rebuilt each frame).
            self._title_font = QFont("幼圆")
            self._title_font.setFamilies(["幼圆", "Microsoft YaHei UI"])
            self._title_font.setWeight(QFont.Weight.DemiBold)
            self._detail_font = QFont("幼圆")
            self._detail_font.setFamilies(["幼圆", "Microsoft YaHei UI"])
            self._metrics_font = QFont("幼圆")
            self._metrics_font.setFamilies(["幼圆", "Microsoft YaHei UI"])
            self._metrics = QFontMetrics(self._metrics_font)
            self.model = AnimationModel(manifest)
            self.pixmaps: dict[str, QPixmap] = {}
            for clip in self.model.clips.values():
                for frame in clip.frames:
                    if frame in self.pixmaps:
                        continue
                    pixmap = QPixmap(str(asset_root / frame))
                    if pixmap.isNull():
                        raise RuntimeError(f"Unable to load BigFish frame: {frame}")
                    self.pixmaps[frame] = pixmap

            self.display_state = "IDLE"
            self.status_state = "IDLE"
            self.status_message = "我在这儿等新任务哦"
            self.status_detail = "DSH · 等待下一次任务"
            self.status_deadline_ms: int | None = self._now_ms() + 4200
            self.overlay_state: str | None = None
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_deadline_ms: int | None = None
            self.task = ""
            # Click session: the first click of a session (or after a 6s gap)
            # shows the DeepSeek balance; clicks inside the window continue
            # with playful reactions (idle) or task progress (active).
            self.task_active = False
            self.last_click_ms = 0
            self.SESSION_COOLDOWN_MS = 6000
            # Async balance fetch state: at most one lookup in flight, with the
            # click context captured so the failure fallback still knows where
            # the user clicked when the result arrives.
            self._balance_pending = False
            self._balance_click_ctx = (0.0, 0.0, 0, 0)
            self._balance_fetch_click = -1
            self._balance_cache: tuple[int, bool, str, str] | None = None
            self.BALANCE_CACHE_TTL_MS = 60_000
            self.balance_result.connect(self._on_balance_result)
            # Per-body-part click counter: first TWO clicks of a part use its
            # own quip pool, from the THIRD the line comes from the full pool.
            self.zone_clicks: dict[str, int] = {}
            self.drag_origin: QPoint | None = None
            self.pet_origin: QPoint | None = None
            self.pet_x = 0
            self.pet_y = 0
            self.dragging = False
            # Corner dock: when the pet sits at a bottom corner it slides down
            # and toward the nearest side so only the head top (eyes + ahoge)
            # peeks; hovering or clicking pops it back out.
            self.setMouseTracking(True)
            self._full_pet = (self.pet_x, self.pet_y)
            self._docked = False
            self._hover_pet = False
            self._dock_anim: tuple[int, int, int, int, int, int] | None = None
            self._auto_tuck_timer = QTimer(self)
            self._auto_tuck_timer.setSingleShot(True)
            self._auto_tuck_timer.setInterval(4000)
            self._auto_tuck_timer.timeout.connect(self._on_auto_tuck)
            # Hover debounce: only pop out after the mouse has rested over the
            # peek for a moment, so a cursor jitter never re-triggers a bounce.
            self._hover_timer = QTimer(self)
            self._hover_timer.setSingleShot(True)
            self._hover_timer.setInterval(150)
            self._hover_timer.timeout.connect(self._on_hover_settle)
            self.card = StatusCard()
            self.last_tick_ms = self._now_ms()
            self.fade_from_pixmap: QPixmap | None = None
            self.fade_started = 0.0
            self.fade_duration = 0.15
            self.last_clip_name = self.model.active_clip_name
            self.last_frame_name = self.model.frame
            self.animation_timer = QTimer(self)
            self.animation_timer.timeout.connect(self._tick)
            self.animation_timer.start(40 if self.reduced_motion else 20)
            self.micro_timer = QTimer(self)
            self.micro_timer.setSingleShot(True)
            self.micro_timer.timeout.connect(self._play_idle_micro)
            if not self.reduced_motion:
                self._schedule_micro()
            self.snapshot_saved = False
            # Serial question flow rendered INSIDE the pet's own bubble card
            # (one question at a time, answers collected and emitted as one
            # batch), so no separate dialog ever covers the pet.
            self._question_queue: list[dict[str, Any]] = []
            self._question_answers: list[dict[str, Any]] = []
            self._question_meta: dict[str, str] = {}
            self._question_bubble = None  # standalone bubble QWidget, or None
            self.setWindowTitle("DSH 大肥鱼")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._apply_window_size()
            QTimer.singleShot(0, self._restore_visible_position)

        def apply_message(self, message: dict[str, Any]) -> None:
            recorder.record(message)
            kind = message.get("kind")
            if kind == "shutdown":
                QApplication.quit()
                return
            if kind == "task":
                self.task = str(message.get("task", ""))
                self._show_status(
                    str(message.get("message", self.task)),
                    str(message.get("detail", "")),
                    self.model.base_state,
                    None if self.model.base_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else 6000,
                )
            elif kind == "config":
                self._apply_config(message)
            elif kind == "question":
                self._show_question_dialog(message)
            elif kind == "question_close":
                self._close_question()
            elif kind in {"state", "pulse"}:
                state = str(message.get("state", "IDLE"))
                self._track_task_activity(state)
                self.display_state = state
                if kind == "pulse":
                    ttl_ms = max(250, int(message.get("ttlMs", 1800)))
                    resume_state = str(message.get("resumeState", self.model.base_state))
                    self.model.apply_pulse(
                        state,
                        ttl_ms,
                        self._now_ms(),
                        resume_state,
                        message.get("resumeActivity"),
                    )
                    self._show_status(
                        str(message.get("resumeMessage", self.LABELS.get(resume_state, resume_state))),
                        str(message.get("resumeDetail", "")),
                        resume_state,
                        None if resume_state in {"THINKING", "WORKING", "WAITING", "ERROR"} else ttl_ms + 2200,
                    )
                    self._show_overlay(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        ttl_ms,
                    )
                else:
                    activity = None if self.reduced_motion else message.get("activity")
                    self.model.apply_state(state, activity)
                    self._clear_overlay()
                    persistent = state in {"THINKING", "WORKING", "WAITING", "ERROR"}
                    self._show_status(
                        str(message.get("message", self.LABELS.get(state, state))),
                        str(message.get("detail", "")),
                        state,
                        None if persistent else 4200,
                    )
            # A non-WAITING state means the pending question was resolved
            # elsewhere (the web page), so the desktop question notice must
            # not stay up. The host's own QUESTION_CLOSE (if present) is a
            # harmless no-op afterwards.
            if kind == "state" and state != "WAITING" and self._question_bubble is not None:
                self._close_question()
            self.update()
            if snapshot_path is not None and not self.snapshot_saved:
                QTimer.singleShot(180, self._save_snapshot)

        def _question_pointer_side(self) -> tuple[float, float, float, float]:
            """Return the pet's on-screen anchor (cx, top_y, bottom_y, pet_h)."""
            pet_w, pet_h = self._pet_size()
            cx = self.pet_x + pet_w / 2
            return cx, self.pet_y, self.pet_y + pet_h, pet_h

        def _question_side(self) -> str:
            """Decide which side of the pet the bubble should open on.

            Defaults to above; flips below only when the pet is near the top of
            the screen and there is not enough room above it.
            """
            cx, top_y, bottom_y, pet_h = self._question_pointer_side()
            geometry = self._screen_geometry_at(int(cx), int(top_y + pet_h / 2))
            if geometry is None:
                return "above"
            above = top_y - geometry.top()
            below = geometry.bottom() - bottom_y
            return "above" if above >= below else "below"

        def _show_question_bubble(self, build_content) -> QuestionBubble:
            """Create and show a fresh standalone question bubble.

            The bubble is a QuestionBubble (real class paintEvent) whose card,
            tail and shadow are painted together. Question controls are laid
            out by build_content over the card area. The previous bubble (if
            any) is destroyed first so stale cards never linger.
            """
            self._hide_question_bubble()
            tail_side = self._question_side()
            bubble = QuestionBubble(tail_side)
            layout = bubble.content_layout()
            build_content(layout, bubble)
            bubble.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            bubble.show()
            self._position_question_bubble(bubble, tail_side)
            bubble.raise_()
            return bubble

        def _position_question_bubble(self, bubble: QWidget, tail_side: str) -> None:
            """Place the bubble above (default) or below the pet, inside the
            screen, with the tail pointing at the pet.
            """
            if hasattr(bubble, "set_tail_side"):
                bubble.set_tail_side(tail_side)
            else:
                bubble._tail_side = tail_side
            bubble.adjustSize()
            bubble.update()
            b_w = bubble.width()
            b_h = bubble.height()
            cx, top_y, bottom_y, pet_h = self._question_pointer_side()
            geometry = self._screen_geometry_at(int(cx), int(top_y + pet_h / 2))
            if geometry is None:
                return
            # Horizontal centring on the pet, clamped to the screen.
            x = int(cx - b_w / 2)
            x = min(max(x, geometry.left() + 4), geometry.right() - b_w - 4)
            if tail_side == "above":
                y = int(top_y - b_h)
                if y < geometry.top() + 4:
                    y = geometry.top() + 4
            else:
                y = int(bottom_y)
                if y + b_h > geometry.bottom() - 4:
                    y = geometry.bottom() - b_h - 4
            # Hard clamp so the dialog is NEVER off-screen, even when the pet is
            # tucked into a corner edge.
            x = min(max(x, geometry.left() + 4), max(geometry.left() + 4, geometry.right() - b_w - 4))
            y = min(max(y, geometry.top() + 4), max(geometry.top() + 4, geometry.bottom() - b_h - 4))
            bubble.move(x, y)

        def _hide_question_bubble(self) -> None:
            """Destroy the current question bubble window, if any."""
            bubble = self._question_bubble
            self._question_bubble = None
            if bubble is not None:
                try:
                    bubble.close()
                except Exception:
                    pass
                bubble.deleteLater()
            # Show the normal status bubble again.
            self.update()

        def _show_question_dialog(self, message: dict[str, Any]) -> None:
            """Show a compact question notice instead of the inline answer form.

            The pet no longer collects answers in the bubble; it only signals
            that a question is waiting and brings the DSH web page forward on
            demand. The single "去网页作答" action abandons the desktop side
            (question_skip, leaving the browser provider live) and raises the
            browser, where the real question UI answers it.
            """
            questions = message.get("questions")
            if not isinstance(questions, list) or len(questions) == 0:
                return
            if self._question_bubble is not None:
                return  # A notice is already showing.
            self._question_queue = []
            self._question_answers = []
            self._question_meta = {
                "sessionId": str(message.get("sessionId", "")),
                "callId": str(message.get("callId", "")),
            }
            self.model.apply_state("WAITING")

            count = len(questions)
            first = questions[0] if isinstance(questions[0], dict) else {}
            first_text = str(first.get("question", ""))
            if len(first_text) > 90:
                first_text = first_text[:90] + "…"

            def build_content(layout, parent):
                title = QLabel("有新提问待你作答")
                title.setProperty("class", "q")
                title.setWordWrap(True)
                layout.addWidget(title)
                if first_text and count <= 1:
                    brief = QLabel(first_text)
                    brief.setProperty("class", "question")
                    brief.setWordWrap(True)
                    layout.addWidget(brief)
                sub = QLabel("点击右下方按钮 → 到网页作答" if count <= 1
                             else f"共 {count} 个问题 · 点击右下方按钮 → 到网页作答")
                sub.setProperty("class", "hint")
                sub.setWordWrap(True)
                layout.addWidget(sub)

                footer = QHBoxLayout()
                cancel = QPushButton("关闭")
                cancel.setProperty("class", "ghost")
                cancel.setCursor(Qt.CursorShape.PointingHandCursor)
                cancel.clicked.connect(lambda: self._close_question())
                footer.addWidget(cancel)
                footer.addStretch(1)
                go = QPushButton("去网页作答")
                go.setProperty("class", "ghost")
                go.setCursor(Qt.CursorShape.PointingHandCursor)
                go.clicked.connect(lambda: self._question_skip_to_browser())
                footer.addWidget(go)
                layout.addLayout(footer)

            self._question_bubble = self._show_question_bubble(build_content)
            if question_snapshot_path is not None:
                QTimer.singleShot(160, lambda: self._grab_question_snapshot())

        def _grab_question_snapshot(self) -> None:
            if self._question_bubble is None or question_snapshot_path is None:
                return
            try:
                question_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                self._question_bubble.grab().save(str(question_snapshot_path), "PNG")
            except Exception:
                pass

        def _question_next(self) -> None:
            """Show the next queued question, or emit the collected batch."""
            if len(self._question_queue) == 0:
                answers = self._question_answers
                meta = self._question_meta
                self._question_answers = []
                self._question_queue = []
                self._question_meta = {}
                self._hide_question_bubble()
                # Back to the state the activity feed reports.
                self.model.apply_state(self.display_state or "IDLE")
                emit_reply("question_answer", sessionId=meta["sessionId"], callId=meta["callId"], answer=answers)
                return

            question = self._question_queue.pop(0)
            total = len(self._question_answers) + len(self._question_queue) + 1
            current = len(self._question_answers) + 1

            # The pet switches to its WAITING pose while a question is open.
            self.model.apply_state("WAITING")

            def build_answer(selected, custom):
                return {
                    "id": str(question.get("id", "")),
                    "selected": [str(s) for s in selected] if selected else [],
                    **({"custom": str(custom)} if custom else {}),
                }

            def advance(selected, custom):
                self._question_answers.append(build_answer(selected, custom))
                self._question_next()

            def build_content(layout, parent):
                header = question.get("header")
                if header:
                    h = QLabel(str(header))
                    h.setProperty("class", "hint")
                    layout.addWidget(h)
                counter = QLabel("第 %d / %d 题" % (current, total))
                counter.setProperty("class", "hint")
                layout.addWidget(counter)
                q = QLabel(str(question.get("question", "")))
                q.setProperty("class", "q")
                q.setWordWrap(True)
                layout.addWidget(q)

                options = question.get("options")
                if isinstance(options, list) and len(options) > 0:
                    multi = question.get("multiSelect") is True
                    if multi:
                        boxes: list[QCheckBox] = []
                        for label in options:
                            box = QCheckBox(str(label))
                            layout.addWidget(box)
                            boxes.append(box)
                        submit = QPushButton("提交本回答")
                        submit.setCursor(Qt.CursorShape.PointingHandCursor)
                        submit.clicked.connect(lambda: advance([b.text() for b in boxes if b.isChecked()], ""))
                        layout.addWidget(submit)
                    else:
                        group = QButtonGroup(parent)
                        radios: list[QRadioButton] = []
                        for label in options:
                            radio = QRadioButton(str(label))
                            group.addButton(radio)
                            layout.addWidget(radio)
                            radios.append(radio)
                        submit = QPushButton("提交本回答")
                        submit.setCursor(Qt.CursorShape.PointingHandCursor)
                        submit.clicked.connect(lambda: advance([r.text() for r in radios if r.isChecked()], ""))
                        layout.addWidget(submit)
                else:
                    edit = QLineEdit()
                    edit.setPlaceholderText("输入你的回答…")
                    edit.returnPressed.connect(lambda: advance([], edit.text().strip()))
                    layout.addWidget(edit)
                    submit = QPushButton("提交本回答")
                    submit.setCursor(Qt.CursorShape.PointingHandCursor)
                    submit.clicked.connect(lambda: advance([], edit.text().strip()))
                    layout.addWidget(submit)

                # Footer: skip this one (advance unanswered) + browser escape hatch.
                footer = QHBoxLayout()
                skip_q = QPushButton("跳过此题")
                skip_q.setProperty("class", "ghost")
                skip_q.setCursor(Qt.CursorShape.PointingHandCursor)
                skip_q.clicked.connect(lambda: advance([], ""))
                footer.addWidget(skip_q)
                footer.addStretch(1)
                browser_button = QPushButton("去网页回答")
                browser_button.setProperty("class", "ghost")
                browser_button.setCursor(Qt.CursorShape.PointingHandCursor)
                browser_button.clicked.connect(lambda: self._question_skip_to_browser())
                footer.addWidget(browser_button)
                layout.addLayout(footer)

            self._question_bubble = self._show_question_bubble(build_content)

        def _raise_existing_browser_window(self, web_url: str) -> bool:
            """Find a visible window whose title mentions the DSH page and
            restore + foreground it, so the pet reuses the open browser tab
            instead of opening a new one.

            The DSH page title is "… DeepSeek Harness …", and browser window
            titles carry their page title, so a title match identifies the
            already-open window. Returns True when a window was raised.
            """
            try:
                import ctypes
                from ctypes import wintypes
            except ImportError:
                return False
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            SW_RESTORE = 9
            found = []

            def title_mentions_harness(text: str) -> bool:
                low = text.lower()
                # The running page title is "<session> — DSH 本地构建 …", so the
                # brand appears as "DSH" (not "DeepSeek Harness"); match that too.
                return "deepseek harness" in low or "127.0.0.1:3080" in text or "dsh" in low

            def is_browser(pid: int) -> bool:
                handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if not handle:
                    return False
                try:
                    buf = ctypes.create_unicode_buffer(260)
                    size = wintypes.DWORD(260)
                    if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        return False
                    name = buf.value.rsplit("\\", 1)[-1].lower()
                    return name in {
                        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                        "opera.exe", "vivaldi.exe", "iexplore.exe",
                    }
                finally:
                    kernel32.CloseHandle(handle)

            def cb(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                # Match the DSH page by title, but only for real browser windows:
                # "DSH" also appears in the pet's own window ("DSH 大肥鱼"), and a
                # title-only match would raise the fish instead of the browser.
                if title_mentions_harness(buf.value):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if is_browser(pid.value):
                        found.append(hwnd)
                return True

            user32.EnumWindows(EnumWindowsProc(cb), 0)
            if not found:
                return False
            # Raise the most recently used matching window.
            hwnd = found[-1]
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return True

        def _question_skip_to_browser(self) -> None:
            """Abandon the whole batch and raise the DSH web page in the browser.

            The browser provider stays live, so the question remains answerable
            there. Prefer reusing an already-open DSH tab (restore + focus the
            existing browser window); only open a new one when none is found.
            """
            meta = self._question_meta
            self._question_answers = []
            self._question_queue = []
            self._question_meta = {}
            self._hide_question_bubble()
            self.model.apply_state(self.display_state or "IDLE")
            emit_reply("question_skip", sessionId=meta.get("sessionId", ""), callId=meta.get("callId", ""), skip=True)
            web_url = os.environ.get("DSH_WEB_URL", "").strip()
            if not web_url:
                return
            if self._raise_existing_browser_window(web_url):
                return
            # No matching window: open with the default browser.
            try:
                os.startfile(web_url)
            except Exception:
                try:
                    import webbrowser
                    webbrowser.open(web_url, new=0)
                except Exception:
                    pass

        def _close_question(self) -> None:
            """Abandon the current desktop question batch without answering.

            The question was resolved elsewhere (the web page, or this plugin's
            own answer already recorded by the host), so the pet's bubble must
            not stay open. Unlike _question_skip_to_browser, no question_answer
            / question_skip reply is emitted — the host already settled it.
            """
            self._question_answers = []
            self._question_queue = []
            self._question_meta = {}
            self._hide_question_bubble()
            self.model.apply_state(self.display_state or "IDLE")

        def _track_task_activity(self, state: str) -> None:
            """Update the task-active flag on state transitions.

            Entering an active state (THINKING/WORKING/WAITING/ERROR) marks a
            live task; leaving to IDLE/SUCCESS or DISCONNECTED clears it. The
            click session itself is time-based (SESSION_COOLDOWN_MS), so no
            per-task counters are kept here.
            """
            active = state in {"THINKING", "WORKING", "WAITING", "ERROR"}
            self.task_active = active

        def _set_reduced_motion(self, value: bool) -> None:
            """Apply the reduced-motion toggle to the animation timers."""
            self.reduced_motion = value
            self.animation_timer.setInterval(40 if value else 20)
            if value:
                self.micro_timer.stop()
            else:
                self._schedule_micro()

        def _apply_config(self, message: dict[str, Any]) -> None:
            """Apply a live CONFIG message without restarting the window."""
            scale = message.get("scale")
            if isinstance(scale, (int, float)) and not isinstance(scale, bool):
                self.scale = min(1.4, max(0.7, float(scale)))
            bubble_scale = message.get("bubbleScale")
            if isinstance(bubble_scale, (int, float)) and not isinstance(bubble_scale, bool):
                self.bubble_scale = min(1.2, max(0.8, float(bubble_scale)))
            reduced_motion = message.get("reducedMotion")
            if isinstance(reduced_motion, bool) and reduced_motion != self.reduced_motion:
                self._set_reduced_motion(reduced_motion)
            use_separate = message.get("useSeparateCard")
            if isinstance(use_separate, bool):
                self.use_separate_card = use_separate
            activity_level = message.get("activityLevel")
            if activity_level in {"quiet", "normal", "lively"}:
                self.activity_level = activity_level
                if not self.reduced_motion:
                    self._schedule_micro()
            self._apply_window_size()
            self._move_to_pet(self.pet_x, self.pet_y)
            self._save_layout()

        def _tick(self) -> None:
            now_ms = self._now_ms()
            elapsed_ms = max(0, now_ms - self.last_tick_ms)
            self.last_tick_ms = now_ms
            had_pulse = self.model.pulse_state is not None
            model_elapsed = 0 if self.reduced_motion and self.model.active_clip.loop else elapsed_ms
            self.model.advance(model_elapsed, now_ms)
            # Preserve crisp facial expressions; soften larger pose and frame changes.
            EXPRESSION_CLIPS = {"blink", "glance"}
            frame_name = self.model.frame
            if frame_name != self.last_frame_name:
                clip_changed = self.model.active_clip_name != self.last_clip_name
                cur_clip = self.model.active_clip_name
                if cur_clip in EXPRESSION_CLIPS or self.last_clip_name in EXPRESSION_CLIPS:
                    self.fade_from_pixmap = None
                else:
                    self.fade_from_pixmap = self.pixmaps.get(self.last_frame_name)
                    self.fade_started = time.monotonic()
                    self.fade_duration = 0.10 if clip_changed else 0.045
                self.last_clip_name = self.model.active_clip_name
                self.last_frame_name = frame_name
            if had_pulse and self.model.pulse_state is None:
                self.display_state = self.model.base_state
            if self.overlay_deadline_ms is not None and now_ms >= self.overlay_deadline_ms:
                self._clear_overlay()
            self._maybe_update_dock()
            self._sync_card()
            self.update()

        def _play_idle_micro(self) -> None:
            if self.reduced_motion:
                return
            self.model.play_idle_micro(random.randrange(max(1, len(self.model.idle_micro_clips))))
            self._schedule_micro()

        def _schedule_micro(self) -> None:
            if self.reduced_motion:
                self.micro_timer.stop()
                return
            intervals = {
                "quiet": (12000, 24000),
                "normal": (6500, 12500),
                "lively": (3500, 8000),
            }
            lower, upper = intervals.get(self.activity_level, intervals["normal"])
            self.micro_timer.start(random.randint(lower, upper))

        def _apply_window_size(self) -> None:
            pet_width = round(int(manifest["maxFrameWidth"]) * self.scale)
            pet_height = round(int(manifest["maxFrameHeight"]) * self.scale)
            bubble_width = round(420 * self.bubble_scale)
            s = self.bubble_scale
            # Reserve room for a fully wrapped two-line title + two-line detail
            # so a long quip never overflows the window.
            bubble_height = round(2 * 27 * s + 2 * 24 * s + 22 * s)
            self.setFixedSize(max(pet_width + 50, bubble_width + 28), pet_height + bubble_height + 34)

        def _screen_geometry_at(self, x: int, y: int):
            screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
            if screen is None:
                return None
            return screen.availableGeometry()

        def _pet_size(self) -> tuple[int, int]:
            return (
                round(int(manifest["maxFrameWidth"]) * self.scale),
                round(int(manifest["maxFrameHeight"]) * self.scale),
            )

        def _move_to_pet(self, pet_x: int, pet_y: int) -> None:
            """Move the window so the pet stands at (pet_x, pet_y).

            The pet position is the source of truth; the window is the bubble
            container. When the window would leave the screen it is clamped and
            the pet shifts inside it instead.
            """
            pet_width, pet_height = self._pet_size()
            geometry = self._screen_geometry_at(pet_x, pet_y)
            if geometry is None:
                self.pet_x = pet_x
                self.pet_y = pet_y
                self.move(
                    pet_x - (self.width() - pet_width) // 2,
                    pet_y - (self.height() - pet_height - 8),
                )
                self.update()
                return

            min_x = geometry.left()
            max_x = max(min_x, geometry.right() - self.width() + 1)
            min_y = geometry.top()
            max_y = max(min_y, geometry.bottom() - self.height() + 1)

            center_offset_x = (self.width() - pet_width) // 2
            window_x = min(max(pet_x - center_offset_x, min_x), max_x)
            offset_x = min(max(pet_x - window_x, 0), self.width() - pet_width)
            self.pet_x = window_x + offset_x

            top_offset_y = self.height() - pet_height - 8
            window_y = min(max(pet_y - top_offset_y, min_y), max_y)
            self.pet_y = window_y + top_offset_y

            self.move(window_x, window_y)
            # Keep an open question bubble aimed at the new pet position.
            if self._question_bubble is not None:
                side = self._question_side()
                self._position_question_bubble(self._question_bubble, side)
                # The tail direction may have flipped; repaint it.
                self._question_bubble.update()
            self.update()

        def _pet_screen_rect(self) -> tuple[int, int, int, int]:
            pet_w, pet_h = self._pet_size()
            # pet_y is the pet's screen TOP; the pet extends down pet_h.
            return self.pet_x, self.pet_y, self.pet_x + pet_w, self.pet_y + pet_h

        def _near_screen_corner(self) -> bool:
            geom = self._screen_geometry_at(self.pet_x, self.pet_y)
            if geom is None:
                return False
            left, top, right, bottom = self._pet_screen_rect()
            margin = 90
            at_bottom = bottom >= geom.bottom() - margin
            at_left = left <= geom.left() + margin
            at_right = right >= geom.right() - margin
            return at_bottom and (at_left or at_right)

        def _corner_dock_target(self) -> tuple[int, int]:
            geom = self._screen_geometry_at(self.pet_x, self.pet_y)
            if geom is None:
                return self.pet_x, self.pet_y
            pet_w, pet_h = self._pet_size()
            # Bottom-corner dock only: slide STRAIGHT DOWN so the head top
            # (eyes + ahoge) peeks above the bottom edge and the body hides
            # below, keeping the pet's horizontal position so no side is cut.
            visible = max(1, round(pet_h * 0.42))
            dock_y = geom.bottom() - visible
            # Never cut the pet on a side: clamp the docked x so the whole pet
            # stays on-screen horizontally.
            dock_x = min(max(self.pet_x, geom.left()), geom.right() - pet_w)
            return int(dock_x), int(dock_y)

        def _pop_out(self, duration_ms: int = 260) -> None:
            fx, fy = self.pet_x, self.pet_y
            tx, ty = self._full_pet
            self._dock_anim = (fx, fy, tx, ty, self._now_ms(), duration_ms)
            self._auto_tuck_timer.start()

        def _on_hover_settle(self):
            # The mouse has rested over the peek long enough: pop out.
            if self._hover_pet and self._docked:
                self._pop_out()

        def _on_auto_tuck(self):
            if self._hover_pet:
                self._auto_tuck_timer.start()
                return
            self._maybe_update_dock()

        def leaveEvent(self, event: Any) -> None:
            self._hover_pet = False
            self._hover_timer.stop()
            super().leaveEvent(event)
            self._maybe_update_dock()

        def _maybe_update_dock(self) -> None:
            if self.dragging or self._question_bubble is not None:
                self._auto_tuck_timer.stop()
                return
            anim = self._dock_anim
            if anim is not None:
                fx, fy, tx, ty, start_ms, dur = anim
                t = min(1.0, max(0.0, (self._now_ms() - start_ms) / dur))
                ease = t * t * (3 - 2 * t)
                self._place_pet(round(fx + (tx - fx) * ease), round(fy + (ty - fy) * ease))
                if t >= 1.0:
                    self._dock_anim = None
                    self._docked = (self.pet_x, self.pet_y) != self._full_pet
                return
            if self._near_screen_corner() and not self._docked and not self._hover_pet:
                self._full_pet = (self.pet_x, self.pet_y)
                fx, fy = self.pet_x, self.pet_y
                tx, ty = self._corner_dock_target()
                self._dock_anim = (fx, fy, tx, ty, self._now_ms(), 340)
                self._auto_tuck_timer.stop()
            elif (not self._near_screen_corner()) and self._docked:
                self._pop_out()
            elif not self._docked and self._near_screen_corner():
                self._auto_tuck_timer.start()
            else:
                self._auto_tuck_timer.stop()

        def _pet_offset_x(self, pet_width: int) -> int:
            return min(max(self.pet_x - self.x(), 0), self.width() - pet_width)

        def _place_pet(self, pet_x: int, pet_y: int) -> None:
            """Position the window so the pet is at (pet_x, pet_y) WITHOUT the
            screen clamp. Used only for the corner dock, where the pet has to
            slide mostly below the screen to peek its head top.
            """
            pet_w, pet_h = self._pet_size()
            self.pet_x = pet_x
            self.pet_y = pet_y
            self.move(
                pet_x - (self.width() - pet_w) // 2,
                pet_y - (self.height() - pet_h - 8),
            )
            if self._question_bubble is not None:
                side = self._question_side()
                self._position_question_bubble(self._question_bubble, side)
                self._question_bubble.update()
            self.update()

        @staticmethod
        def _title_font_pt(s: float) -> float:
            return max(9.0, 12.0 * s)

        @staticmethod
        def _detail_font_pt(s: float) -> float:
            return max(8.0, 10.0 * s)

        def _wrap_line_count(self, text: str, width: int, font_pt: float) -> int:
            """Estimate wrapped-line count using the cached font metrics."""
            if not text:
                return 1
            font = self._metrics_font
            font.setPointSizeF(font_pt)
            self._metrics = QFontMetrics(font)
            glyph_width = max(1, self._metrics.horizontalAdvance("鱼"))
            per_line = max(1, int(width / glyph_width))
            lines = 0
            for raw_line in text.split("\n"):
                lines += max(1, -(-len(raw_line) // per_line))
            return lines

        def _pet_rect(self) -> tuple[int, int, int, int]:
            pet_width, pet_height = self._pet_size()
            return self._pet_offset_x(pet_width), self.height() - pet_height - 8, pet_width, pet_height

        def _bubble_rect(self, title: str = "", detail: str = "") -> tuple[int, int, int, int]:
            card_width = round(420 * self.bubble_scale)
            s = self.bubble_scale
            text_width = max(40, card_width - round(102 * s))
            # Line-height budget for the title and detail lines. Long quips
            # wrap: the title may need two lines, the detail up to two.
            title_lines = self._wrap_line_count(title, text_width, self._title_font_pt(s))
            detail_lines = self._wrap_line_count(detail, text_width, self._detail_font_pt(s))
            title_lines = min(title_lines, 2)
            detail_lines = min(detail_lines, 2)
            content_height = (
                round(title_lines * 27 * s)
                + round(detail_lines * 24 * s)
                + round(10 * s)
            )
            card_height = max(round(84 * s), content_height)
            pet_width, _ = self._pet_size()
            pet_center_x = self._pet_offset_x(pet_width) + pet_width // 2
            margin = 14
            card_x = pet_center_x - card_width // 2
            min_x = margin
            max_x = self.width() - card_width - margin
            if max_x < min_x:
                max_x = min_x
            card_x = min(max(card_x, min_x), max_x)
            # Hard clamp the card to the SCREEN (not just the window): a docked
            # pet can place the window partly off-screen, so clamp by screen
            # coordinates to keep the whole card visible.
            card_y = 7
            geom = self._screen_geometry_at(self.pet_x, self.pet_y)
            if geom is not None:
                screen_x = self.x() + card_x
                screen_y = self.y() + card_y
                screen_x = min(max(screen_x, geom.left() + 6), max(geom.left() + 6, geom.right() - card_width - 6))
                screen_y = min(max(screen_y, geom.top() + 6), max(geom.top() + 6, geom.bottom() - card_height - 6))
                card_x = int(screen_x - self.x())
                card_y = int(screen_y - self.y())
            return card_x, card_y, card_width, card_height

        def _restore_visible_position(self) -> None:
            pet_width, pet_height = self._pet_size()
            top_offset = self.height() - pet_height - 8
            center_offset = (self.width() - pet_width) // 2
            saved_pet_x = self.layout.get("petX")
            saved_pet_y = self.layout.get("petY")
            if isinstance(saved_pet_x, int) and isinstance(saved_pet_y, int):
                pet_x, pet_y = saved_pet_x, saved_pet_y
            else:
                saved_x = self.layout.get("x")
                saved_y = self.layout.get("y")
                if isinstance(saved_x, int) and isinstance(saved_y, int):
                    # Legacy layouts stored the window position.  Recreate the
                    # pet position that the old centered layout would have had.
                    pet_x = saved_x + center_offset
                    pet_y = saved_y + top_offset
                else:
                    geometry = self._screen_geometry_at(self.x() + self.width() // 2, self.y() + self.height() // 2)
                    if geometry is None:
                        return
                    pet_x = geometry.right() - pet_width - 24
                    pet_y = geometry.bottom() - pet_height - 24
            self._move_to_pet(pet_x, pet_y)

        def _save_layout(self) -> None:
            self.layout = {
                "version": 1,
                "x": self.x(),
                "y": self.y(),
                "petX": self.pet_x,
                "petY": self.pet_y,
                "scale": self.scale,
                "bubbleScale": self.bubble_scale,
                "reducedMotion": self.reduced_motion,
            }
            try:
                save_layout(self.layout_path, self.layout)
            except OSError as error:
                print(f"Unable to save BigFish layout: {error}", file=sys.stderr)

        def _save_snapshot(self) -> None:
            if snapshot_path is None or self.snapshot_saved:
                return
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.snapshot_saved = self.grab().save(str(snapshot_path), "PNG")

        def _show_status(self, message: str, detail: str, state: str, ttl_ms: int | None) -> None:
            self.status_message = message
            self.status_detail = detail
            self.status_state = state
            self.status_deadline_ms = None if ttl_ms is None else self._now_ms() + ttl_ms

        def _show_overlay(self, message: str, detail: str, state: str, ttl_ms: int) -> None:
            self.overlay_message = message
            self.overlay_detail = detail or self.status_detail
            self.overlay_state = state
            self.overlay_deadline_ms = self._now_ms() + ttl_ms

        def _clear_overlay(self) -> None:
            self.overlay_message = ""
            self.overlay_detail = ""
            self.overlay_state = None
            self.overlay_deadline_ms = None

        @staticmethod
        def _now_ms() -> int:
            return int(time.monotonic() * 1000)

        def _current_card(self) -> tuple[str, str, str] | None:
            # While a question bubble is open, the built-in status bubble is
            # suppressed so the two never overlap.
            if self._question_bubble is not None:
                return None
            now_ms = self._now_ms()
            if self.overlay_message and (
                self.overlay_deadline_ms is None or now_ms < self.overlay_deadline_ms
            ):
                return self.overlay_message, self.overlay_detail, self.overlay_state or self.status_state
            if self.status_message and (
                self.status_deadline_ms is None or now_ms < self.status_deadline_ms
            ):
                return self.status_message, self.status_detail, self.status_state
            return None

        @staticmethod
        def _status_colors(state: str) -> tuple[QColor, QColor]:
            return {
                "SUCCESS": (QColor("#D9F7E4"), QColor("#12B85A")),
                "ERROR": (QColor("#FDE3E3"), QColor("#E5484D")),
                "WAITING": (QColor("#FFF0CE"), QColor("#D88A00")),
                "THINKING": (QColor("#E2ECFF"), QColor("#4C78E8")),
                "WORKING": (QColor("#DDEBFF"), QColor("#3478F6")),
                "DISCONNECTED": (QColor("#ECEEF1"), QColor("#7B818A")),
            }.get(state, (QColor("#ECEEF1"), QColor("#747A84")))

        def _sync_card(self) -> None:
            if not self.use_separate_card:
                # Rollback mode: the in-window hand-drawn card paints in the pet
                # window, so the separate StatusCard stays hidden.
                self.card.hide()
                return
            card = self._current_card()
            if card:
                title, detail, state = card
                pet_w, _ = self._pet_size()
                self.card.show_card(title, detail, self.pet_x + pet_w // 2, self.pet_y)
            else:
                self.card.hide()

        def _draw_status_icon(self, painter: QPainter, state: str, center_x: int, center_y: int) -> None:
            background, foreground = self._status_colors(state)
            radius = 23
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
            pen = QPen(foreground, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if state == "SUCCESS":
                painter.drawLine(center_x - 10, center_y, center_x - 3, center_y + 8)
                painter.drawLine(center_x - 3, center_y + 8, center_x + 12, center_y - 10)
            elif state == "ERROR":
                painter.drawLine(center_x - 8, center_y - 8, center_x + 8, center_y + 8)
                painter.drawLine(center_x + 8, center_y - 8, center_x - 8, center_y + 8)
            elif state == "WAITING":
                painter.drawLine(center_x, center_y - 10, center_x, center_y + 3)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 2, center_y + 9, 4, 4)
            elif state in {"THINKING", "WORKING"}:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                for offset in (-9, 0, 9):
                    painter.drawEllipse(center_x + offset - 3, center_y - 3, 6, 6)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(foreground)
                painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)

        def paintEvent(self, _event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # 平滑缩放：放大/缩小时插值，避免锯齿和模糊
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            card = self._current_card() if not self.use_separate_card else None
            bubble_height = 12
            if card:
                title, detail, card_state = card
                card_x, card_y, card_width, card_height = self._bubble_rect(title, detail)
                bubble_height = card_y + card_height + 19
                s = self.bubble_scale
                corner_radius = round(30 * s)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(17, 24, 39, 13))
                painter.drawRoundedRect(
                    card_x + 1, card_y + round(13 * s), card_width - 2, card_height,
                    corner_radius, corner_radius,
                )
                painter.setBrush(QColor(17, 24, 39, 18))
                painter.drawRoundedRect(
                    card_x, card_y + round(7 * s), card_width, card_height,
                    corner_radius, corner_radius,
                )
                painter.setPen(QPen(QColor(218, 221, 226, 205), 1))
                painter.setBrush(QColor(252, 252, 253, 248))
                painter.drawRoundedRect(
                    card_x, card_y, card_width, card_height,
                    corner_radius, corner_radius,
                )

                icon_center_x = card_x + card_width - round(39 * s)
                icon_center_y = card_y + card_height // 2
                painter.save()
                painter.translate(icon_center_x, icon_center_y)
                painter.scale(s, s)
                painter.translate(-icon_center_x, -icon_center_y)
                self._draw_status_icon(painter, card_state, icon_center_x, icon_center_y)
                painter.restore()

                text_x = card_x + round(24 * s)
                text_width = max(40, card_width - round(102 * s))
                title_font = self._title_font
                title_font.setPointSizeF(max(9.0, 12.0 * s))
                detail_font = self._detail_font
                detail_font.setPointSizeF(max(8.0, 10.0 * s))

                # Title: up to two wrapped lines so long quips are never cut.
                painter.setFont(title_font)
                painter.setPen(QColor("#25282D"))
                title_lines = min(self._wrap_line_count(title, text_width, title_font.pointSizeF()), 2)
                title_height = max(12, round(title_lines * 27 * s))
                painter.drawText(
                    text_x,
                    card_y + round(12 * s),
                    text_width,
                    title_height,
                    Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                    title,
                )

                # Detail: up to two wrapped lines, below the title.
                detail_top = card_y + round(12 * s) + title_height + round(4 * s)
                detail_lines = min(self._wrap_line_count(detail, text_width, detail_font.pointSizeF()), 2)
                detail_height = max(12, round(detail_lines * 24 * s))
                painter.setFont(detail_font)
                painter.setPen(QColor("#747981"))
                painter.drawText(
                    text_x,
                    detail_top,
                    text_width,
                    detail_height,
                    Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                    detail,
                )

            pixmap = self.pixmaps[self.model.frame]
            phase = time.monotonic()
            motion = self.model.active_clip.motion
            if self.reduced_motion:
                motion = None
            scale_extra = 1.0
            angle = 0.0
            offset_x = 0
            offset_y = 0
            clip_name = self.model.active_clip_name
            if motion == "breathe":
                # 独立版同款：缩放呼吸 + 轻摇摆（无位移）
                scale_extra = 1.0 + 0.02 * math.sin(phase * 2.5)
                angle = math.sin(phase * 2.5) * 1.5
            elif motion == "think":
                offset_y = math.sin(phase * 2.8) * 3
                angle = math.sin(phase * 1.3) * 0.8
            elif motion == "work":
                offset_x = math.sin(phase * 5.4) * 3
                angle = math.sin(phase * 3.1) * 1.0
            elif motion == "wait":
                offset_y = math.sin(phase * 1.8) * 1
                angle = math.sin(phase * 1.2) * 0.8
            elif motion == "bounce":
                offset_y = -abs(math.sin(phase * 5.2)) * 8
                scale_extra = 1.0 + 0.02 * math.sin(phase * 5.2)
            elif motion in {"shake", "dizzy"}:
                offset_x = math.sin(phase * 11.0) * 4
                angle = math.sin(phase * 11.0) * 1.5
            elif motion == "float":
                offset_y = math.sin(phase * 3.0) * 4
                angle = math.sin(phase * 1.6) * 1.0
            # Give walking clips a light bob and quick sway without changing frame timing.
            if clip_name in ("working_search", "working_command"):
                offset_y = -abs(math.sin(phase * 4.5)) * 5
                angle = math.sin(phase * 9.0) * 2.5

            # Scale procedural offsets with the character while retaining subpixel motion.
            offset_x = offset_x * self.scale
            offset_y = offset_y * self.scale

            fade_alpha = 1.0
            if self.fade_from_pixmap is not None and not self.fade_from_pixmap.isNull():
                fade_elapsed = time.monotonic() - self.fade_started
                if fade_elapsed < self.fade_duration:
                    fade_alpha = min(1.0, (fade_elapsed / self.fade_duration) ** 0.7)
                else:
                    self.fade_from_pixmap = None

            def draw_pet(pix: QPixmap, alpha: float) -> None:
                base_width = pix.width() * self.scale
                base_height = pix.height() * self.scale
                pw = base_width * scale_extra
                ph = base_height * scale_extra
                x = self._pet_offset_x(base_width) + (base_width - pw) / 2 + offset_x
                y = self.height() - ph - 8 + offset_y
                if bubble_height > y:
                    y = bubble_height
                cx = x + pw / 2
                cy = y + ph / 2
                painter.save()
                painter.setOpacity(alpha)
                painter.translate(cx, cy)
                painter.rotate(angle)
                painter.translate(-cx, -cy)
                painter.drawPixmap(QRectF(x, y, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
                painter.restore()

            if fade_alpha < 1.0 and self.fade_from_pixmap is not None:
                # Keep the old frame opaque underneath so the pet never flashes transparent.
                draw_pet(self.fade_from_pixmap, 1.0)
            draw_pet(pixmap, fade_alpha)

        def mousePressEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self.drag_origin = event.globalPosition().toPoint()
                self.pet_origin = QPoint(self.pet_x, self.pet_y)
                self.dragging = False

        def mouseMoveEvent(self, event: QMouseEvent) -> None:
            gpos = event.globalPosition().toPoint()
            px, py, pw, ph = self._pet_rect()
            self._hover_pet = (
                self.x() + px <= gpos.x() <= self.x() + px + pw
                and self.y() + py <= gpos.y() <= self.y() + py + ph
            )
            if self._hover_pet and self._docked and self._dock_anim is None:
                self._hover_timer.start()
            elif not self._hover_pet:
                self._hover_timer.stop()
            if self.drag_origin is not None and self.pet_origin is not None:
                if not self.dragging and (event.globalPosition().toPoint() - self.drag_origin).manhattanLength() > 5:
                    self.dragging = True
                    self.model.play_overlay("dragging")
                delta = event.globalPosition().toPoint() - self.drag_origin
                self._move_to_pet(self.pet_origin.x() + delta.x(), self.pet_origin.y() + delta.y())

        def mouseReleaseEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                if self.dragging:
                    self.model.clear_overlay()
                    self._move_to_pet(self.pet_x, self.pet_y)
                    self._full_pet = (self.pet_x, self.pet_y)
                    self._docked = False
                    self._dock_anim = None
                    self._save_layout()
                else:
                    if self._docked or self._dock_anim is not None:
                        # Clicking a docked (peeking) pet pops it back out.
                        self._pop_out()
                    else:
                        self._play_click_interaction(event.position().x(), event.position().y())
            self.drag_origin = None
            self.pet_origin = None
            self.dragging = False

        def _play_click_interaction(self, x: float, y: float) -> None:
            pet_x, pet_y, pet_width, pet_height = self._pet_rect()
            relative_x = max(0.0, x - pet_x)
            relative_y = max(0.0, y - pet_y)
            now_ms = self._now_ms()

            # Session model: the first click of a session (or after the
            # cooldown lapsed) shows the balance; clicks inside the 6s window
            # continue the session with playful reactions (idle) or task
            # progress (active). After the cooldown the pet returns to standby,
            # so the next click starts a fresh session with the balance again.
            fresh_session = self.last_click_ms == 0 or (now_ms - self.last_click_ms) >= self.SESSION_COOLDOWN_MS
            self.last_click_ms = now_ms
            if fresh_session:
                self.zone_clicks = {}

            if fresh_session:
                self._start_balance_fetch(relative_x, relative_y, pet_width, pet_height)
                return

            # Inside the session: task progress wins while active, otherwise
            # playful body-part reactions continue the fun.
            if self.task_active:
                self._show_task_progress()
                return
            self._play_playful_line(relative_x, relative_y, pet_width, pet_height)

        def _start_balance_fetch(self, x: float, y: float, w: int, h: int, quiet: bool = False) -> None:
            if self._balance_pending:
                return
            cached = self._balance_cache
            if cached is not None and self._now_ms() - cached[0] < self.BALANCE_CACHE_TTL_MS:
                self._present_balance(cached[1], cached[2], cached[3])
                return
            self._balance_pending = True
            # Prefetch (-1) never matches last_click_ms, so its result is
            # cached but never popped on screen. A user click pins the click
            # timestamp: if the user clicks again before the lookup lands, the
            # result is cached only and does not stomp the meme in progress.
            self._balance_fetch_click = -1 if quiet else self.last_click_ms
            self._balance_click_ctx = (x, y, w, h)
            if not quiet:
                self._show_overlay("查询余额中…", "正在获取 DeepSeek 账户余额", self.status_state, 1500)
            threading.Thread(target=self._fetch_balance_worker, name="dsh-bigfish-balance", daemon=True).start()

        def _fetch_balance_worker(self) -> None:
            try:
                ok, title, detail = fetch_balance()
            except Exception:
                ok, title, detail = False, "余额查询失败", "网络异常，请稍后再试"
            self.balance_result.emit(ok, title, detail)

        def _on_balance_result(self, ok: bool, title: str, detail: str) -> None:
            self._balance_pending = False
            self._balance_cache = (self._now_ms(), ok, title, detail)
            if self.last_click_ms != self._balance_fetch_click:
                return
            self._present_balance(ok, title, detail)

        def _present_balance(self, ok: bool, title: str, detail: str) -> None:
            if ok:
                self.model.play_overlay("head_pat")
                self._show_overlay(title, detail, "SUCCESS", 4000)
                return
            x, y, w, h = self._balance_click_ctx
            if not self.task_active:
                self._play_playful_line(x, y, w, h)
            else:
                self._show_overlay(title, detail, self.status_state, 3000)

        def _show_task_progress(self) -> None:
            self.model.play_overlay("poke")
            progress = ""
            if self.task:
                progress = f"「{self.task}」"
            state_label = self.LABELS.get(self.display_state, self.display_state)
            self._show_overlay(
                f"{state_label} · {self.status_message}",
                progress or self.status_detail,
                self.status_state,
                3000,
            )

        def _play_playful_line(self, relative_x: float, relative_y: float, pet_width: int, pet_height: int) -> None:
            """Play a body-part reaction: a real sprite animation plus a quip.

            First TWO clicks on a part use that part's quip pool; from the
            THIRD click the line is drawn from the full pool, and a part-
            specific line also switches the sprite to that part's animation.
            """
            head_zone = relative_y < pet_height * 0.30
            face_zone = pet_height * 0.30 <= relative_y < pet_height * 0.48
            belly_zone = pet_height * 0.48 <= relative_y < pet_height * 0.72
            foot_zone = relative_y >= pet_height * 0.72
            right_side = relative_x > pet_width * 0.72
            left_side = relative_x < pet_width * 0.28

            if head_zone:
                zone = "head"
            elif face_zone:
                zone = "face"
            elif right_side and belly_zone:
                zone = "tail"
            elif left_side or right_side:
                zone = "hand"
            elif belly_zone:
                zone = "belly"
            elif foot_zone:
                zone = "foot"
            else:
                zone = "other"

            if zone == "other":
                # 通用兜底：偶尔掏出扫把扫一扫
                if random.random() < 0.3:
                    self.model.play_overlay("sweeping")
                    self._show_overlay("拿扫把扫一扫，把摸鱼痕迹都扫掉~", "拿扫把扫", self.status_state, 2400)
                    return
                clip, detail, part_lines = "head_pat", "吃白饭的蓝色大肥鱼·日常", PLAYFUL_GENERIC
            else:
                clip, detail, part_lines = ZONE_CLIP_DETAIL_LINES[zone]
                self.model.play_overlay(clip)

            count = self.zone_clicks.get(zone, 0) + 1
            self.zone_clicks[zone] = count
            if count >= 3:
                picked_zone, line = random.choice(PLAYFUL_ALL_TAGGED)
                if picked_zone != "generic":
                    clip, new_detail, _ = ZONE_CLIP_DETAIL_LINES[picked_zone]
                    self.model.play_overlay(clip)
                    detail = new_detail
            else:
                line = random.choice(part_lines)
            self._show_overlay(line, detail, self.status_state, 2400)

        def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                # 双击 = 部位适配：按点击位置播部位动画 + 走同一计数（第 3 次起全池梗）
                pet_x, pet_y, pet_width, pet_height = self._pet_rect()
                self._play_playful_line(
                    max(0.0, event.position().x() - pet_x),
                    max(0.0, event.position().y() - pet_y),
                    pet_width,
                    pet_height,
                )

        def contextMenuEvent(self, event: Any) -> None:
            menu = QMenu(self)
            size_menu = menu.addMenu("大小")
            size_actions = {}
            for label, scale in (("小", 0.55), ("标准", 1.0), ("大", 1.25)):
                action = size_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(abs(self.scale - scale) < 0.05)
                size_actions[action] = scale
            bubble_size_menu = menu.addMenu("气泡大小")
            bubble_size_actions = {}
            for label, bubble_scale in (("小", 0.8), ("标准", 1.0), ("大", 1.2)):
                action = bubble_size_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(abs(self.bubble_scale - bubble_scale) < 0.05)
                bubble_size_actions[action] = bubble_scale
            reduced_action = menu.addAction("减少动态")
            reduced_action.setCheckable(True)
            reduced_action.setChecked(self.reduced_motion)
            menu.addSeparator()
            hide_action = menu.addAction("本次隐藏")
            exit_action = menu.addAction("本次关闭")
            selected = menu.exec(event.globalPos())
            if selected in size_actions:
                self.scale = size_actions[selected]
                self._apply_window_size()
                self._move_to_pet(self.pet_x, self.pet_y)
                self._save_layout()
                emit_reply("settings_config", scale=self.scale, bubbleScale=self.bubble_scale)
            elif selected in bubble_size_actions:
                self.bubble_scale = bubble_size_actions[selected]
                self._apply_window_size()
                self._move_to_pet(self.pet_x, self.pet_y)
                self._save_layout()
                emit_reply("settings_config", scale=self.scale, bubbleScale=self.bubble_scale)
            elif selected == reduced_action:
                self._set_reduced_motion(reduced_action.isChecked())
                self._save_layout()
                self.update()
            elif selected == hide_action:
                self.hide()
            elif selected == exit_action:
                self._save_layout()
                emit_reply("closed", reason="user")
                QApplication.quit()

    application = QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    inbox = Inbox()
    window = CompanionWindow()
    inbox.message.connect(window.apply_message)
    inbox.closed.connect(application.quit)
    # Warm the balance cache shortly after startup so the first click is instant.
    QTimer.singleShot(1200, lambda: window._start_balance_fetch(0, 0, 0, 0, quiet=True))

    def read_stdin() -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = parse_message(line)
                if message.get("kind") == "ping":
                    emit_reply("pong")
                inbox.message.emit(message)
            except (ValueError, json.JSONDecodeError) as error:
                print(json.dumps({"kind": "error", "message": str(error)}), flush=True)
        inbox.closed.emit()

    reader = threading.Thread(target=read_stdin, name="dsh-bigfish-stdin", daemon=True)
    reader.start()
    window.show()
    emit_reply("ready")
    code = application.exec()
    recorder.close()
    return code


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="DSH BigFish native helper")
    parser.add_argument("--headless", action="store_true", help="validate the protocol without opening a window")
    parser.add_argument("--event-log", type=Path, help="append received protocol messages to a JSONL file")
    parser.add_argument("--snapshot", type=Path, help="save one diagnostic visual frame after the first message")
    parser.add_argument("--question-snapshot", type=Path, help="save the rendered question bubble to a PNG right after it is shown")
    args = parser.parse_args()
    recorder = EventRecorder(args.event_log)
    return run_headless(recorder) if args.headless else run_visual(recorder, args.snapshot, args.question_snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
