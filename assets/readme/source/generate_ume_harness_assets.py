"""Generate bilingual UME-HARNESS README assets.

The Human Layer animation stops at preview. SVG outputs explain responsibility
and presentation only; none of these assets grants authority or records work.
"""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import sys
from textwrap import wrap

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - build-host preflight
    raise SystemExit("README asset generation requires Python 3.12 or newer") from exc

from PIL import Image, ImageDraw, ImageFont


MIN_PYTHON = (3, 12)
if sys.version_info < MIN_PYTHON:  # pragma: no cover - build-host preflight
    raise SystemExit("README asset generation requires Python 3.12 or newer")

CONTRACT_PATH = Path(__file__).with_name("asset-build.toml")
CONTRACT = tomllib.loads(CONTRACT_PATH.read_text("utf-8"))
if CONTRACT.get("schema") != "ume-harness-readme-assets.v1":
    raise SystemExit("unsupported README asset contract")
PACK_PATH = Path(__file__).resolve().parents[3] / "common-language/packs/ja-JP/p0_concepts.json"
PACK = json.loads(PACK_PATH.read_text("utf-8"))["concepts"]

WIDTH, HEIGHT = int(CONTRACT["width"]), int(CONTRACT["height"])
POSTER_WIDTH, POSTER_HEIGHT = int(CONTRACT["poster_width"]), int(CONTRACT["poster_height"])
RESPONSIBILITY_WIDTH = int(CONTRACT["responsibility_width"])
RESPONSIBILITY_HEIGHT = int(CONTRACT["responsibility_height"])
CARDS_WIDTH = int(CONTRACT["cards_width"])
CARDS_HEIGHT = int(CONTRACT["cards_height"])
FPS = int(CONTRACT["fps"])
SCENES = 5
FRAME_COUNT = int(CONTRACT["frame_count"])
DURATION_MS = int(CONTRACT["duration_ms"])
NORMAL_WEIGHT = int(CONTRACT["normal_weight"])
BOLD_WEIGHT = int(CONTRACT["bold_weight"])
if FRAME_COUNT % SCENES:
    raise SystemExit("frame_count must divide evenly across scenes")
if FRAME_COUNT * 1000 != FPS * DURATION_MS:
    raise SystemExit("frame_count, duration_ms, and fps are inconsistent")
FRAMES_PER_SCENE = FRAME_COUNT // SCENES

BG = "#f8fafc"
PAPER = "#ffffff"
INK = "#202b38"
MUTED = "#64748b"
BLUE = "#315f9f"
BLUE_LIGHT = "#e6eef9"
GREEN = "#16705a"
GREEN_LIGHT = "#dcf1e9"
ORANGE = "#b56817"
ORANGE_LIGHT = "#fff0d7"
RED = "#b93838"
RED_LIGHT = "#fde8e8"
PURPLE = "#7356a8"
PURPLE_LIGHT = "#eee8fb"
CYAN = "#237e91"
CYAN_LIGHT = "#def3f6"
LINE = "#cbd5e1"
SOFT = "#f1f5f9"

COPY = {
    "ja": {
        "title": "日本語Human Layer — 作業前のプレビュー",
        "subtitle": "曖昧な依頼を、確認できる範囲と確認が必要な操作へ整理する",
        "human": "人間の依頼",
        "request": "この資料をまとめて、\n必要ならREADMEも\nいい感じに直しといて",
        "harness": "UME-HARNESS",
        "do_title": "確認なしで進めてよい内容",
        "do_lines": ("候補の操作を表示", "内容を整理", "質問をまとめる"),
        "confirm_title": "実行前に確認が必要な操作",
        "confirm_lines": ("あなたの確認が必要です",),
        "not_title": "まだ実行していないこと",
        "not_lines": ("ファイル操作など",),
        "done": "プレビュー完了",
        "unchanged": "まだ何も変更していません",
        "scene_titles": (
            "普通の曖昧な依頼から始める",
            "確認できる範囲を表示する",
            "決められない点をまとめて確認する",
            "まだ実行していないことを示す",
            "作業前のプレビューで止まる",
        ),
        "footer": "単体CLIはプレビューと報告まで。ファイル操作を実行しません。",
    },
    "en": {
        "title": "Human Layer — preview before work",
        "subtitle": "Turn an imperfect request into visible scope and actions requiring confirmation",
        "human": "Human request",
        "request": "Please organize the\nmaterial and improve\nthe README if useful.",
        "harness": "UME-HARNESS",
        "do_title": "May proceed without confirmation",
        "do_lines": ("Show candidate actions", "Organize the request", "Group questions"),
        "confirm_title": "Needs your confirmation before work",
        "confirm_lines": ("Your confirmation is required",),
        "not_title": "Has not run yet",
        "not_lines": ("File operations",),
        "done": "Preview complete",
        "unchanged": "Nothing has been changed",
        "scene_titles": (
            "Start with an ordinary, imperfect request",
            "Show the visible scope",
            "Group unresolved choices for confirmation",
            "Show what has not run yet",
            "Stop at the pre-work preview",
        ),
        "footer": "The standalone CLI stops at preview / report and performs no file operations.",
    },
}

