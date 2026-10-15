#!/usr/bin/env python3
"""국토교통부 아파트 매매 실거래가(상세) -> complexes.json (남양주 별내동)
좌표는 API에 없어서 complexes_geo.csv(위도·경도 직접 입력)에서 읽는다. 처음 실행하면 단지 목록 골격 CSV를 만들어 준다."""
import csv, datetime as dtm, json, os, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
LAWD = "41360"            # 남양주시 (법정동코드 앞 5자리)
DONGS = {"별내동"}         # 포함할 법정동. 다산동·퇴계원읍 등을 넣으려면 여기에 추가
MONTHS = 15               # 최근 15개월 거래
STATIONS = ["별내역", "별내별가람역", "퇴계원역", "갈매역", "다산역"]
GEO = Path("complexes_geo.csv")
COLS = ["코드", "이름", "종류", "위도", "경도", "세대수", "지도링크"]

def months(n):
    t, out = dtm.date.today().replace(day=1), []
    for _ in range(n):
        out.append(t.strftime("%Y%m"))
        t = (t - dtm.timedelta(days=1)).replace(day=1)
    return out

def call(key, ymd):
    rows, page = [], 1
    while True:
        q = urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": LAWD, "DEAL_YMD": ymd, "pageNo": page, "numOfRows": 1000})
        with urllib.request.urlopen(f"{URL}?{q}", timeout=60) as r:
            root = ET.fromstring(r.read())
        code = (root.findtext(".//resultCode") or "").strip()
        if code not in ("00", "000"):
            sys.exit(f"[오류] 실거래가 API 응답({ymd}): {ET.tostring(root, encoding='unicode')[:300]}\n"
                     "  -> 인증키(DATA_GO_KR_KEY) 등록과 활용신청 승인을 확인하세요. 승인 직후엔 활성화에 시간이 걸릴 수 있어요.")
        rows += [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        if page * 1000 >= int(root.findtext(".//totalCount") or 0):
            return rows
        page += 1

def link(q):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(q)

def collect(key):
    cx = {}
    for ymd in months(MONTHS):
        for r in call(key, ymd):
            if r.get("umdNm") not in DONGS or r.get("cdealType") or r.get("cdealDay"):  # 해제(취소) 건 제외
                continue
            try:
                p = int(r["dealAmount"].replace(",", "")) / 10000
                t = [f"{int(r['dealYear']):04d}-{int(r['dealMonth']):02d}-{int(r['dealDay']):02d}",
                     round(float(r["excluUseAr"]), 2), round(p, 2), int(r.get("floor") or 0)]
            except (KeyError, ValueError):
                continue
            code = r.get("aptSeq") or f"{r.get('aptNm')}_{r.get('jibun')}"
            c = cx.setdefault(code, {"n": r.get("aptNm", code), "y": int(r.get("buildYear") or 0) or None, "t": []})
            c["t"].append(t)
    return cx

def main():
    key = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())
    if not key:
        sys.exit("[오류] DATA_GO_KR_KEY 가 없습니다. GitHub Settings > Secrets 등록을 확인하세요.")
    cx = collect(key)
    print(f"[정보] {'/'.join(sorted(DONGS))} 단지 {len(cx)}곳, 거래 {sum(len(c['t']) for c in cx.values())}건 (최근 {MONTHS}개월)")
    geo = {}
    if GEO.exists():
        with open(GEO, encoding="utf-8-sig", newline="") as f:
            geo = {r["코드"]: r for r in csv.DictReader(f)}
    for code, c in cx.items():
        geo.setdefault(code, dict(zip(COLS, [code, c["n"], "단지", "", "", "", link(f"남양주 별내동 {c['n']}")])))
    for s in STATIONS:
        geo.setdefault("역:" + s, dict(zip(COLS, ["역:" + s, s, "역", "", "", "", link(s)])))
    with open(GEO, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(geo.values())

    def ll(row):
        try:
            la, ln = float(row["위도"]), float(row["경도"])
        except (TypeError, ValueError):
            return None
        if not (37 < la < 38.5 and 126.5 < ln < 128):
            print(f"[경고] {row['이름']}: 좌표({la}, {ln})가 남양주 범위를 벗어났어요. 위도·경도 순서를 확인하세요.")
            return None
        return la, ln

    out, miss = [], []
    for code, c in cx.items():
        pos = ll(geo[code])
        if not pos:
            miss.append(c["n"])
            continue
        d = {"n": c["n"], "lat": pos[0], "lng": pos[1], "t": sorted(c["t"])}
        if c["y"]:
            d["y"] = c["y"]
        try:
            d["h"] = int(geo[code].get("세대수") or 0) or None
        except ValueError:
            d["h"] = None
        out.append({k: v for k, v in d.items() if v is not None})
    lm = [{"n": r["이름"], "lat": p[0], "lng": p[1]} for r in geo.values() if r["종류"] == "역" and (p := ll(r))]
    print(f"[정보] 좌표가 있는 단지 {len(out)}곳 / 없는 단지 {len(miss)}곳 {miss[:8]}{'...' if len(miss) > 8 else ''}")
    if len(out) < 3:
        print("[안내] complexes_geo.csv 의 위도·경도 칸을 채운 뒤 다시 실행하면 complexes.json 이 만들어집니다. (최소 3곳)")
        return
    today = dtm.date.today().isoformat()
    Path("complexes.json").write_text(json.dumps({"updated": today, "asof": today, "landmarks": lm, "complexes": out},
                                                 ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("complexes.json 갱신 완료")

if __name__ == "__main__":
    main()
