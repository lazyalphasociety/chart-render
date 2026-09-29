# -*- coding: utf-8 -*-
"""시그널 카드용 차트 이미지 — **우리가 직접 그린다** (B안, 2026-09-29).

왜 직접 그리나
──────────────────────────────────────────────────────────────────────
TradingView 웹훅에는 이미지가 안 담긴다. 제3자 스냅샷 서비스(A안)는
TradingView 세션 쿠키를 넘겨야 하고, 그 쿠키는 주기적으로 죽는다.
여기는 **의존성이 없다** — OHLCV 와 웹훅이 이미 주는 값만으로 그린다.
A안이 막히면 그대로 이게 남는다.

이평선 기간을 적는 이유 (2026-09-29 정정)
──────────────────────────────────────────────────────────────────────
초판은 「기간 숫자 = 설정 노출」이라 보고 범례를 단기·중기·장기로만 썼다.
**그 판단은 과했다.** 지표 소스를 다시 보니

  · 멤버판에 `show_ma_labels` 옵션이 있어 켜면 차트에 `EMA 8` 라벨이 뜬다
  · 대시보드에 `8/14/21/55 (Auto)` 가 상시 표시된다
  · 파인 3파일 분석의 배포 경계는 **웹훅 JSON 템플릿과 봇 연동 필드**이지
    이평선 기간이 아니다

즉 기간은 **회원이 이미 자기 차트에서 보고 있는 값**이다. 숨기면 오히려
「내 차트의 8선과 이 그림의 선이 같은 건가」를 매번 헷갈리게 만든다.

**여전히 이미지에 안 들어가는 것**: 조건식 임계값 — 에너지 리밋, ADR·RS
문턱, 관문 조건, 점수 계산식. 그건 회원 화면에도 없고 앞으로도 안 나간다.

무엇을 안 그리는가
──────────────────────────────────────────────────────────────────────
· 지표의 밴드·라벨 같은 고유 시각 요소는 재현하지 않는다. 재현하려면 파인
  로직을 파이썬으로 옮겨야 하고, 그건 소스 이중 관리다.
· 청산 전략선을 강조하지 않는다. 진입 그림에 청산 기준을 그리면 규칙이
  둘이 되고, 둘이면 하나는 반드시 틀린다. (「새로 살 자리」 v25.0 §2)
· 이모지는 안 쓴다. matplotlib 에서 컬러 이모지는 네모로 나온다.
"""
import io
import re
import warnings

import matplotlib
matplotlib.use("Agg")
warnings.filterwarnings("ignore", message=".*missing from font.*")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.patches import Rectangle             # noqa: E402
from matplotlib import font_manager                  # noqa: E402

# ── 팔레트 ──────────────────────────────────────────────────────────
SURFACE = "#1a1a19"
INK = "#ffffff"
INK_2 = "#c3c2b7"
INK_MUTED = "#898781"
GRID = "#2c2c2a"

#  캔들 — 국내 관례(적색 상승)로 바꾸려면 UP_IS_GREEN 한 줄만 바꾼다.
UP_IS_GREEN = True
_GREEN, _RED = "#2f9e5e", "#c04a42"
UP = _GREEN if UP_IS_GREEN else _RED
DOWN = _RED if UP_IS_GREEN else _GREEN

#  이동평균 — **지표의 기본 색 그대로.** 회원이 자기 차트에서 보던 색과
#  같아야 같은 선이라는 걸 설명 없이 안다.
#    EMA1 흰색 / EMA2 파랑 rgb(30,100,255) / EMA3 주황 rgb(255,140,0)
#    MA4 노랑 rgb(255,210,0) / MA5 보라 rgb(140,80,255) / MA6 빨강 rgb(255,80,80)
MA_COLORS = ("#ffffff", "#1e64ff", "#ff8c00",
             "#ffd200", "#8c50ff", "#ff5050")
#  지표와 같은 굵기 서열(1·1·1 / 2·2·3). 장기로 갈수록 두껍다.
MA_WIDTHS = (1.0, 1.15, 1.3, 1.7, 1.9, 2.3)

#  프리셋별 기간 — 지표와 **같은 값**이어야 한다. 바뀌면 여기도 바꾼다.
#    Classic : EMA 5/10/20  + SMA 50/100/200
#    Fibo    : EMA 8/14/21  + EMA 55 + SMA 100/200
#  (기간, 방식) 여섯. MA4 만 프리셋에 따라 EMA/SMA 가 갈린다.
PRESET_MA = {
    "CLASSIC": ((5, "e"), (10, "e"), (20, "e"),
                (50, "s"), (100, "s"), (200, "s")),
    "FIBO":    ((8, "e"), (14, "e"), (21, "e"),
                (55, "e"), (100, "s"), (200, "s")),
}
PRESET_DEFAULT = "CLASSIC"