FONT_PATH: Path


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    result = ImageFont.truetype(str(FONT_PATH), size)
    result.set_variation_by_axes([BOLD_WEIGHT if bold else NORMAL_WEIGHT])
    return result


def centered(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, size: int, *, color: str = INK, bold: bool = False) -> None:
    current = load_font(size, bold=bold)
    box = draw.textbbox((0, 0), value, font=current)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2), value, font=current, fill=color)


def lines_in_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    values: tuple[str, ...] | list[str],
    size: int,
    *,
    color: str = INK,
    bold: bool = False,
    marker: str | None = None,
    gap: int = 6,
) -> None:
    current = load_font(size, bold=bold)
    x0, y0, x1, y1 = box
    heights = [draw.textbbox((0, 0), value, font=current)[3] for value in values]
    total = sum(heights) + gap * max(0, len(values) - 1)
    y = (y0 + y1 - total) / 2
    for value, height in zip(values, heights, strict=True):
        shown = f"{marker} {value}" if marker else value
        draw.text((x0, y), shown, font=current, fill=color)
        y += height + gap


def centered_lines(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    values: tuple[str, ...] | list[str],
    size: int,
    *,
    color: str = INK,
    bold: bool = False,
    gap: int = 6,
) -> None:
    current = load_font(size, bold=bold)
    x0, y0, x1, y1 = box
    bounds = [draw.textbbox((0, 0), value, font=current) for value in values]
    heights = [bound[3] - bound[1] for bound in bounds]
    total = sum(heights) + gap * max(0, len(values) - 1)
    y = (y0 + y1 - total) / 2
    for value, bound, height in zip(values, bounds, heights, strict=True):
        width = bound[2] - bound[0]
        draw.text(((x0 + x1 - width) / 2, y), value, font=current, fill=color)
        y += height + gap


def panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill: str, outline: str, active: bool) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=6 if active else 2)


