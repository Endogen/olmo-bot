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


def draw_points_on_image(
    image_path: str,
    groups: list[PointGroup],
    *,
    dot_radius: int | None = None,
    output_path: str | None = None,
) -> str:
    """Draw colored point markers on an image and save it.

    Returns the path to the annotated image.
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # Auto-scale dot size based on image dimensions
    if dot_radius is None:
        dot_radius = max(8, min(w, h) // 60)

    draw = ImageDraw.Draw(img, "RGBA")

    # Try to load a font for labels
    font = None
    font_size = max(14, dot_radius)
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

    all_points = []
    for group in groups:
        for pt in group.points:
            all_points.append((pt, group.label))

    for i, (pt, label) in enumerate(all_points):
        color = POINT_COLORS[i % len(POINT_COLORS)]

        # Convert from 0–1000 to pixel coordinates
        px = int(pt.x / COORD_SCALE * w)
        py = int(pt.y / COORD_SCALE * h)

        # Clamp to image bounds
        px = max(0, min(w - 1, px))
        py = max(0, min(h - 1, py))

        r = dot_radius

        # Draw outer ring (semi-transparent white for visibility)
        draw.ellipse(
            [px - r - 3, py - r - 3, px + r + 3, py + r + 3],
            fill=(*color, 60),
            outline=(255, 255, 255, 200),
            width=3,
        )

        # Draw solid inner dot
        draw.ellipse(
            [px - r, py - r, px + r, py + r],
            fill=(*color, 220),
            outline=(255, 255, 255, 255),
            width=2,
        )

        # Draw label if multiple points
        if len(all_points) > 1:
            tag = f"{i + 1}"
            # Draw number in the center of the dot
            bbox = draw.textbbox((0, 0), tag, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = px - tw // 2
            ty = py - th // 2 - 1
            # Text shadow
            draw.text((tx + 1, ty + 1), tag, fill=(0, 0, 0, 180), font=font)
            draw.text((tx, ty), tag, fill=(255, 255, 255, 255), font=font)

    # Build caption
    unique_labels = list(dict.fromkeys(label for _, label in all_points))
    if len(all_points) == 1:
        caption = unique_labels[0]
    elif len(unique_labels) == 1:
        # All points share the same label (e.g. "eyes")
        caption = f"📍 {unique_labels[0]} ({len(all_points)} points)"
    else:
        # Different labels — number them
        caption = "\n".join(
            f"📍 {i + 1}. {label}" for i, (_, label) in enumerate(all_points)
        )

    # Save
    if output_path is None:
        output_path = image_path.rsplit(".", 1)[0] + "_pointed.jpg"

    img.save(output_path, "JPEG", quality=92)
    return output_path, caption
