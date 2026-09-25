"""단지광장 홍보 영상 배경음악. 120 BPM, F단조, 32초 + 꼬리.

전부 코드로 합성한다(샘플·루프 없음 → 저작권 문제 없음).
구간은 구성안 타임라인과 박 단위로 맞춘다. 한 박 = 0.5초, 한 마디 = 2초.
"""
import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
import wave, sys

SR = 44100
BPM = 120
BEAT = 60 / BPM
BAR = BEAT * 4
DUR = 34.0
N = int(SR * DUR)
rng = np.random.default_rng(7)

L = np.zeros(N); R = np.zeros(N)          # 드라이 버스
RVL = np.zeros(N); RVR = np.zeros(N)      # 리버브 센드
SC = np.ones(N)                           # 사이드체인 게인


def t_(sec):
    return np.arange(int(SR * sec)) / SR


def put(buf, sig, at, gain=1.0):
    i = int(at * SR)
    if i >= N:
        return
    j = min(N, i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def place(sig, at, gain=1.0, pan=0.0, rev=0.0):
    gl = np.cos((pan + 1) * np.pi / 4) * np.sqrt(2)
    gr = np.sin((pan + 1) * np.pi / 4) * np.sqrt(2)
    put(L, sig, at, gain * gl); put(R, sig, at, gain * gr)
    if rev:
        put(RVL, sig, at, gain * rev * gl); put(RVR, sig, at, gain * rev * gr)


def lp(x, fc, order=2):
    return sosfilt(butter(order, min(fc, SR / 2 - 100), "low", fs=SR, output="sos"), x)


def hp(x, fc, order=2):
    return sosfilt(butter(order, fc, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def sweep_lp(x, f0, f1, block=512):
    """블록마다 차단주파수를 바꾸는 로우패스(필터 여닫기)."""
    out = np.zeros_like(x)
    nb = int(np.ceil(len(x) / block))
    zi = None
    for b in range(nb):
        fc = f0 * (f1 / f0) ** (b / max(1, nb - 1))
        sos = butter(2, min(fc, SR / 2 - 100), "low", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2))
        seg = x[b * block:(b + 1) * block]
        out[b * block:b * block + len(seg)], zi = sosfilt(sos, seg, zi=zi)
    return out


# ── 악기 ────────────────────────────────────────────────
def kick(dec=0.32, f_hi=150, f_lo=46):
    t = t_(dec * 2.2)
    f = f_lo + (f_hi - f_lo) * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t / dec)
    click = hp(rng.standard_normal(len(t)), 2500) * np.exp(-t / 0.004) * 0.35
    return np.tanh(1.6 * (s + click))


def sub808(freq, dec=0.9):
    t = t_(dec * 2.5)
    f = freq * (1 + 1.6 * np.exp(-t / 0.03))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t / dec)
    return np.tanh(2.2 * s) * 0.9


def impact(freq=43.65):
    """오프닝 '쾅'. 808 서브 + 킥 트랜지언트 + 저역 노이즈 폭발."""
    k = kick(0.25, 180, 50)
    s = sub808(freq, 0.85)
    t = t_(1.2)
    nz = lp(rng.standard_normal(len(t)), 900) * np.exp(-t / 0.18) * 0.5
    out = np.zeros(len(s)); out[:len(k)] += k * 0.8; out += s
    out[:len(nz)] += nz
    return out


def hat(dec=0.035, bright=8000):
    t = t_(0.12)
    return hp(rng.standard_normal(len(t)), bright) * np.exp(-t / dec) * 0.5


def clap():
    t = t_(0.35)
    n = rng.standard_normal(len(t))
    env = np.zeros(len(t))
    for off in (0, 0.011, 0.022):
        i = int(off * SR)
        env[i:] += np.exp(-(t[: len(t) - i]) / (0.006 if off < 0.02 else 0.09))
    return bp(n, 900, 3200) * env * 0.7


def snare(dec=0.12):
    t = t_(0.3)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05) * 0.5
    nz = bp(rng.standard_normal(len(t)), 1500, 7000) * np.exp(-t / dec)
    return body + nz


def saw(freq, t, detune=0.0):
    ph = (freq * (1 + detune) * t) % 1.0
    return 2 * ph - 1


def pad_chord(freqs, dur, cutoff=1400, amp=0.12):
    """디튠 톱니 3보이스를 로우패스로 눌러 따뜻하게. 슈퍼소우처럼 밝히지 않는다."""
    t = t_(dur)
    l = np.zeros(len(t)); r = np.zeros(len(t))
    for f in freqs:
        l += saw(f, t, -0.004) + 0.6 * saw(f, t, 0.007)
        r += saw(f, t, 0.004) + 0.6 * saw(f, t, -0.007)
    att = np.minimum(1, t / 0.04); rel = np.minimum(1, (dur - t) / 0.08)
    env = att * np.clip(rel, 0, 1)
    return lp(l, cutoff, 2) * env * amp, lp(r, cutoff, 2) * env * amp


