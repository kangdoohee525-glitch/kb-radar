#!/usr/bin/env python3
"""KB부동산 데이터허브 주간 아파트 매매·전세 가격지수 -> data.json
사용: python collect.py                      (Playwright로 자동 다운로드)
      python collect.py --sale a.xlsx --jeonse b.xlsx   (직접 받은 엑셀로 변환만)"""
import argparse, asyncio, datetime as dtm, json, re, sys, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd

URL = "https://data.kbland.kr/kbstats/wmh"
WEEKS = 364  # 최근 7년
SEOUL = "도봉 노원 은평 강북 성북 중랑 서대문 종로 동대문 성동 광진 마포 중구 용산 강남 송파 강동 강서 양천 영등포 동작 서초 구로 금천 관악".split()
GG = ("연천 파주 양주 동두천 포천 김포 고양 의정부 구리 남양주 가평 부천 광명 과천 하남 양평 시흥 안양 성남 광주 이천 "
      "안산 군포 의왕 수원 용인 여주 화성 오산 안성 평택").split()
METRO = {"서울": (SEOUL, "서울", "부산"), "경기": (GG, "경기", "강원")}
cands = lambda n, m: {n, n + "구"} if m == "서울" else {n, n + "시", n + "군"}
ANCHOR = {c for m, (ns, _, _) in METRO.items() for n in ns for c in cands(n, m)} | {"서울", "경기", "부산"}

def asdate(v):
    return v if isinstance(v, (str, dtm.datetime)) else pd.NaT

def _walk(o):
    yield o
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)

def _dates(lst):
    out = []
    for v in lst:
        s = re.sub(r"\D", "", str(v))[:8]
        if len(s) != 8:
            return None
        try:
            out.append(pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:]}"))
        except Exception:
            return None
    return out

def describe(o, depth=0, key="root"):
    """JSON 구조 요약을 로그(stderr)에 출력 - 구조를 모를 때 원인 파악용"""
    pad = "  " * depth
    if isinstance(o, dict):
        print(f"{pad}{key}: dict({len(o)}) 키={list(o)[:8]}", file=sys.stderr)
        if depth < 4:
            for k, v in list(o.items())[:6]:
                describe(v, depth + 1, k)
    elif isinstance(o, list):
        first = json.dumps(o[0], ensure_ascii=False)[:150] if o else None
        print(f"{pad}{key}: list({len(o)}) 첫 원소={first}", file=sys.stderr)
        if o and depth < 4 and isinstance(o[0], (dict, list)):
            describe(o[0], depth + 1, key + "[0]")
    else:
        print(f"{pad}{key}: {type(o).__name__} {str(o)[:60]}", file=sys.stderr)

def from_json(data):
    """KB 데이터허브 API의 JSON 응답 -> table()과 같은 (헤더, 본문). 날짜 목록 1개 + 지역별 숫자 배열을 자동 탐색."""
    try:  # KB 데이터허브 실제 구조: dataBody.data.{날짜리스트, 데이터리스트[{지역명, dataList[{데이터, 기준날짜}]}]}
        d = data["dataBody"]["data"]
        keys, rows = d["날짜리스트"], d["데이터리스트"]
        if rows and isinstance(rows[0]["dataList"][0], dict):
            dts = _dates(keys)
            names, cols = [], []
            for r in rows:
                m = {str(x.get("기준날짜")): x.get("데이터") for x in r["dataList"]}
                names.append(str(r["지역명"]).strip())
                cols.append([m.get(str(k)) for k in keys])
            body = pd.DataFrame(dict(enumerate(cols)), index=pd.DatetimeIndex(dts)).apply(pd.to_numeric, errors="coerce")
            return names, body.sort_index()
    except (KeyError, TypeError, IndexError, ValueError):
        pass
    dates = None
    for o in _walk(data):
        if isinstance(o, list) and len(o) >= 30 and all(isinstance(x, (str, int)) for x in o):
            d = _dates(o)
            if d:
                dates = d
                break
    names, cols = [], []
    num = lambda x: x is None or isinstance(x, (int, float)) or re.fullmatch(r"-?\d+(\.\d+)?", str(x))
    for o in _walk(data) if dates else []:
        if not isinstance(o, dict):
            continue
        nm = next((o[k] for k in o if isinstance(o[k], str) and ("지역명" in k or k in ("name", "regionName"))), None) \
            or next((v for v in o.values() if isinstance(v, str) and v.strip() in ANCHOR), None)
        for v in o.values():
            if nm and isinstance(v, list) and len(v) == len(dates) and any(x is not None for x in v) and all(num(x) for x in v):
                vals = pd.to_numeric(pd.Series(v), errors="coerce")
                if vals.median() > 20:  # 증감률(0 근처)이 아니라 지수(수십~백수십)만
                    names.append(nm.strip())
                    cols.append(vals.tolist())
                    break
    if not dates or len(names) < 5:
        describe(data)
        raise ValueError("JSON에서 날짜/지역별 지수 배열을 찾지 못했습니다. 위 구조 요약을 확인하세요.")
    body = pd.DataFrame(dict(enumerate(cols)), index=pd.DatetimeIndex(dates))
    return names, body.sort_index()

