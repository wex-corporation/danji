"""단지광장 홍보 영상 합성. 1080×1920, 30fps, 34초.

음악(music.wav)의 박과 프레임을 맞춘다. 120 BPM → 한 박 = 15프레임.
앱 화면은 danji.life 실제 캡처(home.png, post_tall.png)를 잘라 카메라만 움직인다.
화면 위에 그리는 건 강조 테두리·형광펜뿐이고 UI를 새로 만들지 않는다.
"""
import json, math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops
import imageio_ffmpeg

W, H, FPS = 1080, 1920, 30
BEAT = 15
TOTAL = 34 * FPS
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")          # 영상 프레임·폰트·음악(커밋 안 함)
ASSETS = os.path.join(HERE, "assets")        # 실제 화면 캡처와 요소 좌표
FR = os.path.join(BUILD, "frames")

PURPLE = (116, 87, 245)       # 아이콘 #7457f5
SITE_PURPLE = (88, 76, 230)   # 헤더 보라
INK = (24, 24, 29)            # 아이콘 #18181d
PAPER = (247, 246, 242)

def font(w, size):
    return ImageFont.truetype(os.path.join(BUILD, "fonts", f"Pretendard-{w}.otf"), size)

_fc = {}
def F(w, size):
    k = (w, size)
    if k not in _fc:
        _fc[k] = font(w, size)
    return _fc[k]

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3

def lerp(a, b, t):
    return a + (b - a) * t

# ── 공통 그리기 ─────────────────────────────────────────
def fit_size(text, weight, max_w, start):
    s = start
    while s > 20:
        bb = F(weight, s).getbbox(text)
        if bb[2] - bb[0] <= max_w:
            return s
        s -= 4
    return s

def draw_center(img, text, weight, size, cy, fill, scale=1.0, tracking=0):
    """글자를 한 장에 그려 두고 scale만큼 키워 붙인다(박자 '쾅' 연출)."""
    f = F(weight, size)
    bb = f.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad = 40
    layer = Image.new("L", (tw + pad * 2, th + pad * 2), 0)
    ImageDraw.Draw(layer).text((pad - bb[0], pad - bb[1]), text, font=f, fill=255)
    if abs(scale - 1) > 1e-3:
        layer = layer.resize((int(layer.width * scale), int(layer.height * scale)), Image.BICUBIC)
    x = (W - layer.width) // 2
    y = int(cy - layer.height / 2)
    col = Image.new("RGB", layer.size, fill)
    img.paste(col, (x, y), layer)

def punch(k):
    """박 직후 k프레임째의 크기. 크게 떨어졌다가 1.0으로 가라앉는다."""
    return 1 + 0.14 * math.exp(-k / 1.6)

def load_frame(name, i):
    d = os.path.join(FR, name)
    files = sorted(os.listdir(d))
    return Image.open(os.path.join(d, files[min(i, len(files) - 1)])).convert("RGB")

def kb(img, t, z0=1.0, z1=1.08):
    """1188×2112 원본에서 서서히 조여 들어가는 켄번즈."""
    z = lerp(z0, z1, t)
    cw, ch = int(W * 1.1 / z), int(H * 1.1 / z)
    x = (img.width - cw) // 2
    y = (img.height - ch) // 2
    return img.crop((x, y, x + cw, y + ch)).resize((W, H), Image.BICUBIC)