def draw_preview(locale: str, scene: int | None, progress: float = 1.0) -> Image.Image:
    copy = COPY[locale]
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    centered(draw, WIDTH // 2, 35, copy["title"], 34, bold=True)
    centered(draw, WIDTH // 2, 76, copy["subtitle"], 22, color=MUTED)

    human_box = (35, 120, 350, 470)
    draw.rounded_rectangle(human_box, radius=28, fill=BLUE_LIGHT, outline=BLUE, width=5 if scene == 0 else 3)
    centered(draw, 192, 160, copy["human"], 26, color=BLUE, bold=True)
    request_lines = tuple(copy["request"].splitlines())
    lines_in_box(draw, (65, 205, 320, 410), request_lines, 22, color=BLUE, bold=scene == 0, gap=10)

    draw.line((350, 295, 395, 295), fill=BLUE, width=5)
    draw.polygon(((398, 295), (382, 285), (382, 305)), fill=BLUE)

    card = (405, 105, 1165, 500)
    draw.rounded_rectangle(card, radius=28, fill=PAPER, outline=GREEN, width=5)
    centered(draw, 785, 137, copy["harness"], 26, color=GREEN, bold=True)

    do_box = (435, 165, 1135, 255)
    confirm_box = (435, 270, 1135, 355)
    not_box = (435, 370, 1135, 455)
    panel(draw, do_box, fill=GREEN_LIGHT if scene in (1, None) else SOFT, outline=GREEN, active=scene == 1)
    panel(draw, confirm_box, fill=ORANGE_LIGHT if scene in (2, None) else SOFT, outline=ORANGE, active=scene == 2)
    panel(draw, not_box, fill=RED_LIGHT if scene in (3, None) else SOFT, outline=RED, active=scene == 3)

    draw.text((460, 180), copy["do_title"], font=load_font(20, bold=True), fill=GREEN)
    lines_in_box(draw, (850, 176, 1110, 245), copy["do_lines"], 18, marker="✓", gap=2)
    draw.text((460, 285), copy["confirm_title"], font=load_font(20, bold=True), fill=ORANGE)
    lines_in_box(draw, (850, 283, 1110, 340), copy["confirm_lines"], 18, marker="?")
    draw.text((460, 385), copy["not_title"], font=load_font(20, bold=True), fill=RED)
    lines_in_box(draw, (850, 378, 1110, 445), copy["not_lines"], 18, marker="×", gap=2)

    done_fill = GREEN_LIGHT if scene in (4, None) else SOFT
    draw.rounded_rectangle((405, 515, 1165, 565), radius=15, fill=done_fill, outline=GREEN, width=5 if scene == 4 else 2)
    centered(draw, 600, 540, copy["done"], 22, color=GREEN, bold=True)
    centered(draw, 925, 540, copy["unchanged"], 22, color=GREEN, bold=True)

    if scene is not None:
        start, end, y = 190, 1010, 590
        draw.line((start, y, end, y), fill=LINE, width=3)
        for index in range(SCENES):
            x = start + int((end - start) * index / (SCENES - 1))
            fill = GREEN if index <= scene else PAPER
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=fill, outline=GREEN, width=2)
        cursor = start + int((end - start) * progress)
        draw.ellipse((cursor - 8, y - 8, cursor + 8, y + 8), fill=GREEN, outline=PAPER, width=2)
        centered(draw, WIDTH // 2, 623, copy["scene_titles"][scene], 24, bold=True)

    centered(draw, WIDTH // 2, 657, copy["footer"], 18, color=MUTED)
    return image


def draw_poster(locale: str) -> Image.Image:
    copy = COPY[locale]
    image = Image.new("RGB", (POSTER_WIDTH, POSTER_HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    center_x = POSTER_WIDTH // 2
    centered(draw, center_x, 34, copy["title"], 30, bold=True)
    subtitle = wrap(copy["subtitle"], width=47 if locale == "en" else 26, break_long_words=False)
    centered_lines(draw, (45, 60, 675, 105), subtitle, 20, color=MUTED, gap=3)

    human_box = (45, 120, 675, 285)
    draw.rounded_rectangle(human_box, radius=24, fill=BLUE_LIGHT, outline=BLUE, width=4)
    centered(draw, center_x, 152, copy["human"], 25, color=BLUE, bold=True)
    request_lines = tuple(copy["request"].splitlines())
    centered_lines(draw, (75, 180, 645, 265), request_lines, 22, color=BLUE, gap=6)

    draw.line((center_x, 285, center_x, 325), fill=BLUE, width=4)
    draw.polygon(((center_x, 330), (center_x - 9, 315), (center_x + 9, 315)), fill=BLUE)
    centered(draw, center_x, 350, copy["harness"], 26, color=GREEN, bold=True)

    boxes = (
        ((45, 380, 675, 500), copy["do_title"], copy["do_lines"], GREEN_LIGHT, GREEN, "✓"),
        ((45, 520, 675, 625), copy["confirm_title"], copy["confirm_lines"], ORANGE_LIGHT, ORANGE, "?"),
        ((45, 645, 675, 765), copy["not_title"], copy["not_lines"], RED_LIGHT, RED, "×"),
    )
    for box, title, values, fill, outline, marker in boxes:
        panel(draw, box, fill=fill, outline=outline, active=False)
        x0, y0, x1, y1 = box
        centered(draw, center_x, y0 + 27, title, 22, color=outline, bold=True)
        visible_values = values
        visible_marker = marker
        if title == copy["confirm_title"]:
            wrap_width = 32 if locale == "en" else 22
            wrapped_values = tuple(
                line
                for value in values
                for line in wrap(value, width=wrap_width, break_long_words=False)
            )
            visible_values = (f"? {wrapped_values[0]}",) + tuple(f"  {line}" for line in wrapped_values[1:])
            visible_marker = None
        lines_in_box(draw, (x0 + 70, y0 + 48, x1 - 35, y1 - 8), visible_values, 18, marker=visible_marker, gap=2)

    done = (45, 795, 675, 885)
    draw.rounded_rectangle(done, radius=16, fill=GREEN_LIGHT, outline=GREEN, width=3)
    centered(draw, center_x, 815, copy["done"], 23, color=GREEN, bold=True)
    centered(draw, center_x, 850, copy["unchanged"], 23, color=GREEN, bold=True)
    footer = wrap(copy["footer"], width=55 if locale == "en" else 35, break_long_words=False)
    centered_lines(draw, (45, 905, 675, 970), footer, 20, color=MUTED, gap=4)
    return image


RESPONSIBILITY_COPY = {
    "ja": {
        "title": "人間とAIが仕事を分け合うための責務分担",
        "human": ("人間：目的を持ち、何を任せるかを決める",),
        "harness": ("UME-HARNESS", "曖昧な日本語を整理", "確認範囲 / 承認要求", "ローカル作業のプレビュー"),
        "state_current": "現在の実装",
        "bridge": "方向性・未実装",
        "mothership": ("Mothership", "具体的な外部操作を固定", "人間の判断と照合", "同じ台帳履歴内で一度だけ"),
        "executor": ("別途構成する実行系",),
        "verifier": ("別経路の確認系",),
        "caption": ("現在の公開版同士に自動接続はありません。", "破線部分は未実装です。"),
        "legend": ("実線 = 現在実装済み", "破線 = 現在未接続", "外枠 = 別途構成"),
    },
    "en": {
        "title": "Responsibility split for humans and AI sharing work",
        "human": ("Human: holds the purpose", "and decides what to entrust"),
        "harness": ("UME-HARNESS", "Organize ambiguous Japanese intent", "Visible scope / confirmation", "Local-work preview"),
        "state_current": "CURRENT",
        "bridge": "DIRECTION / NOT_SHIPPED",
        "mothership": ("Mothership", "Freeze one concrete external action", "Check the human decision", "Consume once in one ledger history"),
        "executor": ("Separately configured", "executor"),
        "verifier": ("Separate verification", "path"),
        "caption": ("The current public releases have no automatic runtime bridge.", "The dashed connection is not implemented."),
        "legend": ("Solid = implemented now", "Dashed = not connected", "Outline = separately configured"),
    },
}


def svg_lines(values: tuple[str, ...], start_y: int) -> str:
    return "\n".join(
        f'<text class="body" x="360" y="{start_y + index * 40}" text-anchor="middle">{escape(value)}</text>'
        for index, value in enumerate(values)
    )


def svg_tspans(
    values: tuple[str, ...],
    x: int,
    center_y: int,
    *,
    gap: int = 28,
    css_class: str = "body",
) -> str:
    start_y = center_y - (len(values) - 1) * gap // 2
    spans = "".join(
        f'<tspan x="{x}" y="{start_y + index * gap}">{escape(value)}</tspan>'
        for index, value in enumerate(values)
    )
    return f'<text class="{css_class}" x="{x}" text-anchor="middle">{spans}</text>'


def responsibility_svg(locale: str) -> str:
    copy = RESPONSIBILITY_COPY[locale]
    caption = " ".join(copy["caption"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {RESPONSIBILITY_WIDTH} {RESPONSIBILITY_HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(copy["title"])}</title>
  <desc id="desc">{escape(caption)}</desc>
  <style>
    .title {{ font: 700 28px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #202b38; }}
    .label {{ font: 700 28px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #202b38; }}
    .state {{ font: 700 20px ui-monospace, SFMono-Regular, Consolas, monospace; fill: #16705a; }}
    .body {{ font: 23px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #334155; }}
    .small {{ font: 20px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #64748b; }}
    .legend {{ font: 18px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #64748b; }}
  </style>
  <rect width="{RESPONSIBILITY_WIDTH}" height="{RESPONSIBILITY_HEIGHT}" fill="#f8fafc"/>
  <text class="title" x="360" y="58" text-anchor="middle">{escape(copy["title"])}</text>
  <rect x="60" y="92" width="600" height="108" rx="22" fill="#fff0d7" stroke="#b56817" stroke-width="4"/>
  {svg_tspans(copy["human"], 360, 155)}
  <path d="M360 200 V240" stroke="#315f9f" stroke-width="5"/><path d="M350 226 L360 243 L370 226" fill="#315f9f"/>

  <rect x="45" y="245" width="630" height="235" rx="26" fill="#e6eef9" stroke="#315f9f" stroke-width="5"/>
  <text class="state" x="75" y="282">{escape(copy["state_current"])}</text>
  <text class="label" x="360" y="318" text-anchor="middle">{escape(copy["harness"][0])}</text>
  {svg_lines(copy["harness"][1:], 365)}

  <g data-role="bridge">
    <path d="M360 480 V615" stroke="#7356a8" stroke-width="5" stroke-dasharray="14 12"/><path d="M350 600 L360 618 L370 600" fill="#7356a8"/>
    <rect x="60" y="518" width="600" height="64" rx="18" fill="#eee8fb" stroke="#7356a8" stroke-width="3" stroke-dasharray="12 10"/>
    <text class="state" x="360" y="558" text-anchor="middle">{escape(copy["bridge"])}</text>
  </g>

  <rect x="45" y="620" width="630" height="235" rx="26" fill="#dcf1e9" stroke="#16705a" stroke-width="5"/>
  <text class="state" x="75" y="657">{escape(copy["state_current"])}</text>
  <text class="label" x="360" y="693" text-anchor="middle">{escape(copy["mothership"][0])}</text>
  {svg_lines(copy["mothership"][1:], 740)}

  <path d="M360 855 V878 H190 V900" stroke="#16705a" stroke-width="5" fill="none"/><path d="M180 886 L190 903 L200 886" fill="#16705a"/>
  <rect data-role="external" x="40" y="905" width="300" height="92" rx="20" fill="#fff" stroke="#7356a8" stroke-width="4"/>
  <rect data-role="external" x="380" y="905" width="300" height="92" rx="20" fill="#fff" stroke="#237e91" stroke-width="4"/>
  {svg_tspans(copy["executor"], 190, 960)}
  {svg_tspans(copy["verifier"], 530, 960)}
  <path d="M340 951 H375" stroke="#237e91" stroke-width="4"/><path d="M365 941 L380 951 L365 961" fill="#237e91"/>
  <text class="small" x="360" y="1016" text-anchor="middle">{escape(copy["caption"][0])}</text>
  <text class="small" x="360" y="1044" text-anchor="middle">{escape(copy["caption"][1])}</text>
  {svg_tspans(copy["legend"], 360, 1091, gap=21, css_class="legend")}
</svg>
'''


KONJAC_COPY = {
    "ja": {
        "title": "Translation Konjac — 技術操作を普通の日本語へ",
        "cards": (
            (
                "読むだけ",
                PACK["git.status"]["headline"],
                ("変更されたファイルがあるか", "確認しています"),
            ),
            (
                "PCの外へ出る（表示例）",
                PACK["git.push.normal"]["headline"].format(service="GitHub", branch="作業ブランチ"),
                ("⚠️ ここからPCの外へ出ます。", "GitHub の「作業ブランチ」へ", "履歴を送ろうとしています"),
            ),
            (
                "削除（表示例）",
                PACK["fs.delete"]["headline"].format(target="選択した対象"),
                ("⚠️ 「選択した対象」を", "削除しようとしています"),
            ),
        ),
        "caption": "説明用の表示です。外部操作の権限は発行しません。",
    },
    "en": {
        "title": "Translation Konjac — explain technical actions plainly",
        "cards": (
            ("Read only", "Checking whether files have changed", ("Checking whether files", "have changed")),
            ("Leaves this PC", "About to send history to a remote branch", ("About to send history", "to a remote branch")),
            ("Deletion", "About to delete the selected target", ("About to delete", "the selected target")),
        ),
        "caption": "Presentation only. These cards do not grant External Action Authority.",
    },
}


def konjac_svg(locale: str) -> str:
    copy = KONJAC_COPY[locale]
    colors = (("#e6eef9", "#315f9f"), ("#fff0d7", "#b56817"), ("#fde8e8", "#b93838"))
    cards = []
    for index, ((label, exact, visible), (fill, stroke)) in enumerate(zip(copy["cards"], colors, strict=True)):
        y = 110 + index * 245
        visible_text = "\n".join(
            f'<text class="body" x="360" y="{y + 105 + line_index * 34}" text-anchor="middle">{escape(line)}</text>'
            for line_index, line in enumerate(visible)
        )
        cards.append(
            f'''<g><title>{escape(exact)}</title>
  <rect x="45" y="{y}" width="630" height="215" rx="24" fill="{fill}" stroke="{stroke}" stroke-width="4"/>
  <text class="label" x="360" y="{y + 52}" text-anchor="middle">{escape(label)}</text>
  {visible_text}
</g>'''
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CARDS_WIDTH} {CARDS_HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{escape(copy["title"])}</title>
  <desc id="desc">{escape(copy["caption"])}</desc>
  <style>
    .title {{ font: 700 28px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #202b38; }}
    .label {{ font: 700 26px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #202b38; }}
    .body {{ font: 23px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #334155; }}
    .small {{ font: 20px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #64748b; }}
  </style>
  <rect width="{CARDS_WIDTH}" height="{CARDS_HEIGHT}" fill="#f8fafc"/>
  <text class="title" x="360" y="58" text-anchor="middle">{escape(copy["title"])}</text>
  {"".join(cards)}
  <text class="small" x="360" y="910" text-anchor="middle">{escape(copy["caption"])}</text>
</svg>
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--diagram", action="store_true")
    mode.add_argument("--konjac-cards", action="store_true")
    parser.add_argument("--locale", choices=tuple(COPY), required=True)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def frame_durations() -> list[int]:
    """Distribute whole GIF centiseconds while preserving the exact duration."""
    if DURATION_MS % 10:
        raise SystemExit("duration_ms must be representable in GIF centiseconds")
    total_ticks = DURATION_MS // 10
    base, remainder = divmod(total_ticks, FRAME_COUNT)
    durations = []
    accumulator = 0
    for _ in range(FRAME_COUNT):
        accumulator += remainder
        extra = 0
        if accumulator >= FRAME_COUNT:
            extra = 1
            accumulator -= FRAME_COUNT
        durations.append((base + extra) * 10)
    return durations


def main() -> None:
    global FONT_PATH
    args = parse_args()
    if args.diagram or args.konjac_cards:
        if args.output is None:
            raise SystemExit("--output is required for SVG generation")
        content = responsibility_svg(args.locale) if args.diagram else konjac_svg(args.locale)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"generated {args.output}")
        return

    if args.font is None or args.output_dir is None:
        raise SystemExit("--font and --output-dir are required for GIF generation")
    FONT_PATH = args.font.resolve()
    if not FONT_PATH.is_file():
        raise SystemExit("font input is missing or is not a regular file")
    expected_font = (CONTRACT_PATH.parent / str(CONTRACT["font"])).resolve()
    if FONT_PATH != expected_font:
        raise SystemExit(f"font input must match the asset contract: {expected_font}")
    actual_font_sha256 = hashlib.sha256(FONT_PATH.read_bytes()).hexdigest()
    if actual_font_sha256 != CONTRACT["font_sha256"]:
        raise SystemExit("font input digest does not match the asset contract")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    gif_path = output_dir / "ume-harness-human-layer.gif"
    poster_path = output_dir / "ume-harness-human-layer-poster.png"

    frames = []
    for frame_index in range(FRAME_COUNT):
        scene = min(SCENES - 1, frame_index // FRAMES_PER_SCENE)
        frames.append(draw_preview(args.locale, scene, frame_index / max(1, FRAME_COUNT - 1)))
    draw_poster(args.locale).save(poster_path, format="PNG", optimize=True)
    palette = [
        frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        for frame in frames
    ]
    palette[0].save(
        gif_path,
        format="GIF",
        save_all=True,
        append_images=palette[1:],
        duration=frame_durations(),
        loop=0,
        optimize=True,
        disposal=2,
    )
    if gif_path.stat().st_size >= int(CONTRACT["max_gif_bytes"]):
        raise SystemExit("generated GIF exceeds the asset contract size ceiling")
    print(f"generated {gif_path} ({gif_path.stat().st_size} bytes)")
    print(f"generated {poster_path} ({poster_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
