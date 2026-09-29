# -*- coding: utf-8 -*-
"""이미지 URL 서명.

디스코드가 이미지를 긁어가려면 URL 이 **공개**여야 한다. 그러니 URL 에 토큰을
박으면 그 토큰이 디스코드 CDN 과 회원 브라우저에 그대로 남는다. 대신 파라미터
전체를 시크릿으로 서명하고 서명만 붙인다 — 남이 임의 종목·임의 가격으로 우리
도메인의 그림을 만들어 낼 수 없다.

라우터 쪽에서도 같은 모듈을 써서 `build()` 로 URL 을 만든다.
"""
import hashlib
import hmac
import os
from urllib.parse import urlencode

SECRET_ENV = "CHART_SECRET"
SIG_KEY = "sg"


def _secret():
    v = os.getenv(SECRET_ENV) or ""
    if not v:
        raise RuntimeError("%s 미설정" % SECRET_ENV)
    return v.encode("utf-8")


def canon(params):
    """서명 대상 문자열. 키 정렬 + 서명 키 제외 — 양쪽이 같아야 한다."""
    items = sorted((str(k), "" if v is None else str(v))
                   for k, v in params.items() if k != SIG_KEY)
    return "&".join("%s=%s" % (k, v) for k, v in items)


def sign(params):
    return hmac.new(_secret(), canon(params).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


def verify(params):
    got = str(params.get(SIG_KEY) or "")
    return bool(got) and hmac.compare_digest(got, sign(params))


def build(base_url, params):
    """`https://chart.../card.png?...&sg=...` 한 줄."""
    p = dict(params)
    p.pop(SIG_KEY, None)
    p[SIG_KEY] = sign(p)
    return "%s?%s" % (base_url.rstrip("?"), urlencode(p))