VIG = None
def vignette():
    global VIG
    if VIG is None:
        m = Image.new("L", (W // 8, H // 8), 0)
        d = ImageDraw.Draw(m)
        d.ellipse((-W // 16, -H // 32, W // 8 + W // 16, H // 8 + H // 32), fill=255)
        VIG = m.filter(ImageFilter.GaussianBlur(40)).resize((W, H), Image.BICUBIC)
    return VIG

def grade(img, dark=0.5, sat=0.55):
    img = ImageEnhance.Color(img).enhance(sat)
    img = ImageEnhance.Brightness(img).enhance(dark)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(img, black, vignette())

# ── 훅: 관리비 고지서 ────────────────────────────────────
def make_bill():
    """특정 단지·기관을 가리키지 않는 일반 고지서. 금액은 전부 흐린 막대로 둔다(가짜 숫자 금지)."""
    S = 2
    bw, bh = 1000, 2150
    im = Image.new("RGB", (bw, bh), (250, 249, 245))
    d = ImageDraw.Draw(im)
    m = 70
    d.text((m, 80), "관리비 고지서", font=F("ExtraBold", 96), fill=(30, 30, 36))
    d.text((m, 200), "____동  ____호", font=F("Medium", 44), fill=(120, 120, 128))
    d.line((m, 290, bw - m, 290), fill=(30, 30, 36), width=6)
    rows = ["일반관리비", "청소비", "경비비", "소독비", "승강기유지비", "수선유지비",
            "장기수선충당금", "전기료", "수도료", "난방비", "급탕비"]
    y = 340
    row_y = {}
    for r in rows:
        d.text((m, y), r, font=F("Medium", 52), fill=(60, 60, 68))
        d.rounded_rectangle((bw - m - 240, y + 10, bw - m, y + 52), 10, fill=(190, 190, 196))
        d.line((m, y + 86, bw - m, y + 86), fill=(225, 224, 220), width=2)
        row_y[r] = y
        y += 110
    y += 20
    d.line((m, y, bw - m, y), fill=(30, 30, 36), width=6)
    d.text((m, y + 40), "합계", font=F("ExtraBold", 70), fill=(20, 20, 26))
    d.rounded_rectangle((bw - m - 300, y + 50, bw - m, y + 116), 14, fill=(150, 150, 158))
    total_y = y + 40
    # 금액 막대를 흐려 숫자처럼 보이게만 한다
    blur = im.filter(ImageFilter.GaussianBlur(6))
    mask = Image.new("L", im.size, 0)
    md = ImageDraw.Draw(mask)
    for r in rows:
        md.rectangle((bw - m - 260, row_y[r], bw - m + 10, row_y[r] + 62), fill=255)
    md.rectangle((bw - m - 320, total_y, bw - m + 10, total_y + 110), fill=255)
    im = Image.composite(blur, im, mask)
    # 어두운 책상 위에 놓인 종이처럼 좌우 여백을 둔다
    canvas = Image.new("RGB", (bw + 240, bh + 200), (22, 22, 25))
    sh = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(sh).rectangle((120 + 10, 100 + 20, 120 + bw + 10, 100 + bh + 20), fill=160)
    canvas.paste((0, 0, 0), (0, 0), sh.filter(ImageFilter.GaussianBlur(24)))
    canvas.paste(im, (120, 100))
    return canvas, {r: v + 100 for r, v in row_y.items()}, total_y + 100, rows

BILL = None
def hook_frame(f):
    global BILL
    t = f / FPS
    if f < 24:  # 0~0.8초: 우편함 벽(얼굴 없는 오른쪽만)
        img = kb(load_frame("hook_mail", f), f / 24, 1.0, 1.06)
        return grade(img, 0.62, 0.6)
    if BILL is None:
        BILL = make_bill()
    bill, row_y, total_y, rows = BILL
    k = (f - 24) / (60 - 24)
    # 합계 칸 쪽으로 카메라가 내려가며 조인다
    z = lerp(1.0, 1.15, ease(k))
    view_h = int(1180 * H / W / z)
    view_w = int(view_h * W / H)
    cy = lerp(bill.height * 0.42, total_y - 200, ease(k))
    cx = bill.width * 0.5
    x0 = int(max(0, min(bill.width - view_w, cx - view_w / 2)))
    y0 = int(max(0, min(bill.height - view_h, cy - view_h / 2)))
    # 형광펜이 줄을 따라 내려가다 합계에서 멈춘다
    b2 = bill.copy()
    ov = Image.new("RGBA", b2.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    stops = [row_y[r] for r in rows] + [total_y]
    pos = min(len(stops) - 1, int(ease(min(1, k / 0.7)) * (len(stops) - 1) + 0.5))
    yy = stops[pos]
    hh = 110 if pos == len(stops) - 1 else 70
    od.rounded_rectangle((150, yy - 6, b2.width - 150, yy + hh), 16, fill=(255, 214, 0, 90))
    b2 = Image.alpha_composite(b2.convert("RGBA"), ov).convert("RGB")
    crop = b2.crop((x0, y0, x0 + view_w, y0 + view_h)).resize((W, H), Image.BICUBIC)
    crop = crop.rotate(-2.0, resample=Image.BICUBIC, expand=False, fillcolor=(20, 20, 22))
    # 얕은 심도: 위아래를 흐린다
    blur = crop.filter(ImageFilter.GaussianBlur(10))
    m = Image.new("L", (1, H))
    for y in range(H):
        dy = abs(y - H * 0.52) / (H * 0.5)
        m.putpixel((0, y), int(255 * min(1, max(0, (dy - 0.35) / 0.4))))
    crop = Image.composite(blur, crop, m.resize((W, H)))
    crop = ImageEnhance.Brightness(crop).enhance(0.92)
    crop = Image.composite(crop, Image.new("RGB", (W, H), 0), vignette())
    if t >= 1.5:
        kk = f - 45
        a = ease_out(kk / 4)
        layer = crop.copy()
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle((W // 2 - 250, 1540, W // 2 + 250, 1680), 70, fill=(12, 12, 14))
        draw_center(layer, "이거, 맞아?", "Bold", 72, 1610, (255, 255, 255))
        crop = Image.blend(crop, layer, a)
    return crop

# ── 오프닝: 검은 화면 큰 글자 ─────────────────────────────
OPEN = ["우리 단지", "얘기는", "늘", "누가 그러던데", "단톡방에서", "엘리베이터에서", "그래서", "진짜는?"]

def opening_frame(f):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    rel = f - 60
    i = rel // 30
    k = rel % 30
    if f >= 285:  # 드롭 직전 한 박은 완전 무음·완전 암전
        return img
    word = OPEN[i]
    size = fit_size(word, "Black", 900, 230 if len(word) <= 3 else 190)
    draw_center(img, word, "Black", size, H // 2, (255, 255, 255), punch(k))
    return img

# ── 드롭: 한 박 한 단어 ──────────────────────────────────
DROP = [("관리비", "w_fee"), ("주차", "w_park"), ("경비", "w_guard"), ("승강기", "w_lift"),
        ("분리수거", "w_recycle"), ("놀이터", "w_play"), ("통학로", "w_school"), ("도서관", "w_lib"),
        ("산책로", "w_walk"), ("한강", "w_han"), ("전세", "w_key"), ("재건축", "w_build")]

def drop_frame(f):
    rel = f - 300
    i, k = rel // BEAT, rel % BEAT
    word, clip = DROP[i]
    img = kb(load_frame(clip, k), k / BEAT, 1.0, 1.05)
    img = grade(img, 0.48, 0.5)
    if k == 0:  # 박 첫 프레임은 살짝 번쩍
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), 0.28)
    size = fit_size(word, "Black", 940, 250)
    draw_center(img, word, "Black", size, H // 2, (255, 255, 255), punch(k))
    return img

END4 = [("전부", "w"), ("출처", "b"), ("붙여서", "w"), ("기록.", "b")]

def end4_frame(f):
    rel = f - 480
    i, k = rel // BEAT, rel % BEAT
    word, mode = END4[i]
    bg, fg = ((255, 255, 255), (0, 0, 0)) if mode == "w" else ((0, 0, 0), (255, 255, 255))
    img = Image.new("RGB", (W, H), bg)
    if word == "기록.":
        # 마침표만 브랜드 보라
        base = "기록"
        size = 260
        f_ = F("Black", size)
        bb = f_.getbbox(base + ".")
        tw = bb[2] - bb[0]
        s = punch(k)
        layer = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(layer)
        x = (W - tw) // 2 - bb[0]
        y = H // 2 - (bb[3] + bb[1]) // 2
        d.text((x, y), base, font=f_, fill=fg)
        d.text((x + f_.getlength(base), y), ".", font=f_, fill=PURPLE)
        if abs(s - 1) > 1e-3:
            big = layer.resize((int(W * s), int(H * s)), Image.BICUBIC)
            ox, oy = (big.width - W) // 2, (big.height - H) // 2
            layer = big.crop((ox, oy, ox + W, oy + H))
        return layer
    draw_center(img, word, "Black", 260, H // 2, fg, punch(k))
    return img

# ── 실제 앱 화면 ─────────────────────────────────────────
HOME = Image.open(os.path.join(ASSETS, "home.png")).convert("RGB")      # 360×640 CSS @4x
POST = Image.open(os.path.join(ASSETS, "post_tall.png")).convert("RGB")  # 360×1000 CSS @4x
DPR = 4
CARD = (90, 470, 990, 1870)   # 900×1400
CW, CH = CARD[2] - CARD[0], CARD[3] - CARD[1]
WIN_H = 360 * CH / CW          # 전폭 창의 CSS 높이 = 560

CARD_MASK = Image.new("L", (CW, CH), 0)
ImageDraw.Draw(CARD_MASK).rounded_rectangle((0, 0, CW - 1, CH - 1), 56, fill=255)
SHADOW = None

def card_base():
    global SHADOW
    img = Image.new("RGB", (W, H), (10, 10, 12))
    if SHADOW is None:
        s = Image.new("L", (W, H), 0)
        ImageDraw.Draw(s).rounded_rectangle((CARD[0] - 6, CARD[1] + 10, CARD[2] + 6, CARD[3] + 22), 60, fill=150)
        SHADOW = s.filter(ImageFilter.GaussianBlur(30))
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), SHADOW)
    return img

def render_window(src, win, marks):
    """win=(x,y,w) CSS 좌표. 높이는 카드 비율로 정한다. marks는 CSS 좌표의 강조 목록."""
    x, y, w = win
    h = w * CH / CW
    crop = src.crop((int(x * DPR), int(y * DPR), int((x + w) * DPR), int((y + h) * DPR))).resize((CW, CH), Image.LANCZOS)
    sc = CW / w
    ov = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for mk in marks:
        kind, rects, a = mk[0], mk[1], mk[2]
        if a <= 0:
            continue
        for j, r in enumerate(rects):
            rx, ry, rw, rh = r["x"], r["y"], r["w"], r["h"]
            X0, Y0 = (rx - x) * sc, (ry - y) * sc
            X1, Y1 = X0 + rw * sc, Y0 + rh * sc
            if kind == "marker":   # 형광펜: 줄마다 순서대로 왼→오 칠한다
                prog = max(0, min(1, a * len(rects) - j))
                if prog > 0:
                    d.rounded_rectangle((X0 - 6, Y0 + (Y1 - Y0) * 0.1, X0 - 6 + (X1 - X0 + 12) * prog, Y1 + 4), 8,
                                        fill=(PURPLE[0], PURPLE[1], PURPLE[2], 70))
            elif kind == "box":
                pad = mk[3] if len(mk) > 3 else 10
                d.rounded_rectangle((X0 - pad, Y0 - pad, X1 + pad, Y1 + pad), 18,
                                    outline=(PURPLE[0], PURPLE[1], PURPLE[2], int(255 * a)), width=7)
            elif kind == "ring":
                cx, cy = (X0 + X1) / 2, (Y0 + Y1) / 2
                for q in range(2):
                    ph = (a * 1.6 + q * 0.5) % 1.0
                    rad = 60 + ph * 160
                    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad),
                              outline=(PURPLE[0], PURPLE[1], PURPLE[2], int(220 * (1 - ph))), width=8)
    crop = Image.alpha_composite(crop.convert("RGBA"), ov).convert("RGB")
    img = card_base()
    img.paste(crop, (CARD[0], CARD[1]), CARD_MASK)
    return img

def caption(img, lines, k, cy=300):
    a = ease_out(k / 5)
    s = 1 + 0.06 * math.exp(-k / 2)
    layer = img.copy()
    n = len(lines)
    size = 92 if n == 1 else 80
    for j, ln in enumerate(lines):
        yy = cy + (j - (n - 1) / 2) * size * 1.25
        draw_center(layer, ln, "ExtraBold", fit_size(ln, "ExtraBold", 900, size), yy, (255, 255, 255), s)
    return Image.blend(img, layer, a)

PB = json.load(open(os.path.join(ASSETS, "boxes_post.json")))
def pick(lst, pred):
    for grp in lst:
        if grp and pred(grp[0]):
            return grp
    raise KeyError
BADGE = [{"x": 18, "y": 27, "w": 74, "h": 16}]
AGENT = pick(PB["agent"], lambda r: r["y"] < 300)
STOP = PB["stop"][0]
QUES = PB["question"][0]
BASIS = [{"x": 18, "y": 805, "w": 324, "h": 160}]
PIN = [{"x": 72, "y": 207, "w": 50, "h": 36}]  # 원베일리 핀(home.png 에서 잰 값)

def app_frame(f):
    rel = f - 540
    shot, k = rel // 60, rel % 60
    t = k / 60
    if shot == 0:   # 지도 → 원베일리 핀
        e = ease(k / 45)
        win = (lerp(0, 12, e), lerp(40, 93, e), lerp(360, 170, e))
        img = render_window(HOME, win, [("ring", PIN, max(0, (k - 18) / 42))])
        return caption(img, ["단지마다, AI가"], k)
    if shot == 1:   # 글 상세: 출처 확인 배지 → 확인 기준 상자
        if k < 30:
            e = ease(k / 30)
            img = render_window(POST, (lerp(0, 4, e), lerp(0, 4, e), lerp(360, 300, e)),
                                [("box", BADGE, ease(k / 8), 12)])
        else:
            kk = k - 30
            e = ease(kk / 30)
            img = render_window(POST, (0, lerp(430, 440, e), lerp(360, 352, e)),
                                [("box", BASIS, ease(kk / 8), 6)])
        return caption(img, ["공개 자료로", "확인한 것만 쓰고"], k)
    if shot == 2:   # AGENT 라벨 → '현장이 답할 문제입니다'
        e = ease(k / 60)
        win = (lerp(0, 6, e), lerp(150, 330, e), lerp(360, 330, e))
        img = render_window(POST, win, [("box", AGENT, ease(k / 8), 8), ("marker", STOP, ease((k - 18) / 28))])
        return caption(img, ["모르는 데서", "멈춥니다"], k)
    # shot 3: 글 끝 질문
    e = ease(k / 60)
    win = (lerp(0, 10, e), lerp(440, 520, e), lerp(360, 320, e))
    img = render_window(POST, win, [("marker", QUES, ease((k - 6) / 30))])
    return caption(img, ["나머지는"], k)

# ── 끝: 선언 · 브랜드 한 줄 · 로고 ───────────────────────
def declare_frame(f):
    k = f - 780
    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw_center(img, "사는 사람이 압니다.", "Black", fit_size("사는 사람이 압니다.", "Black", 940, 150), H // 2, (255, 255, 255), punch(k))
    return img

def brand_frame(f):
    k = f - 840
    bg = kb(load_frame("end_city", k), k / 60, 1.0, 1.06)
    img = grade(bg, 0.42, 0.7)
    for j, (ln, at) in enumerate((("공개 자료는 여기까지.", 0), ("나머지는 사는 사람이.", 30))):
        if k >= at:
            kk = k - at
            a = ease_out(kk / 6)
            layer = img.copy()
            draw_center(layer, ln, "ExtraBold", fit_size(ln, "ExtraBold", 920, 96), 870 + j * 150,
                        (255, 255, 255), 1 + 0.05 * math.exp(-kk / 2))
            img = Image.blend(img, layer, a)
    return img

LOGO = None
def logo_img(px):
    """icon.svg 재현: 64 단위 둥근 사각형, 대각선 57%에서 #18181d→#7457f5, 흰 '단'."""
    S = px * 4
    g = Image.new("RGB", (S, S), INK)
    gd = ImageDraw.Draw(g)
    # 대각선 x+y > 0.575*2S 영역을 보라로
    t = 0.575 * 2 * S
    gd.polygon([(t - S, S), (S, t - S), (S, S)] if t > S else [(0, t), (t, 0), (S, 0), (S, S), (0, S)], fill=PURPLE)
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, S - 1, S - 1), S * 16 // 64, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(g, (0, 0), m)
    d = ImageDraw.Draw(out)
    fnt = F("ExtraBold", S * 26 // 64)
    d.text((S / 2, S * 42 / 64), "단", font=fnt, fill=(255, 255, 255), anchor="ms")
    return out.resize((px, px), Image.LANCZOS)

def logo_frame(f):
    global LOGO
    k = f - 900
    img = Image.new("RGB", (W, H), PAPER)
    if LOGO is None:
        LOGO = logo_img(300)
    # 오버슈트 있게 튀어나온다
    s = lerp(0.6, 1.0, ease_out(k / 8)) * (1 + 0.06 * math.exp(-max(0, k - 8) / 3) if k >= 8 else 1)
    lg = LOGO.resize((max(1, int(300 * s)), max(1, int(300 * s))), Image.LANCZOS)
    img.paste(lg, ((W - lg.width) // 2, int(800 - lg.height / 2)), lg)
    if k >= 8:
        a = ease_out((k - 8) / 6)
        layer = img.copy()
        draw_center(layer, "단지광장", "Black", 132, 1060, INK)
        img = Image.blend(img, layer, a)
    if k >= 16:
        a = ease_out((k - 16) / 6)
        layer = img.copy()
        draw_center(layer, "danji.life", "Medium", 50, 1170, (110, 110, 118))
        img = Image.blend(img, layer, a)
    if f >= TOTAL - 18:  # 마지막 0.6초 페이드
        img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), (f - (TOTAL - 18)) / 18)
    return img

def frame(f):
    if f < 60: return hook_frame(f)
    if f < 300: return opening_frame(f)
    if f < 480: return drop_frame(f)
    if f < 540: return end4_frame(f)
    if f < 780: return app_frame(f)
    if f < 840: return declare_frame(f)
    if f < 900: return brand_frame(f)
    return logo_frame(f)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stills":
        os.makedirs(os.path.join(BUILD, "stills"), exist_ok=True)
        for f in map(int, sys.argv[2:]):
            frame(f).save(os.path.join(BUILD, "stills", f"{f:04d}.jpg"), quality=85)
        sys.exit()
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = os.path.join(HERE, "out", "danji-promo-9x16.mp4")
    p = subprocess.Popen([ff, "-hide_banner", "-loglevel", "error", "-y",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-i", os.path.join(BUILD, "music.wav"),
                          "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out],
                         stdin=subprocess.PIPE)
    for f in range(TOTAL):
        p.stdin.write(frame(f).tobytes())
        if f % 60 == 0:
            print("frame", f, flush=True)
    p.stdin.close(); p.wait()
    print("wrote", out)