#  장기 3선(50·100·200)을 그릴지. 끄면 단기 3선만.
SHOW_LONG_DEFAULT = True

#  레벨선 — 데이터가 아니라 주석이다.
#  진입은 **회백색**이다. 순백으로 하면 흰 EMA1 과 헷갈린다.
C_ENTRY = "#c3c2b7"
C_STOP = "#d03b3b"      # status critical
C_TARGET = "#0ca30c"    # status good

#  레벨 종류 → (색, 점선 모양, 허용 여유).
#  허용 여유가 클수록 그 선을 살리려고 y 범위를 더 벌린다. 카드의 본체가 되는
#  선(기준가·손절)은 거의 무조건 살리고, 먼 목표는 포기하고 칩만 남긴다.
LEVEL_STYLE = {
    "base":   (C_ENTRY, (4, 2), 3.0),     # 진입가 · 평단 · 기준선
    "stop":   (C_STOP, (5, 3), 3.0),      # 손절 · 트레일링
    "target": (C_TARGET, (2, 2), 0.85),   # 목표1 · TP
    "far":    (C_TARGET, (2, 2), 0.40),   # 목표2 — 멀면 포기
}

# ── 시그널 한글 이름 ────────────────────────────────────────────────
#  **카탈로그(`lazy/catalog.py`)가 원본이다.** 여기 표는 카탈로그를 못
#  불러왔을 때의 폴백일 뿐이다. 지어내지 않는다 — 카드와 그림이 서로 다른
#  이름을 쓰면 같은 신호가 둘로 보인다.
SIGNAL_KO = {
    "ENTRY": "정석 진입", "BREAKOUT_ENTRY": "돌파 진입",
    "AGGRO_ENTRY": "공격 진입", "PULLBACK_ENTRY": "눌림 진입",
    "PYRAMID": "피라미딩 추매", "PULLBACK": "눌림목 추매",
    "PEG_PULLBACK": "PEG 되돌림", "PEG_REBREAK": "PEG 재돌파",
    "CHANNEL_BREAKOUT": "박스권 돌파",
    "MOMENTUM_BUY": "모멘텀 BUY", "MOMENTUM_SELL": "모멘텀 SELL",
    "PARTIAL_SELL_1": "1차 분할청산", "PARTIAL_SELL_2": "2차 분할청산",
    "OVERHEAT": "과열 경고", "TRIM": "부분 익절고려",
    "TP1": "TP1 달성", "TP2": "TP2 달성", "CHANNEL_BREAK": "박스권 이탈",
    "FINAL_EXIT": "최종 청산", "BREAKOUT_EXIT": "돌파 청산",
    "CRASH_SL": "크래시 손절",
    "SETUP": "셋업 형성", "VCP": "VCP 형성", "VOL_CONTRACT": "수급 수축",
}
CONTRACTION_KO = {"VCP": "VCP 수축", "COIL": "응축(코일)"}

#  이모지·변이 셀렉터 — matplotlib 에서 네모가 되므로 통째로 걷어낸다.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF←-⇿⌀-➿︀-️‍]+")


def _strip_emoji(s):
    return _EMOJI.sub("", str(s)).strip()


def signal_ko(v, catalog=None):
    """영문 키든, 이미 한글인 `type` 이든 **화면에 쓸 한글 한 마디**로.

    웹훅 `signal.type` 은 이미 「🚀 돌파 진입」처럼 오는 경우가 있다.
    그때는 이모지만 벗기면 되고, 영문 키로 올 때만 표를 탄다.
    catalog 를 넘기면 그쪽이 먼저다 (카드와 이름을 맞추기 위함).
    """
    if not v:
        return ""
    raw = str(v).strip()
    key = _strip_emoji(raw).upper().replace(" ", "_")
    if catalog:
        hit = catalog.get(key) or catalog.get(raw)
        if hit:
            return _strip_emoji(hit)
    if key in SIGNAL_KO:
        return SIGNAL_KO[key]
    return _strip_emoji(raw)          # 이미 한글이면 그대로


