# chart-render

시그널 카드에 붙일 **차트 PNG 한 장**만 서빙하는 작은 서비스.

## 왜 따로 서 있나

`watchlist-router` 는 운영 중이다. 거기에 matplotlib 과 CJK 폰트를 얹으면 빌드가
무거워지고, 한 번 깨질 때 시그널 카드 전체가 멈춘다. 여기가 죽어도 카드는 그대로
나간다 — 그림만 빠진다. 나중에 A안(chart-img)으로 갈아타도 라우터는 손댈 게 없다.

## 라우터가 할 일

임베드에 한 줄 더하는 것뿐이다.

```python
from sign import build
embed["image"] = {"url": build(CHART_BASE + "/card.png", {
    "t": ticker, "m": market, "nm": name, "p": preset,
    "sig": sig_type, "ctr": contraction,
    "b": trigger_price, "s": sl, "t1": tp1, "t2": tp2,
    "d": bar_date,          # 봉 날짜 — 캐시 키
})}
```

청산 카드처럼 선 이름이 다른 경우는 `bl`·`sl_`·`t1l`·`t2l` 로 라벨을 넘긴다.

## 환경변수

| 이름 | 쓰임 |
|---|---|
| `CHART_SECRET` | 이미지 URL 서명(HMAC). 라우터와 **같은 값** |
| `CHART_BASE` | 이 서비스의 공개 주소 |
| `SUPPLY_BASE` / `SUPPLY_TOKEN` | 국장 캔들 — supply-bot `/ohlcv` |
| `FMP_API_KEY` | 미장 캔들 |
| `ADMIN_TOKEN` | `/test/send` 보호 |
| `CHART_TEST_WEBHOOK` | 테스트 채널 웹훅 (테스트 전용) |

## 라우트

- `GET /card.png` — 서명된 파라미터로 PNG. 실패하면 **404** (500 아님) — 그림 하나
  때문에 카드를 막지 않는다. 디스코드는 이미지 자리를 그냥 비운다.
- `GET /health` — 폰트·소스·캐시 상태
- `GET /test/send?k=ADMIN_TOKEN` — 테스트 채널로 카드 한 장

## 데이터 요구 — 320봉

200선을 표시 구간(마지막 120봉) 전체에 그리려면 캔들이 **320봉 이상**이어야 한다.
모자라면 장기선 앞쪽이 끊긴 채 그려진다.

## 한글

CJK 폰트가 없으면 한글이 통째로 네모로 나간다. `nixpacks.toml` 의 `aptPkgs` 에
`fonts-noto-cjk` 를 넣어 두었고, 그 설정이 안 먹는 경우를 대비해 `krfont.py` 가
부팅 때 한 번 더 확인하고 없으면 내려받는다. `/health` 가 어느 쪽인지 말해 준다.
