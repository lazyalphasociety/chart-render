# -*- coding: utf-8 -*-
"""chart-render — 시그널 카드에 붙일 차트 PNG 한 장만 서빙한다.

**왜 따로 서 있나**
watchlist-router 는 운영 중이다. 거기에 matplotlib 과 CJK 폰트를 얹으면 빌드가
무거워지고, 한 번 깨질 때 시그널 카드 전체가 멈춘다. 여기가 죽어도 카드는
그대로 나간다 — 그림만 빠진다. 나중에 A안(chart-img)으로 갈아타도 라우터는
손댈 게 없다. 이 서비스 안쪽만 바꾸면 된다.

**라우터가 할 일**은 임베드에 한 줄 더하는 것뿐이다.

    from sign import build
    embed["image"] = {"url": build(CHART_BASE + "/card.png", {
        "t": ticker, "m": market, "nm": name, "p": preset,
        "sig": sig_type, "ctr": contraction,
        "b": trigger_price, "s": sl, "t1": tp1, "t2": tp2,
        "d": bar_date,                 # 봉 날짜 — 캐시 키이자 디스코드 캐시 무력화
    })}

라벨을 바꿔야 하는 카드(청산 등)는 `bl`·`sl_` 로 넘긴다.
"""
import io
import os
import re
import threading
import time
import traceback

from flask import Flask, jsonify, request, send_file

import chart_card
import krfont
import ohlcv
from sign import SIG_KEY, verify

app = Flask(__name__)

ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or "").strip()
FMP_ENV = (os.getenv("FMP_API_KEY") or os.getenv("FMP_KEY") or "").strip()
SUPPLY_TOK_ENV = (os.getenv("SUPPLY_TOKEN") or "").strip()
TEST_WEBHOOK = (os.getenv("CHART_TEST_WEBHOOK") or "").strip()
CACHE_SEC = int(os.getenv("CHART_CACHE_SEC", "900"))
CACHE_MAX = 200

_CACHE = {}                 # key -> (ts, png)
_LOCK = threading.Lock()
_STATS = {"hit": 0, "miss": 0, "error": 0, "last_error": None}


def _cache_get(key):
    with _LOCK:
        got = _CACHE.get(key)
        if got and time.time() - got[0] < CACHE_SEC:
            _STATS["hit"] += 1
            return got[1]
    return None


def _cache_put(key, png):
    with _LOCK:
        if len(_CACHE) >= CACHE_MAX:            # 오래된 것부터 버린다
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:CACHE_MAX // 4]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time(), png)


def _scrub(msg):
    """에러 문자열에서 비밀을 지운다.

    /health 는 인증이 없다. 그런데 requests 의 예외 메시지에는 **요청 URL 이
    통째로** 들어 있고 거기엔 apikey 가 붙어 있다. 실제로 FMP 키가 이 경로로
    새어 나갔다(2026-09-29). 소스에서 안 싣는 게 1차 방어고, 이건 2차다.
    """
    s = str(msg)
    for v in (FMP_ENV, SUPPLY_TOK_ENV, ADMIN_TOKEN,
              os.getenv("CHART_SECRET") or ""):
        if v and len(v) >= 8:
            s = s.replace(v, "<가림>")
    s = re.sub(r"(?i)(apikey|api_key|token|secret|key)=[^&\s\"\']+",
               r"\1=<가림>", s)
    return s[:400]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _levels(q):
    """카드 종류마다 같은 자리의 선을 다르게 부른다 — 라벨을 쿼리로 받는다."""
    out = []
    for val, label, kind in ((q.get("b"), q.get("bl") or "진입", "base"),
                             (q.get("s"), q.get("sl_") or "손절", "stop"),
                             (q.get("t1"), q.get("t1l") or "목표1", "target"),
                             (q.get("t2"), q.get("t2l") or "목표2", "far")):
        f = _f(val)
        if f:
            out.append((label, f, kind))
    return out


def _render(q, candles):
    sig = {
        "name": q.get("nm") or q.get("t") or "",
        "ticker": q.get("t") or "",
        "market": q.get("m") or "KR",
        "preset": q.get("p") or "",
        "signal": q.get("sig") or "",
        "contraction": q.get("ctr") or "",
        "asof": q.get("as") or "",
        "levels": _levels(q),
    }
    return chart_card.render(sig, candles, sample=(q.get("demo") == "1"))


