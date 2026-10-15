name: collect-apts
on:
  schedule:
    - cron: "0 0 * * 6"   # 매주 토요일 09:00 KST
  workflow_dispatch:
permissions:
  contents: write
jobs:
  apts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: python collect_apts.py
        env:
          DATA_GO_KR_KEY: ${{ secrets.DATA_GO_KR_KEY }}
      - run: |
          git config user.name "kb-bot" && git config user.email "bot@users.noreply.github.com"
          git add complexes_geo.csv
          [ -f complexes.json ] && git add complexes.json || true
          git diff --staged --quiet || (git commit -m "data: weekly apartment trades" && git push)
