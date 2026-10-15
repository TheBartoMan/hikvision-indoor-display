"""Generate original integration icons. Maintainer-only dependency: Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "custom_components/hikvision_display/brand"


def make_icon(size, dark=False):
    factor = size * 4 / 256
    image = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(values):
        return tuple(round(value * factor) for value in values)

    body = "#F4F6F5" if dark else "#29322F"
    screen = "#29322F" if dark else "#F4F6F5"
    accent = "#E7474D"
    draw.rounded_rectangle(box((16, 35, 240, 211)), radius=round(19 * factor), fill=body)
    draw.rounded_rectangle(box((30, 49, 226, 177)), radius=round(8 * factor), fill=screen)
    draw.rounded_rectangle(box((65, 81, 164, 145)), radius=round(10 * factor), fill=accent)
    draw.polygon([box((164, 97)), box((194, 82)), box((194, 144)), box((164, 129))], fill=accent)
    draw.ellipse(box((100, 99, 128, 127)), fill=screen)
    for x in (88, 122, 156):
        draw.ellipse(box((x, 187, x + 12, 199)), fill=screen)
    return image.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for dark, prefix in ((False, ""), (True, "dark_")):
        for size, suffix in ((256, ""), (512, "@2x")):
            make_icon(size, dark).save(DESTINATION / (prefix + "icon" + suffix + ".png"))