def pluck(freq, dur=0.22, bright=3500):
    t = t_(dur)
    s = saw(freq, t) * 0.6 + np.sin(2 * np.pi * freq * t) * 0.6
    fenv = bright * np.exp(-t / 0.05) + 400
    # 간이 필터 엔벨로프: 두 번 걸러 섞기
    s = lp(s, bright) * np.exp(-t / 0.05) + lp(s, 500) * np.exp(-t / 0.12) * 0.6
    return s * 0.35


def bell(freq, dur=3.0):
    t = t_(dur)
    s = sum(a * np.sin(2 * np.pi * freq * m * t) * np.exp(-t / d)
            for m, a, d in ((1, 1, 1.6), (2.0, 0.35, 0.8), (3.01, 0.18, 0.4), (4.2, 0.08, 0.25)))
    return s * 0.22


def riser(dur, f0=400, f1=9000):
    t = t_(dur)
    n = rng.standard_normal(len(t))
    out = np.zeros(len(t)); block = 1024
    for b in range(0, len(t), block):
        c = f0 * (f1 / f0) ** (b / len(t))
        out[b:b + block] = bp(n[b:b + block], c * 0.7, min(c * 1.3, SR / 2 - 200), 1)
    return out * (t / dur) ** 2 * 0.35


def sidechain(at, depth=0.65, rel=0.14):
    i = int(at * SR); t = t_(0.5)
    g = 1 - depth * np.exp(-t / rel)
    j = min(N, i + len(g))
    SC[i:j] = np.minimum(SC[i:j], g[: j - i])


# ── 화음·근음 (F단조) ────────────────────────────────────
Fm9 = [174.61, 207.65, 261.63, 311.13, 392.00]
Dbma7 = [138.59, 174.61, 207.65, 261.63]
Ab9 = [207.65, 261.63, 311.13, 466.16]
Eb9 = [155.56, 196.00, 233.08, 349.23]
ROOT = {"Fm9": 43.65, "Dbma7": 69.30, "Ab9": 51.91, "Eb9": 77.78}
CH = {"Fm9": Fm9, "Dbma7": Dbma7, "Ab9": Ab9, "Eb9": Eb9}

PADL = np.zeros(N); PADR = np.zeros(N)   # 사이드체인 걸리는 버스

def pad_at(name, at, dur, cutoff=1400, amp=0.12):
    l, r = pad_chord(CH[name], dur, cutoff, amp)
    put(PADL, l, at); put(PADR, r, at)
    put(RVL, l, at, 0.35); put(RVR, r, at, 0.35)


# ── 0:00–0:02 훅: 무음, 방 소리, 종이 ───────────────────
room = lp(rng.standard_normal(int(SR * 2.0)), 300) * 0.02
place(room, 0.0)
paper = bp(rng.standard_normal(int(SR * 0.5)), 2000, 7000) * \
        (np.sin(np.linspace(0, np.pi, int(SR * 0.5))) ** 2) * \
        (0.5 + 0.5 * np.abs(np.sin(np.linspace(0, 40, int(SR * 0.5))))) * 0.12
place(paper, 0.25, pan=0.2, rev=0.1)
# 1.0~2.0: 아주 낮은 긴장음(F 드론)이 스며든다
t = t_(1.0)
drone = np.sin(2 * np.pi * 87.31 * t) * (t / 1.0) ** 2 * 0.08
place(drone, 1.0)

# ── 0:02–0:10 오프닝: 2박마다 '쾅' 8번 ──────────────────
open_roots = [43.65, 43.65, 43.65, 43.65, 69.30, 69.30, 51.91, 77.78]
for k, f in enumerate(open_roots):
    at = 2.0 + k * 1.0
    place(impact(f), at, gain=0.8, rev=0.25)
# 어둡고 낮은 패드가 뒤에 깔린다 (3마디째부터)
pad_at("Fm9", 4.0, 4.0, cutoff=500, amp=0.07)
pad_at("Dbma7", 8.0, 1.5, cutoff=700, amp=0.08)
# 리버스 심벌 + 라이저, 9.5~10.0은 완전 무음 한 박
place(riser(1.5, 300, 7000), 8.0, gain=1.0, rev=0.2)

# ── 0:10–0:18 드롭 ────────────────────────────────────
drop_chords = ["Fm9", "Dbma7", "Ab9"]
for b, name in enumerate(drop_chords):
    at = 10.0 + b * BAR
    pad_at(name, at, BAR, cutoff=2400, amp=0.11)
    for q in range(4):
        tq = at + q * BEAT
        place(kick(), tq, gain=0.95)
        sidechain(tq)
        place(sub808(ROOT[name], 0.35)[: int(SR * 0.45)], tq + BEAT / 2, gain=0.55)
        place(hat(), tq + BEAT / 2, gain=0.6, pan=0.25)
        place(hat(0.015, 10000), tq + BEAT * 0.25, gain=0.25, pan=-0.3)
        place(hat(0.015, 10000), tq + BEAT * 0.75, gain=0.25, pan=-0.3)
        if q in (1, 3):
            place(clap(), tq, gain=0.8, rev=0.25)
    # 16분 플럭 아르페지오 (한 옥타브 위)
    tones = CH[name] * 2
    for s in range(16):
        f = tones[(s * 3) % len(tones)] * 2
        place(pluck(f), at + s * BEAT / 4, gain=0.55, pan=(-0.35 if s % 2 else 0.35), rev=0.3)