def table(path):
    """엑셀 또는 JSON -> (헤더 리스트, 날짜 인덱스 본문). 엑셀은 지역이 가로/세로 어느 쪽이든 자동 판별."""
    if str(path).endswith(".json"):
        return from_json(json.loads(Path(path).read_text(encoding="utf-8")))
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

API = "https://data-api.kbland.kr/bfmstat/weekMnthlyHuseTrnd/priceIndexOnlyWeekAptExcel"
HDR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
       "Referer": "https://data.kbland.kr/", "Origin": "https://data.kbland.kr", "Accept": "*/*"}

def fetch_best(code, key, dest=Path("raw")):
    """KB 데이터허브가 쓰는 엑셀 API를 직접 호출. 기간(년)을 크게 줄여가며 가장 긴 파일을 고른다.
    code: 01=매매, 02=전세 (화면 통신 기록에서 확인한 값)"""
    dest.mkdir(exist_ok=True)
    best = None
    for yrs in (10, 7, 5, 3, 2):
        p = dest / f"{key}_{yrs}y.xlsx"
        try:
            q = urllib.parse.urlencode({"매매전세코드": code, "기간": yrs, "매물종별구분": "01"})
            with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=HDR), timeout=90) as r:
                data = r.read()
            if data[:2] != b"PK":  # 엑셀이 아니면 JSON 응답(화면이 이 JSON으로 엑셀을 만든다)
                p = p.with_suffix(".json")
            p.write_bytes(data)
            n = len(table(p)[1])
        except (Exception, SystemExit) as ex:
            print(f"[정보] {key} 기간={yrs}년: 실패 ({type(ex).__name__}: {str(ex)[:150]})", file=sys.stderr)
            continue
        print(f"[정보] {key} 기간={yrs}년: {n}주치", file=sys.stderr)
        if not best or n > best[0]:
            best = (n, p)
        if n >= WEEKS + 1:
            break
    if not best:
        raise RuntimeError(f"{key}: 모든 기간 요청이 실패했습니다.")
    final = dest / f"{key}{best[1].suffix}"
    final.write_bytes(best[1].read_bytes())
    return final

def get_files():
    try:
        return fetch_best("01", "sale"), fetch_best("02", "jeonse")
    except Exception as ex:
        print(f"[경고] KB API 직접 호출 실패 -> 브라우저 방식으로 전환: {ex}", file=sys.stderr)
        return asyncio.run(download())

async def download(dest=Path("raw")):
    """KB 데이터허브 화면에서 '엑셀 저장' 버튼으로 매매/전세 지수 파일을 받는다.
    실패하면 raw/ 폴더에 화면 캡처(debug.png), 화면 글자(page.txt), 통신 목록(calls.txt)을 남긴다."""
    from playwright.async_api import async_playwright
    dest.mkdir(exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(accept_downloads=True, locale="ko-KR", viewport={"width": 1280, "height": 900})
        pg = await ctx.new_page()
        calls = []
        pg.on("response", lambda r: calls.append(f"{r.status} {r.request.method} {r.url}")
              if r.request.resource_type in ("xhr", "fetch", "document") else None)
        got = {}
        try:
            await pg.goto(URL, wait_until="networkidle", timeout=60000)
            await pg.wait_for_timeout(3000)
            for key, menu in (("sale", None), ("jeonse", r"text=/전세\s*가격지수/ >> visible=true")):
                if menu:
                    await pg.locator(menu).first.click(timeout=15000)
                    await pg.wait_for_load_state("networkidle")
                    await pg.wait_for_timeout(2000)
                async with pg.expect_download(timeout=30000) as d:
                    # '엑셀 저장'은 접힌 메뉴(li.excel) 안에 숨어 있어 일반 클릭이 안 되므로 스크립트로 직접 누른다
                    print(f"[정보] {key}: li.excel {await pg.locator('li.excel').count()}개 발견", file=sys.stderr)
                    await pg.locator("li.excel").first.evaluate("el => el.click()")
                got[key] = dest / f"{key}.xlsx"
                await (await d.value).save_as(got[key])
        except Exception as ex:
            text = ""
            try:
                await pg.screenshot(path=str(dest / "debug.png"), full_page=True)
                text = await pg.inner_text("body")
                (dest / "page.txt").write_text(text, encoding="utf-8")
            except Exception:
                pass
            (dest / "calls.txt").write_text("\n".join(calls), encoding="utf-8")
            print(f"[오류] 엑셀 다운로드 단계 실패 ({'/'.join(got) or '매매 지수'} 단계): {type(ex).__name__}: {str(ex)[:400]}", file=sys.stderr)
            print("[참고] 화면에 보인 글자:", text[:300].replace("\n", " | "), file=sys.stderr)
            await b.close()
            sys.exit(1)
        (dest / "calls.txt").write_text("\n".join(calls), encoding="utf-8")
        await b.close()
    return got["sale"], got["jeonse"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sale"); ap.add_argument("--jeonse")
    a = ap.parse_args()
    sale, jeonse = (a.sale, a.jeonse) if a.sale and a.jeonse else get_files()
    Path("data.json").write_text(json.dumps(build(sale, jeonse), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("data.json 갱신 완료")
