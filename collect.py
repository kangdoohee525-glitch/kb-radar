#!/usr/bin/env python3
"""KB부동산 데이터허브 주간 아파트 매매·전세 가격지수 -> data.json
사용: python collect.py                      (Playwright로 자동 다운로드)
      python collect.py --sale a.xlsx --jeonse b.xlsx   (직접 받은 엑셀로 변환만)"""
import argparse, asyncio, datetime as dtm, json, re, sys
from pathlib import Path
import pandas as pd

URL = "https://data.kbland.kr/kbstats/wmh"
WEEKS = 156
SEOUL = "도봉 노원 은평 강북 성북 중랑 서대문 종로 동대문 성동 광진 마포 중구 용산 강남 송파 강동 강서 양천 영등포 동작 서초 구로 금천 관악".split()
GG = ("연천 파주 양주 동두천 포천 김포 고양 의정부 구리 남양주 가평 부천 광명 과천 하남 양평 시흥 안양 성남 광주 이천 "
      "안산 군포 의왕 수원 용인 여주 화성 오산 안성 평택").split()
METRO = {"서울": (SEOUL, "서울", "부산"), "경기": (GG, "경기", "강원")}
cands = lambda n, m: {n, n + "구"} if m == "서울" else {n, n + "시", n + "군"}
ANCHOR = {c for m, (ns, _, _) in METRO.items() for n in ns for c in cands(n, m)} | {"서울", "경기", "부산"}

def asdate(v):
    return v if isinstance(v, (str, dtm.datetime)) else pd.NaT

def table(path):
    """엑셀 -> (헤더 리스트, 날짜 인덱스 본문). 지역이 가로/세로 어느 쪽이든 자동 판별."""
    best = None
    for df in pd.read_excel(path, header=None, sheet_name=None).values():
        for d in (df, df.T):
            for i in range(min(len(d), 40)):
                hit = sum(str(v).strip() in ANCHOR for v in d.iloc[i])
                if not best or hit > best[0]:
                    best = (hit, d, i)
    hit, d, i = best
    if hit < 5:
        sys.exit(f"[오류] {path}: 지역명 헤더를 찾지 못했습니다. 엑셀 구조를 확인하세요.")
    head = [str(v).strip() for v in d.iloc[i]]
    body = d.iloc[i + 1:].copy()
    body.columns = range(len(head))
    dates = {j: pd.to_datetime(body[j].map(asdate), errors="coerce") for j in range(len(head))}
    dcol = max(dates, key=lambda j: dates[j].notna().sum())
    body.index = dates[dcol]
    return head, body[body.index.notna()].sort_index()

def pick(head, body, m):
    names, a, b = METRO[m]
    s = next((j for j, h in enumerate(head) if h.startswith(a)), 0)
    e = next((j for j, h in enumerate(head) if j > s and h.startswith(b)), len(head))
    out, miss = {}, []
    for n in names:
        js = [j for j in range(s, e) if head[j] in cands(n, m)]
        if js:
            out[n] = pd.to_numeric(body[js[0]], errors="coerce")
        else:
            miss.append(n)
    return out, miss, head[s:e]

def build(sale, jeonse):
    tabs = [table(sale), table(jeonse)]
    common = tabs[0][1].index.intersection(tabs[1][1].index)[-(WEEKS + 1):]
    if len(common) < 60:
        sys.exit(f"[오류] 매매·전세 공통 주차가 {len(common)}개뿐입니다.")
    res, bad = {}, False
    for m in METRO:
        res[m] = {}
        for k, (head, body) in enumerate(tabs):
            cols, miss, seg = pick(head, body, m)
            if miss:
                bad = True
                print(f"[누락] {m} {'전세' if k else '매매'}: {miss}\n  헤더 후보: {seg}", file=sys.stderr)
            res[m][str(k)] = {}
            for n, s in cols.items():
                s = s.reindex(common).ffill().bfill()
                if s.isna().any():
                    sys.exit(f"[오류] {m} {n}: 숫자 값을 읽지 못했습니다.")
                res[m][str(k)][n] = [round(float(v), 3) for v in s]
    if bad:
        sys.exit(1)
    return {"updated": dtm.date.today().isoformat(), "end": common[-1].strftime("%Y-%m-%d"),
            "weeks": len(common) - 1, "series": res}

async def download(dest=Path("raw")):
    """KB 데이터허브 화면에서 '엑셀 저장' 버튼으로 매매/전세 지수 파일을 받는다. (화면 개편 시 선택자 수정 필요)"""
    from playwright.async_api import async_playwright
    dest.mkdir(exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await (await b.new_context(accept_downloads=True, locale="ko-KR")).new_page()
        await pg.goto(URL, wait_until="networkidle")
        got = {}
        for key, menu in (("sale", None), ("jeonse", re.compile(r"전세\s*가격지수"))):
            if menu:
                await pg.get_by_text(menu).first.click()
                await pg.wait_for_load_state("networkidle")
            async with pg.expect_download(timeout=60000) as d:
                await pg.get_by_text("엑셀 저장").first.click()
            got[key] = dest / f"{key}.xlsx"
            await (await d.value).save_as(got[key])
        await b.close()
    return got["sale"], got["jeonse"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sale"); ap.add_argument("--jeonse")
    a = ap.parse_args()
    sale, jeonse = (a.sale, a.jeonse) if a.sale and a.jeonse else asyncio.run(download())
    Path("data.json").write_text(json.dumps(build(sale, jeonse), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("data.json 갱신 완료")
