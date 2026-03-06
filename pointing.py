"""Parse Molmo 2 pointing responses and draw overlays on images."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Molmo 2 coordinate space: 0–1000 for both axes
COORD_SCALE = 1000

# Regex to match <points coords="...">label</points>
_POINTS_RE = re.compile(
    r'<points\s+coords="([^"]+)">(.*?)</points>',
    re.DOTALL,
)

# Distinct colors for multiple points (RGB)
POINT_COLORS = [
    (255, 59, 48),    # red
    (0, 122, 255),    # blue
    (52, 199, 89),    # green
    (255, 149, 0),    # orange
    (175, 82, 222),   # purple
    (255, 45, 85),    # pink
    (90, 200, 250),   # cyan
    (255, 204, 0),    # yellow
]


@dataclass
class Point:
    x: float  # 0–1000
    y: float  # 0–1000
    label: str
    index: int


@dataclass
class PointGroup:
    points: list[Point]
    label: str


def parse_points(text: str) -> list[PointGroup]:
    """Extract all point groups from a Molmo 2 response.

    Format: <points coords="1 1 X Y [N X Y ...]">label</points>
    - First point: flag flag X Y (4 numbers)
    - Subsequent: index X Y (3 numbers)
    - Coordinates are in 0–1000 space.
    """
    groups: list[PointGroup] = []

    for match in _POINTS_RE.finditer(text):
        coords_str = match.group(1).strip()
        label = match.group(2).strip()

        nums = [int(n) for n in coords_str.split()]
        if len(nums) < 4:
            continue

        points: list[Point] = []

        # First point: skip 2 prefix flags, take x, y
        points.append(Point(x=nums[2], y=nums[3], label=label, index=1))

        # Subsequent points: index, x, y (3 numbers each)
        i = 4
        idx = 2
        while i + 2 < len(nums):
            # nums[i] is the point index, then x, y
            points.append(Point(x=nums[i + 1], y=nums[i + 2], label=label, index=idx))
            i += 3
            idx += 1

        groups.append(PointGroup(points=points, label=label))

    return groups


def has_points(text: str) -> bool:
    """Check if a response contains pointing data."""
    return bool(_POINTS_RE.search(text))


def strip_points(text: str) -> str:
    """Remove pointing XML tags from a response, keeping just the text."""
    return _POINTS_RE.sub(r"\2", text).strip()


def _make_marker(
    color: tuple[int, int, int],
    radius: int,
    label: str | None,
    *,
    scale: int = 4,
) -> Image.Image:
    """Render a single anti-aliased point marker via supersampling.

    Draws at *scale*× resolution then downscales with LANCZOS for smooth edges.
    """
    sr = radius * scale  # supersampled radius
    pad = 4 * scale      # padding for outer glow/border
    size = (sr + pad) * 2
    marker = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(marker)
    cx = cy = size // 2

    # Soft outer glow
    draw.ellipse(
        [cx - sr - pad // 2, cy - sr - pad // 2,
         cx + sr + pad // 2, cy + sr + pad // 2],
        fill=(0, 0, 0, 50),
    )

    # White border ring
    border = 3 * scale
    draw.ellipse(
        [cx - sr - border, cy - sr - border,
         cx + sr + border, cy + sr + border],
        fill=(255, 255, 255, 240),
    )

    # Main colored circle
    draw.ellipse(
        [cx - sr, cy - sr, cx + sr, cy + sr],
        fill=(*color, 230),
    )

    # Draw number label
    if label:
        font = None
        font_size = int(sr * 1.3)
        for font_name in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ):
            if Path(font_name).exists():
                try:
                    font = ImageFont.truetype(font_name, font_size)
                except Exception:
                    pass
                break

        # Dark shadow for contrast (anchor="mm" = middle-middle centering)
        for ox, oy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
            off = 2 * scale
            draw.text(
                (cx + ox * off, cy + oy * off),
                label,
                fill=(0, 0, 0, 120),
                font=font,
                anchor="mm",
            )

        # White text, perfectly centered
        draw.text((cx, cy), label, fill=(255, 255, 255, 255), font=font, anchor="mm")

    # Downscale to target size with LANCZOS for smooth anti-aliasing
    final_size = size // scale
    marker = marker.resize((final_size, final_size), Image.LANCZOS)
    return marker


def draw_points_on_image(
    image_path: str,
    groups: list[PointGroup],
    *,
    dot_radius: int | None = None,
    output_path: str | None = None,
) -> tuple[str, str]:
    """Draw colored point markers on an image and save it.

    Returns (output_path, caption).
    """
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    # Auto-scale dot size based on image dimensions
    if dot_radius is None:
        dot_radius = max(10, min(w, h) // 50)

    all_points = []
    for group in groups:
        for pt in group.points:
            all_points.append((pt, group.label))

    show_numbers = len(all_points) > 1

    for i, (pt, label) in enumerate(all_points):
        color = POINT_COLORS[i % len(POINT_COLORS)]

        # Convert from 0–1000 to pixel coordinates
        px = int(pt.x / COORD_SCALE * w)
        py = int(pt.y / COORD_SCALE * h)
        px = max(0, min(w - 1, px))
        py = max(0, min(h - 1, py))

        number = str(i + 1) if show_numbers else None
        marker = _make_marker(color, dot_radius, number)
        mw, mh = marker.size

        # Paste marker centered on the point
        img.paste(marker, (px - mw // 2, py - mh // 2), marker)

    # Build caption
    unique_labels = list(dict.fromkeys(label for _, label in all_points))
    if len(all_points) == 1:
        caption = unique_labels[0]
    elif len(unique_labels) == 1:
        caption = f"📍 {unique_labels[0]} ({len(all_points)} points)"
    else:
        caption = "\n".join(
            f"📍 {i + 1}. {label}" for i, (_, label) in enumerate(all_points)
        )

    # Save as RGB JPEG
    if output_path is None:
        output_path = image_path.rsplit(".", 1)[0] + "_pointed.jpg"

    img.convert("RGB").save(output_path, "JPEG", quality=92)
    return output_path, caption