@app.route("/card.png")
def card():
    q = {k: v for k, v in request.args.items()}
    if not verify(q):
        return jsonify({"error": "bad signature"}), 403
    key = "|".join("%s=%s" % (k, q[k]) for k in sorted(q) if k != SIG_KEY)
    png = _cache_get(key)
    if png is None:
        _STATS["miss"] += 1
        try:
            if q.get("demo") == "1":
                candles = chart_card._sample(nbars=380)
            else:
                candles = ohlcv.fetch(q.get("t", ""), q.get("m", "KR"))
            png = _render(q, candles)
        except Exception as e:                          # noqa: BLE001
            _STATS["error"] += 1
            _STATS["last_error"] = _scrub("%s: %s" % (type(e).__name__, e))
            traceback.print_exc()
            #  **그림 하나 때문에 카드를 막지 않는다.** 404 면 디스코드가 이미지
            #  자리를 그냥 비운다 — 카드 본문은 그대로 나간다.
            return jsonify({"error": _scrub(e)}), 404
        _cache_put(key, png)
    resp = send_file(io.BytesIO(png), mimetype="image/png",
                     download_name="%s.png" % (q.get("t") or "chart"))
    resp.headers["Cache-Control"] = "public, max-age=%d" % CACHE_SEC
    return resp


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "font": krfont.status(),
        "sources": ohlcv.status(),
        "cache": {"n": len(_CACHE), **_STATS},
        "secret": bool(os.getenv("CHART_SECRET")),
        "test_webhook": bool(TEST_WEBHOOK),
        #  값을 절대 안 내보낸다. **있나 없나와 길이만** — 그것만으로
        #  "안 넣었다" 와 "잘못 넣었다" 가 갈린다.
        "admin_token": {"set": bool(ADMIN_TOKEN), "len": len(ADMIN_TOKEN)},
        "chart_base": os.getenv("CHART_BASE", "") or None,
    })


@app.route("/test/send")
def test_send():
    """테스트 채널로 카드 한 장. 브라우저에서 한 번 열면 된다.

    `?t=005930&m=KR` 로 실제 종목, 아무것도 안 주면 예시 데이터.
    웹훅 주소는 **환경변수에서만** 읽는다 — 주고받지 않는다.
    """
    if not ADMIN_TOKEN or (request.args.get("k") or "").strip() != ADMIN_TOKEN:
        return jsonify({"error": "unauthorized"}), 401
    if not TEST_WEBHOOK:
        return jsonify({"error": "CHART_TEST_WEBHOOK 미설정"}), 400

    import requests as rq
    from sign import build

    demo = not request.args.get("t")
    q = {
        "t": request.args.get("t") or "256840",
        "m": request.args.get("m") or "KR",
        "nm": request.args.get("nm") or ("한국비엔씨" if demo else ""),
        "p": request.args.get("p") or "Fibo",
        "sig": request.args.get("sig") or "BREAKOUT_ENTRY",
        "ctr": request.args.get("ctr") or "VCP",
        "d": time.strftime("%Y%m%d%H%M"),
    }
    if demo:
        q["demo"] = "1"
    for k in ("b", "s", "t1", "t2", "bl", "sl_", "t1l", "t2l", "as"):
        if request.args.get(k):
            q[k] = request.args[k]
    if demo and "b" not in q:                    # 예시 데이터에 맞춘 예시 레벨
        q.update({"b": "26677", "s": "24810", "t1": "29612", "t2": "32546"})

    base = (os.getenv("CHART_BASE") or request.url_root.rstrip("/")) + "/card.png"
    url = build(base, q)

    title = chart_card.signal_ko(q["sig"])
    embed = {
        "title": "%s  %s" % (q["nm"] or q["t"], q["t"]),
        "description": "**%s**%s" % (
            title, "  ·  예시 데이터(테스트용)" if demo else ""),
        "color": 0x3CF281,
        "image": {"url": url},
        "footer": {"text": "차트 렌더 테스트 · LAZY ALPHA SOCIETY"},
    }
    r = rq.post(TEST_WEBHOOK, json={"embeds": [embed]}, timeout=12)
    #  웹훅 주소는 응답에 **절대 싣지 않는다.**
    return jsonify({"sent": r.status_code in (200, 204),
                    "status": r.status_code, "demo": demo,
                    "image_len": len(url)})


#  부팅 때 폰트를 확보해 둔다 — 첫 요청이 느려지는 것도, 두부가 나가는 것도 막는다.
krfont.ensure()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
