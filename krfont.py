# -*- coding: utf-8 -*-
"""한글 폰트 확보 — **없으면 한글이 통째로 네모로 나간다.**

Railway/nixpacks 이미지에는 CJK 폰트가 없다. `nixpacks.toml` 의 `aptPkgs` 로
`fonts-noto-cjk` 를 넣어 두었지만, 그 설정이 빌더 버전에 따라 먹지 않는 일이
있다. **설정 하나에 카드 품질을 걸지 않는다** — 부팅 때 직접 확인하고,
없으면 내려받아 등록한다. 둘 다 실패하면 `/health` 가 그렇게 말한다.
"""
import os
import threading

from matplotlib import font_manager

CACHE_DIR = os.getenv("FONT_CACHE_DIR", "/tmp/fonts")
#  Google Fonts 공개 저장소의 Noto Sans KR (OFL). 고정 태그가 아니라 main 이라
#  파일이 옮겨질 수 있으므로 후보를 여러 개 둔다.
FONT_URLS = [
    "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf",
    "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansKR/NotoSansKR-Regular.ttf",
]
PREFERRED = ("Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans KR",
             "NanumGothic", "NanumBarunGothic", "Malgun Gothic", "AppleGothic")

_STATE = {"family": None, "source": None, "error": None, "tried": False}
_LOCK = threading.Lock()


def _scan():
    """이미 설치된 것 중 한글이 되는 패밀리.

    Noto Sans CJK 는 TTC 한 덩어리라 matplotlib 이 JP 이름 하나로 등록하는데,
    그 안에 한글 글리프가 다 들어 있다. 이름만 보고 KR 을 찾으면 못 찾는다.
    """
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in PREFERRED:
        if name in have:
            return name
    for name in sorted(have):
        if "CJK" in name and "Serif" not in name:
            return name
    return None


def _download():
    import urllib.request
    os.makedirs(CACHE_DIR, exist_ok=True)
    dst = os.path.join(CACHE_DIR, "NotoSansKR.ttf")
    if not os.path.exists(dst) or os.path.getsize(dst) < 200000:
        last = None
        for url in FONT_URLS:
            try:
                urllib.request.urlretrieve(url, dst)
                if os.path.getsize(dst) >= 200000:
                    break
            except Exception as e:                      # noqa: BLE001
                last = e
        else:
            raise last or RuntimeError("font download failed")
    font_manager.fontManager.addfont(dst)
    return font_manager.FontProperties(fname=dst).get_name()


def ensure(force=False):
    """쓸 수 있는 폰트 패밀리 이름. 못 구하면 None (그래도 그림은 그린다)."""
    with _LOCK:
        if _STATE["family"] and not force:
            return _STATE["family"]
        _STATE["tried"] = True
        fam = _scan()
        if fam:
            _STATE.update(family=fam, source="system", error=None)
            return fam
        try:
            fam = _download()
            _STATE.update(family=fam, source="download", error=None)
            return fam
        except Exception as e:                          # noqa: BLE001
            _STATE.update(family=None, source=None, error="%s" % e)
            return None


def status():
    return dict(_STATE)