def ma_spec(sig, show_long=None):
    """이 종목에 실제로 쓰인 이평선 [(기간, 방식)] 목록.

    우선순위: 명시 `ema_lens` → 웹훅 `preset` → 기본 Classic.
    웹훅에 `symbol.preset` 이 이미 있어서 파인을 고칠 필요가 없다.
    """
    spec = None
    given = sig.get("ema_lens")
    if given and len(given) >= 3:
        #  숫자만 넘겨도 되게 — 50 이상은 SMA 로 본다(지표와 같은 규칙).
        spec = [(int(v), "e" if int(v) < 50 else "s") for v in given]
    if spec is None:
        p = str(sig.get("preset") or PRESET_DEFAULT).strip().upper()
        spec = list(PRESET_MA[PRESET_DEFAULT])
        for k in PRESET_MA:
            if k in p:
                spec = list(PRESET_MA[k])
                break
    want = SHOW_LONG_DEFAULT if show_long is None else bool(show_long)
    return spec if want else spec[:3]


def ma_lens(sig, show_long=None):
    """기간만 (하위호환)."""
    return tuple(p for p, _ in ma_spec(sig, show_long))


def _font():
    """한글이 되는 패밀리 이름. 확보 로직은 `krfont` 가 들고 있다."""
    try:
        from krfont import ensure
        return ensure() or "DejaVu Sans"
    except Exception:                                   # noqa: BLE001
        #  모듈 단독으로 쓸 때(로컬 미리보기)는 설치된 것만 훑는다.
        have = {f.name for f in font_manager.fontManager.ttflist}
        for name in ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans KR",
                     "NanumGothic", "Malgun Gothic", "AppleGothic"):
            if name in have:
                return name
        for name in sorted(have):
            if "CJK" in name and "Serif" not in name:
                return name
        return "DejaVu Sans"


def _ema(vals, n):
    """지표와 같은 EMA. 단순이평으로 그리면 선이 미묘하게 어긋난다."""
    if not vals:
        return []
    k = 2.0 / (n + 1.0)
    out, prev = [], None
    for i, v in enumerate(vals):
        if i < n - 1:
            out.append(None)
            continue
        if prev is None:                       # 시드는 첫 n봉 단순평균
            prev = sum(vals[i - n + 1:i + 1]) / float(n)
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _sma(vals, n):
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        out.append(s / float(n) if i + 1 >= n else None)
    return out


def _ma_series(vals, n, kind):
    return _ema(vals, n) if kind == "e" else _sma(vals, n)


def _fmt_price(v, market="KR"):
    """값의 크기에 자릿수를 맞춘다.

    크립토는 한 화면에 `0.09939` 도 `104,300` 도 온다. 소수 두 자리로 고정하면
    잔돈 코인의 진입·손절·목표가 전부 `$0.10` 이 돼 **다른 선이 같은 값을
    가리킨다.** 값이 작을수록 자릿수를 늘린다.
    """
    if v is None:
        return "-"
    if str(market).upper().startswith("K"):
        return format(int(round(v)), ",")
    a = abs(v)
    if a >= 500:
        return "$" + format(int(round(v)), ",")
    if a >= 1:
        return "$%.2f" % v
    if a >= 0.01:
        return "$%.4f" % v
    return "$%.6f" % v


