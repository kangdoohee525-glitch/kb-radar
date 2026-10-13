# 가격변동 레이더
1. 이 폴더를 GitHub 저장소에 올리고 Settings → Pages → Branch: main / root 로 켭니다.
2. Actions 탭 → weekly-kb-data → Run workflow 로 첫 수집을 실행합니다. (이후 매주 금요일 자동 실행)
3. 실패하면 로그의 `[누락]`/`[오류]` 메시지와 raw-excel 아티팩트를 확인하세요. 수동 변환: `python collect.py --sale a.xlsx --jeonse b.xlsx`
data.json이 없으면 index.html은 샘플 데이터로 동작합니다.
