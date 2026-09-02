from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).parent
SOURCE = Path('/var/folders/rj/hpkgkxhx50ld8y67tzr75hsw0000gn/T')
W, H = 1080, 1350
WHITE = '#FFFFFF'
NAVY = '#102A43'
BLUE = '#2563EB'
MUTED = '#667085'


def font(size: int, bold: bool = False):
    name = '/System/Library/Fonts/Hiragino Sans GB.ttc'
    return ImageFont.truetype(name, size, index=0)


def fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    scale = min(box[0] / image.width, box[1] / image.height)
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)


def header(canvas: Image.Image, step: str, title: str, subtitle: str) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((48, 42, 178, 92), radius=25, fill='#EAF1FF')
    draw.text((74, 52), step, font=font(27, True), fill=BLUE)
    draw.text((48, 126), title, font=font(46, True), fill=NAVY)
    draw.text((50, 186), subtitle, font=font(26), fill=MUTED)
    draw.line((48, 234, 1032, 234), fill='#E6ECF5', width=2)


def footer(canvas: Image.Image, text: str) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.line((48, 1190, 1032, 1190), fill='#E6ECF5', width=2)
    draw.ellipse((52, 1233, 66, 1247), fill=BLUE)
    draw.text((84, 1219), text, font=font(25), fill=NAVY)
    draw.text((52, 1283), 'Data OXHor  内测演示', font=font(21), fill='#98A2B3')


def save_cover() -> None:
    source = Image.open(SOURCE / 'codex-clipboard-7bcae048-bb01-4fa3-a68a-a1524e616b19.png').convert('RGB')
    canvas = Image.new('RGB', (W, H), WHITE)
    placed = fit(source, (900, H))
    canvas.paste(placed, ((W - placed.width) // 2, 0))
    canvas.save(ROOT / '01-workflow.png', quality=96)


def save_analysis(source_name: str, output: str, step: str, title: str, subtitle: str, footer_text: str, crop_right: int) -> None:
    source = Image.open(SOURCE / source_name).convert('RGB')
    source = source.crop((0, 0, source.width - crop_right, source.height))
    canvas = Image.new('RGB', (W, H), WHITE)
    header(canvas, step, title, subtitle)
    placed = fit(source, (984, 900))
    x = (W - placed.width) // 2
    y = 292
    canvas.paste(placed, (x, y))
    footer(canvas, footer_text)
    canvas.save(ROOT / output, quality=96)


def save_ppt() -> None:
    source = Image.open(SOURCE / 'codex-clipboard-1a052417-4a0a-434b-a8fc-54c58b0ed613.png').convert('RGB')
    # Remove the presentation application's toolbar and slide navigator. Keep the actual editable slide.
    slide = source.crop((640, 216, 2722, 1272))
    canvas = Image.new('RGB', (W, H), WHITE)
    header(canvas, '03', '生成可编辑 PPT', '把已验证的分析，整理成可继续编辑的经营汇报')
    placed = fit(slide, (984, 900))
    canvas.paste(placed, ((W - placed.width) // 2, 320))
    footer(canvas, '结论、图表与关键数字，来自同一轮分析证据')
    canvas.save(ROOT / '04-ppt-delivery.png', quality=96)


save_cover()
save_analysis(
    'codex-clipboard-35d17400-b7b7-4cc8-b3e1-7370a0bbc9a9.png',
    '02-find-anomaly.png', '01', '先识别经营异常',
    '从同比缺口开始，拆解到付款人数与人均报入',
    '先回答：问题发生在哪里，和整体相比是否异常。',
    65,
)
save_analysis(
    'codex-clipboard-d059200d-a628-43f1-8ba3-70d97b6e2fe8.png',
    '03-drill-down.png', '02', '再沿证据继续下钻',
    '按渠道、时间、产品等维度定位原因，并保留查询证据',
    '不是只给结论，而是给出可以继续核查的证据链。',
    90,
)
save_ppt()