def render(sig, candles, emas=None, sample=False, catalog=None,
           show_long=None):
    """PNG 바이트를 돌려준다. 실패하면 예외 — 부르는 쪽이 감싸서 카드는 내보낸다.

    sig     : {name, ticker, market, signal, preset|ema_lens, contraction,
               trigger_price, sl, tp1, tp2, asof}
    candles : [{date, open, high, low, close, volume}, ...] 오래된 것 → 최신
    emas    : {"e1": [...], "e2": [...], "e3": [...]} 지표가 준 값이 있으면
    catalog : {시그널키: 한글이름} — `lazy/catalog.py` 에서 넘기면 그쪽이 우선
    show_long: 장기 3선(50·100·200) 표시 여부. None 이면 모듈 기본값.

    ※ 200선을 표시 구간 전체에 그리려면 **candles 가 320봉 이상**이어야 한다.
      모자라면 앞쪽이 비는 채로 그려진다(끊긴 선).
    """
    fam = _font()
    plt.rcParams.update({
        "font.family": fam,
        "axes.unicode_minus": False,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    })

    allc = list(candles)
    #  이동평균은 **전체 이력으로 계산**하고 표시 구간만 자른다.
    all_close = [float(r["close"]) for r in allc]
    c = allc[-120:]
    n = len(c)
    o = [float(r["open"]) for r in c]
    h = [float(r["high"]) for r in c]
    lo = [float(r["low"]) for r in c]
    cl = [float(r["close"]) for r in c]
    vol = [float(r.get("volume") or 0) for r in c]
    x = list(range(n))
    market = sig.get("market", "KR")
    spec = ma_spec(sig, show_long)

    fig = plt.figure(figsize=(8.0, 4.5), dpi=160)
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1.0], hspace=0.06,
                          left=0.015, right=0.812, top=0.845, bottom=0.085)
    ax = fig.add_subplot(gs[0])
    av = fig.add_subplot(gs[1], sharex=ax)

    for a in (ax, av):
        a.set_facecolor(SURFACE)
        for sp in a.spines.values():
            sp.set_visible(False)
        a.tick_params(colors=INK_MUTED, labelsize=7, length=0)
        a.set_axisbelow(True)
        a.yaxis.tick_right()
    #  격자는 가격축에만. 거래량 칸의 가로선은 읽을 눈금이 없어 장식일 뿐이다.
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.9)
    av.grid(False)

    # ── 이동평균 ──────────────────────────────────────────────────
    series = []
    if emas:
        for key in ("e1", "e2", "e3", "m4", "m5", "m6"):
            if emas.get(key):
                series.append(list(emas[key])[-n:])
    if len(series) < len(spec):
        series = [_ma_series(all_close, p, k)[-n:] for p, k in spec]
    #  장기 3선은 **배경 문맥**이라 한 톤 물러난다. 특히 200선 빨강은 손절선
    #  빨강과 첫인상이 겹치므로(하나는 곡선·실선, 하나는 수평·점선) 눌러 둔다.
    for i, ser in enumerate(series[:len(spec)]):
        ax.plot(x, ser, color=MA_COLORS[i], linewidth=MA_WIDTHS[i],
                alpha=0.95 if i < 3 else 0.68,
                solid_capstyle="round", zorder=2)

    # ── 캔들 ──────────────────────────────────────────────────────
    bw = 0.62
    for i in range(n):
        up = cl[i] >= o[i]
        col = UP if up else DOWN
        ax.plot([i, i], [lo[i], h[i]], color=col, linewidth=0.9,
                solid_capstyle="round", zorder=3)
        y0, y1 = (o[i], cl[i]) if up else (cl[i], o[i])
        ax.add_patch(Rectangle((i - bw / 2, y0), bw, max(y1 - y0, 1e-9),
                               facecolor=col, edgecolor=col,
                               linewidth=0.6, zorder=4))

    # ── 레벨선 — 우변 가격 칩으로 직접 라벨 ────────────────────────
    #  마지막 숫자는 **허용 여유**다. 클수록 그 선을 살리려고 y를 더 벌린다.
    #  진입·손절은 카드의 본체라 거의 무조건 살리고, 목표2는 멀면 포기한다.
    #  카드가 여섯 종류다(관찰·진입·추매·관리·청산·모멘텀). 같은 자리의 선이
    #  카드마다 다른 이름이다 — 진입 카드의 「진입」은 청산 카드에선 「평단」이다.
    #  sig["levels"] 로 직접 넘기면 그대로 쓰고, 없으면 진입 카드 기본값.
    lv = sig.get("levels")
    if lv:
        lv = [(str(t[0]), t[1], LEVEL_STYLE.get(t[2], LEVEL_STYLE["base"])[0],
               LEVEL_STYLE.get(t[2], LEVEL_STYLE["base"])[1],
               LEVEL_STYLE.get(t[2], LEVEL_STYLE["base"])[2])
              for t in lv]
    else:
        lv = [("진입", sig.get("trigger_price"), C_ENTRY, (4, 2), 3.0),
              ("손절", sig.get("sl"), C_STOP, (5, 3), 3.0),
              ("목표1", sig.get("tp1"), C_TARGET, (2, 2), 0.85),
              ("목표2", sig.get("tp2"), C_TARGET, (2, 2), 0.40)]
    lv = [t for t in lv if t[1] not in (None, 0)]

    #  레벨이 너무 멀면 y 범위를 벌리지 않는다 — 캔들이 납작해지면 그림이 죽는다.
    span = max(h) - min(lo)
    keep, off = [], []
    for t in lv:
        v, tol = float(t[1]), t[4]
        if min(lo) - span * tol <= v <= max(h) + span * tol:
            keep.append(t)
        else:
            off.append(t)
    lows = list(lo) + [float(t[1]) for t in keep]
    highs = list(h) + [float(t[1]) for t in keep]
    pad = (max(highs) - min(lows)) * 0.06
    y0a, y1a = min(lows) - pad, max(highs) + pad
    ax.set_ylim(y0a, y1a)
    ax.set_xlim(-1, n + 0.5)
    plt.setp(ax.get_xticklabels(), visible=False)
    ax.tick_params(axis="y", labelsize=7, colors=INK_MUTED)
    #  FixedLocator로 고정한 뒤 라벨을 붙인다 (set_yticks 없이 라벨만 바꾸면 경고).
    _yt = [t for t in ax.get_yticks() if y0a <= t <= y1a]
    ax.set_yticks(_yt)
    ax.set_yticklabels([_fmt_price(t, market) for t in _yt])

    #  선은 제 값에 긋고, **칩만** 겹치지 않게 벌린다.
    plan = []
    for label, val, col, dash, _tol in keep:
        v = float(val)
        ax.axhline(v, color=col, linewidth=1.35, linestyle=(0, dash),
                   alpha=0.95, zorder=5)
        plan.append([v, v, label, col])
    for label, val, col, dash, _tol in off:
        v = float(val)
        edge = y1a - (y1a - y0a) * 0.03 if v > y1a else y0a + (y1a - y0a) * 0.03
        plan.append([v, edge, label + ("↑" if v > y1a else "↓"), col])

    gap = (y1a - y0a) * 0.062
    plan.sort(key=lambda t: t[1])
    for i in range(1, len(plan)):                   # 아래에서 위로 밀어 올린다
        if plan[i][1] - plan[i - 1][1] < gap:
            plan[i][1] = plan[i - 1][1] + gap
    over = plan[-1][1] - (y1a - gap * 0.4) if plan else 0
    if over > 0:                                    # 위로 넘쳤으면 통째로 내린다
        for t in plan:
            t[1] -= over

    for v, yy, label, col in plan:
        ax.annotate(" %s %s " % (label, _fmt_price(v, market)),
                    xy=(1.10, yy), xycoords=("axes fraction", "data"),
                    va="center", ha="left", fontsize=7.2,
                    color="#0b0b0b" if col == C_ENTRY else INK,
                    bbox=dict(boxstyle="round,pad=0.30", fc=col, ec="none",
                              alpha=0.95),
                    zorder=6, annotation_clip=False)

    #  마지막 봉이 주인공이다.
    ax.annotate("", xy=(n - 1, h[-1] + (y1a - y0a) * 0.025),
                xytext=(n - 1, h[-1] + (y1a - y0a) * 0.085),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.1),
                zorder=7)

    # ── 거래량 ────────────────────────────────────────────────────
    for i in range(n):
        av.bar(i, vol[i], width=bw,
               color=(UP if cl[i] >= o[i] else DOWN), alpha=0.5, zorder=3)
    av.set_ylim(0, max(vol) * 1.25 if max(vol) else 1)
    av.set_yticklabels([])
    step = max(n // 6, 1)
    av.set_xticks(x[::step])
    av.set_xticklabels([str(c[i].get("date", ""))[-5:] for i in x[::step]])

    # ── 머리글 ────────────────────────────────────────────────────
    name = sig.get("name") or sig.get("ticker") or ""
    tk = sig.get("ticker") or ""
    fig.text(0.015, 0.945, "%s  %s" % (name, tk), color=INK,
             fontsize=13, fontweight="bold", va="center")

    #  숫자(거래량 배수·손익비)는 카드 본문이 이미 말한다. 그림은 그림만 한다.
    chips = []
    _s = signal_ko(sig.get("signal") or sig.get("type"), catalog)
    if _s:
        chips.append(_s)
    ctr = str(sig.get("contraction") or "").upper()
    if ctr in CONTRACTION_KO:
        chips.append(CONTRACTION_KO[ctr])
    if chips:
        fig.text(0.015, 0.888, "   ·   ".join(chips), color=INK_2,
                 fontsize=9.0, va="center")

    #  범례 — **기간을 그대로 적는다.** 회원이 자기 차트에서 보던 그 선이다.
    #  색만으로 기대지 않게 굵기도 다르고, 숫자가 직접 라벨 노릇을 한다.
    #  장기선은 화면(가격 범위) 밖으로 나가는 일이 흔하다. **그건 그냥 뺀다** —
    #  화면에 없는 선을 범례가 가리키면 그게 더 헷갈린다.
    items = []
    for i, (per, _k) in enumerate(spec):
        ser = [v for v in series[i] if v is not None] if i < len(series) else []
        if ser and (max(ser) < y0a or min(ser) > y1a):
            continue                       # 통째로 화면 밖 — 범례에서도 뺀다
        items.append(("%d선" % per, MA_COLORS[i]))

    #  글자 수에 맞춰 폭을 잡고 오른쪽 끝에 붙인다.
    def _w(lab):
        return 0.0205 + 0.0098 * len(lab) + 0.010
    widths = [_w(lab) for lab, _ in items]
    lx = 0.985 - sum(widths)
    for (lab, col), w in zip(items, widths):
        fig.text(lx, 0.888, "━", color=col, fontsize=10.0,
                 va="center", ha="left", fontweight="bold")
        fig.text(lx + 0.0205, 0.888, lab, color=INK_2, fontsize=7.8,
                 va="center", ha="left")
        lx += w

    foot = "LAZY ALPHA SOCIETY"
    if sample:
        foot = "예시 데이터 — 테스트용  ·  " + foot
    fig.text(0.015, 0.022, foot, color=INK_MUTED, fontsize=6.8, va="center")
    if sig.get("asof"):
        fig.text(0.985, 0.022, str(sig["asof"]), color=INK_MUTED,
                 fontsize=6.8, va="center", ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ── 예시 데이터로 한 장 뽑아 보기 ────────────────────────────────
def _sample(nbars=380, seed=11):
    """VCP 한 판 — 상승 → 수축(베이스) → 마지막 몇 봉에서 돌파."""
    import random
    from datetime import date as _D, timedelta as _T
    day0 = _D(2026, 9, 29) - _T(days=nbars - 1)
    rnd = random.Random(seed)
    px, out = 17500.0, []
    rise = int(nbars * 0.42)
    brk = nbars - 3
    base_mid = None
    for i in range(nbars):
        if i < rise:
            drift, vola = 0.0042, 0.018               # 1차 상승
        elif i < brk:
            t = (i - rise) / float(max(brk - rise, 1))
            drift, vola = 0.0, 0.017 - 0.012 * t      # 수축
        else:
            drift, vola = 0.036, 0.014                # 돌파
        op = px
        px = op * (1 + rnd.gauss(drift, vola))
        if rise <= i < brk:
            if base_mid is None:
                base_mid = op * 0.985
            px += (base_mid - px) * 0.14              # 평균회귀
        hi = max(op, px) * (1 + abs(rnd.gauss(0, vola * 0.45)))
        lw = min(op, px) * (1 - abs(rnd.gauss(0, vola * 0.45)))
        v = 620000 + rnd.randint(-160000, 160000)
        if rise <= i < brk:
            v = int(v * (0.80 - 0.35 * ((i - rise) / float(max(brk - rise, 1)))))
        else:
            v = int(v * (1.0 + 2.6 * max(0, i - brk + 1) / 3.0))
        d = day0 + _T(days=i)
        out.append({"date": d.strftime("%m-%d"), "open": op, "high": hi,
                    "low": lw, "close": px, "volume": max(v, 40000)})
    return out


def _demo(preset, path, seed=11, scale=None, sig=None):
    cs = _sample(seed=seed)
    if scale:
        k = scale / cs[-1]["close"]
        for r in cs:
            for f in ("open", "high", "low", "close"):
                r[f] *= k
    pivot = max(r["high"] for r in cs[-40:-3])
    base = {"name": "한국비엔씨", "ticker": "256840", "market": "KR",
            "signal": "BREAKOUT_ENTRY", "contraction": "VCP",
            "asof": "2026-09-29 15:30 KST"}
    base.update(sig or {})
    base.update({"preset": preset,
                 "trigger_price": round(pivot, 2), "sl": round(pivot * 0.93, 2),
                 "tp1": round(pivot * 1.11, 2), "tp2": round(pivot * 1.22, 2)})
    png = render(base, cs, sample=True)
    open(path, "wb").write(png)
    print(path, len(png), "bytes", ma_lens(base))


if __name__ == "__main__":
    _demo("Fibo", "/home/claude/out/chartcard/sample_fibo.png")
    _demo("Classic", "/home/claude/out/chartcard/sample_classic.png")
    _demo("Fibo", "/home/claude/out/chartcard/sample_us.png", seed=3, scale=182.0,
          sig={"name": "Palantir", "ticker": "PLTR", "market": "US",
               "signal": "\U0001F4A5 정석 진입",
               "asof": "2026-09-29 09:45 ET"})
