"""Generate Android mipmap launcher icons from Assets/icon-cream-transparent.png."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "Assets"
RES = ROOT / "android" / "app" / "src" / "main" / "res"

SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

BG_COLOR = (15, 23, 42, 255)  # #0f172a deep brand dark slate


def make_launcher_icon(size: int, round_icon: bool = False) -> Image.Image:
    icon_img = Image.open(ASSETS / "icon-cream-transparent.png").convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Base background
    bg = Image.new("RGBA", (size, size), BG_COLOR)

    if round_icon:
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)
        canvas.paste(bg, (0, 0), mask)
    else:
        # Rounded rect corner radius ~20%
        corner_r = int(size * 0.2)
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, size, size), radius=corner_r, fill=255)
        canvas.paste(bg, (0, 0), mask)

    # Scale emblem to fit ~60% of canvas height
    target_h = int(size * 0.62)
    aspect = icon_img.width / icon_img.height
    target_w = int(target_h * aspect)
    resized_emblem = icon_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Center emblem
    offset_x = (size - target_w) // 2
    offset_y = (size - target_h) // 2
    canvas.paste(resized_emblem, (offset_x, offset_y), resized_emblem)
    return canvas


def main() -> None:
    print(">> Generating Android launcher icons...")
    for folder_name, size in SIZES.items():
        folder = RES / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        # Standard launcher icon
        square = make_launcher_icon(size, round_icon=False)
        square.save(folder / "ic_launcher.png", format="PNG")

        # Round launcher icon
        round_ic = make_launcher_icon(size, round_icon=True)
        round_ic.save(folder / "ic_launcher_round.png", format="PNG")

    # Also update drawable foreground
    fg = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    icon_img = Image.open(ASSETS / "icon-cream-transparent.png").convert("RGBA")
    target_h = int(432 * 0.48)
    target_w = int(target_h * (icon_img.width / icon_img.height))
    resized = icon_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    fg.paste(resized, ((432 - target_w) // 2, (432 - target_h) // 2), resized)
    fg.save(RES / "drawable" / "ic_launcher_foreground.png", format="PNG")
    xml_fg = RES / "drawable" / "ic_launcher_foreground.xml"
    if xml_fg.exists():
        xml_fg.unlink()

    print(">> Android icons generated successfully!")


if __name__ == "__main__":
    main()