# 0:16–0:18 드롭 끝: Eb9, 스네어 롤, 필터 닫힘
at = 16.0
l, r = pad_chord(Eb9, BAR, 2400, 0.11)
put(PADL, sweep_lp(l, 2400, 350), at); put(PADR, sweep_lp(r, 2400, 350), at)
for q in range(4):
    place(kick(), at + q * BEAT, gain=0.9); sidechain(at + q * BEAT)
roll = [i * BEAT / 4 for i in range(8)] + [BEAT * 2 + i * BEAT / 8 for i in range(16)]
for i, tr in enumerate(roll):
    place(snare(), at + tr, gain=0.25 + 0.5 * i / len(roll), pan=0.1, rev=0.15)

# ── 0:18–0:26 실제 앱: 하프타임, UI가 읽히게 비운다 ───────
half = ["Fm9", "Dbma7", "Ab9", "Eb9"]
for b, name in enumerate(half):
    at = 18.0 + b * BAR
    cut = 600 if b < 3 else None
    l, r = pad_chord(CH[name], BAR, 900, 0.09)
    if b == 3:  # 0:24–0:26 필터를 연다
        l, r = sweep_lp(l, 700, 4000), sweep_lp(r, 700, 4000)
        place(riser(BAR, 500, 9000), at, gain=0.8, rev=0.2)
    put(PADL, l, at); put(PADR, r, at)
    put(RVL, l, at, 0.35); put(RVR, r, at, 0.35)
    place(kick(0.4), at, gain=0.85); sidechain(at, 0.5, 0.25)
    place(sub808(ROOT[name], 0.8), at, gain=0.5)
    place(clap(), at + 2 * BEAT, gain=0.6, rev=0.45)
    place(hat(0.05, 7000), at + BEAT, gain=0.25, pan=0.3)
    place(hat(0.05, 7000), at + 3 * BEAT, gain=0.25, pan=0.3)
    for s in (0, 3, 6, 10, 12):  # 성긴 플럭
        f = CH[name][s % len(CH[name])] * 2
        place(pluck(f, 0.4, 1800), at + s * BEAT / 4, gain=0.35, pan=0.2, rev=0.5)

# ── 0:26–0:28 '사는 사람이 압니다.' 마지막 임팩트 ─────────
place(impact(43.65), 26.0, gain=1.0, rev=0.4)
pad_at("Fm9", 26.0, 2.0, cutoff=1800, amp=0.10)

# ── 0:28–0:32 브랜드 한 줄 + 로고 ───────────────────────
pad_at("Dbma7", 28.0, 2.0, cutoff=1100, amp=0.08)
l, r = pad_chord(Fm9, 5.5, 900, 0.08)
fade = np.linspace(1, 0, len(l)) ** 1.5
put(PADL, l * fade, 30.0); put(PADR, r * fade, 30.0)
put(RVL, l * fade, 30.0, 0.5); put(RVR, r * fade, 30.0, 0.5)
place(bell(698.46), 30.0, gain=0.9, rev=0.7)          # 로고 등장: F5 벨
place(bell(1046.5, 2.2), 30.0 + BEAT * 1.5, gain=0.35, pan=0.3, rev=0.7)
place(sub808(43.65, 1.2), 30.0, gain=0.35)

# ── 믹스 ──────────────────────────────────────────────
L += PADL * SC; R += PADR * SC

def ir(sec, seed):
    g = np.random.default_rng(seed)
    t = t_(sec)
    return g.standard_normal(len(t)) * np.exp(-t / (sec / 5)) * 0.05

rl = fftconvolve(lp(hp(RVL, 200), 6000), ir(2.6, 1))[:N]
rr = fftconvolve(lp(hp(RVR, 200), 6000), ir(2.6, 2))[:N]
L += rl; R += rr

mix = np.stack([L, R], 1)
mix = hp(mix.T, 25).T
peak = np.max(np.abs(mix))
mix = np.tanh(mix / peak * 1.4) / np.tanh(1.4)       # 부드러운 클리핑
mix *= 10 ** (-1.0 / 20) / np.max(np.abs(mix))       # -1 dBFS
fade = np.ones(N); fn = int(SR * 1.0); fade[-fn:] = np.linspace(1, 0, fn)
mix *= fade[:, None]

# 0:09.5–0:10.0 드롭 직전 한 박은 완전 무음(꼬리까지 자른다)
g = np.ones(N)
a, b = int(9.5 * SR), int(10.0 * SR); f = int(0.015 * SR)
g[a - f:a] = np.linspace(1, 0, f); g[a:b] = 0
mix *= g[:, None]

out = sys.argv[1] if len(sys.argv) > 1 else "music.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print("wrote", out, f"{DUR}s")
