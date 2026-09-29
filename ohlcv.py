# -*- coding: utf-8 -*-
"""캔들 조달.

  국장 — supply-bot 의 `/ohlcv` (이미 KIS 토큰을 물고 있는 쪽이 한투를 부른다.
         여기서 KIS 를 또 붙이면 토큰 발급이 두 군데가 되고, 한투는 토큰 발급
         횟수를 센다.)
  미장 — FMP `historical-price-full`

**320봉이 필요하다.** 표시 120봉 + 200선 계산 200봉. 모자라면 장기선 앞쪽이
끊긴 채 그려진다 — 죽지는 않지만 그림이 어색하다.
"""
import os

import requests

NEED_BARS = 330                    # 320 + 여유
TIMEOUT = 12


def _base(v):
    """스킴 없이 넣어도 되게 한다.

    Railway 대시보드에서 주소를 복사하면 `https://` 가 안 딸려온다. 그대로
    환경변수에 넣으면 requests 가 MissingSchema 로 터지고, **카드에서는
    그림만 조용히 빠져** 어디가 틀렸는지 알 길이 없다. 여기서 붙여 준다.
    """
    v = (v or "").strip().rstrip("/")
    if v and not v.startswith(("http://", "https://")):
        v = "https://" + v
    return v


SUPPLY_BASE = _base(os.getenv("SUPPLY_BASE"))
SUPPLY_TOKEN = (os.getenv("SUPPLY_TOKEN") or "").strip()
FMP_KEY = (os.getenv("FMP_API_KEY") or os.getenv("FMP_KEY") or "").strip()


class NoData(Exception):
    pass


def _rows_kr(ticker, bars):
    if not SUPPLY_BASE:
        raise NoData("SUPPLY_BASE 미설정")
    r = requests.get("%s/ohlcv" % SUPPLY_BASE, timeout=TIMEOUT,
                     params={"ticker": ticker, "bars": bars,
                             "token": SUPPLY_TOKEN})
    r.raise_for_status()
    js = r.json() or {}
    rows = js.get("rows") or js.get("candles") or []
    if not rows:
        raise NoData("supply-bot 응답에 캔들 없음 (%s)" % ticker)
    return rows


def _rows_us(ticker, bars):
    if not FMP_KEY:
        raise NoData("FMP_API_KEY 미설정")
    r = requests.get(
        "https://financialmodelingprep.com/api/v3/historical-price-full/%s" % ticker,
        params={"apikey": FMP_KEY, "timeseries": bars}, timeout=TIMEOUT)
    r.raise_for_status()
    hist = (r.json() or {}).get("historical") or []
    if not hist:
        raise NoData("FMP 응답에 캔들 없음 (%s)" % ticker)
    out = []
    for d in reversed(hist):                    # FMP 는 최신 → 과거 순
        out.append({"date": d.get("date", ""), "open": d.get("open"),
                    "high": d.get("high"), "low": d.get("low"),
                    "close": d.get("close"), "volume": d.get("volume") or 0})
    return out


def _clean(rows):
    """None·0 이 섞인 봉을 걷어낸다. 하나라도 섞이면 선 계산이 통째로 망가진다."""
    out = []
    for d in rows:
        try:
            o, h, lo, c = (float(d["open"]), float(d["high"]),
                           float(d["low"]), float(d["close"]))
        except (TypeError, ValueError, KeyError):
            continue
        if min(o, h, lo, c) <= 0:
            continue
        out.append({"date": str(d.get("date") or "")[-5:] if len(
            str(d.get("date") or "")) >= 5 else str(d.get("date") or ""),
            "open": o, "high": h, "low": lo, "close": c,
            "volume": float(d.get("volume") or 0)})
    return out


def fetch(ticker, market="KR", bars=NEED_BARS):
    rows = (_rows_kr(ticker, bars) if str(market).upper().startswith("K")
            else _rows_us(ticker, bars))
    rows = _clean(rows)
    if len(rows) < 30:
        raise NoData("쓸 만한 봉이 %d개뿐 (%s)" % (len(rows), ticker))
    return rows


def status():
    return {"supply_base": bool(SUPPLY_BASE), "supply_token": bool(SUPPLY_TOKEN),
            "fmp_key": bool(FMP_KEY), "need_bars": NEED_BARS}
