# Cycle Intelligence Hub

> 🏛️ **여러 시장 사이클 인텔리전스 시스템을 한 화면에서 통합 관제**

각 자산군의 사이클 점수를 한눈에 비교하고, 자산 배분 의사결정에 필요한 cross-system insight를 자동 추출하여 텔레그램으로 정기 보고합니다.

## 🎯 핵심 특징

- 📋 **Registry-driven**: `registry.yaml`에 시스템 한 줄 추가만 하면 자동 통합
- 🔗 **No coupling**: 하위 시스템이 Hub의 존재를 알 필요 없음 (자기 데이터만 publish)
- 🌐 **완전 서버리스**: GitHub Actions + Pages, 월 0원
- 🎯 **Cross-system insights**: 자동으로 divergence, synchronized euphoria 등 포착
- 📲 **통합 텔레그램 리포트**: 모든 시스템을 한 번에 요약
- 🛡️ **Resilient**: 한 시스템이 죽어도 나머지는 정상 표시

## 🏗️ 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│        Cycle Intelligence Hub (this repo)                │
│                                                            │
│  ┌─────────────────────────────────────────────────┐    │
│  │ scripts/run_hub.py (GitHub Actions cron)         │    │
│  │  1. registry.yaml 로드                           │    │
│  │  2. 각 시스템의 latest.json fetch                │    │
│  │  3. 점수/페이즈/차원 추출                        │    │
│  │  4. cross-system insights 자동 생성              │    │
│  │  5. data/hub_summary.json 저장                   │    │
│  │  6. Telegram 통합 리포트 발송                    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                            │
│  ┌─────────────────────────────────────────────────┐    │
│  │ docs/site/index.html (GitHub Pages)              │    │
│  │  - 모든 시스템을 카드 그리드로 표시              │    │
│  │  - Cycle Position Map (전체 사이클 분포)         │    │
│  │  - System Score Timeline (히스토리)              │    │
│  │  - Cross-system insights 패널                    │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
┌──────────┐      ┌──────────┐      ┌──────────────┐
│   CCI    │      │   ASCI   │      │   미래 시스템  │
│ (Crypto) │      │ (AI/Semi)│      │   (KOSPI...)  │
└──────────┘      └──────────┘      └──────────────┘
```

## 🚀 새 시스템 추가 방법

`registry.yaml`을 열고 `systems:` 리스트에 한 항목 추가하기만 하면 끝.

```yaml
- id: kospi
  name: "KOSPI Sector"
  asset_class: "Equities"
  description: "Korean equity sector rotation cycle"
  data_url: "https://jinhae8971.github.io/kospi-sector-advisor/data/latest.json"
  dashboard_url: "https://jinhae8971.github.io/kospi-sector-advisor/"
  icon: "🇰🇷"
  color: "#dc2626"
  score_path: "score"            # latest.json 안에서 점수의 dot-path
  phase_path: "phase"
  dimensions_path: "dimensions"
```

다음 파이프라인 실행(매 6시간) 또는 수동 트리거로 즉시 반영됩니다.

## 📊 자동 생성되는 Cross-System Insights

Hub는 다음 패턴을 자동 감지하여 narratives로 변환합니다:

- **Major divergence** (spread ≥ 40): 자산군간 사이클 위치가 크게 어긋날 때
- **Synchronized euphoria** (2+ systems ≥ 80): 시장 전반 과열 신호
- **Synchronized capitulation** (2+ systems ≤ 20): 광범위한 매수 기회
- **Single-system extreme** (≥ 85 또는 ≤ 15): 개별 시스템 임계점 돌파
- **Stale data warnings** (24h 이상 미갱신): 하위 시스템 장애 감지

## 📲 텔레그램 통합 리포트 예시

```
🏛️ Cycle Intelligence Hub
2026-04-23 08:45 KST

₿ Crypto Cycle
   ███░░░░░░░ 30 🌱 Recovery

🤖 AI / Semiconductor
   ███████░░░ 76 🔥 Late Bull

━━━━━━━━━━━━━━━━━━━━━━━
📊 Active: 2/2  ·  Avg: 53  ·  Spread: 46

🎯 Cross-System Insights
• Major cross-asset divergence
   Crypto Cycle (30, Recovery) vs AI/Semi (76, Late Bull) — spread 46

🔗 Open Hub Dashboard
```

## 📅 운영 일정

- **매 6시간 (00/06/12/18 UTC)**: 정기 집계 + 대시보드 갱신
- **매일 23:45 UTC = 08:45 KST**: 메인 일일 리포트 (텔레그램)
- **수동 트리거**: Actions 탭에서 언제든

스케줄은 의도적으로 하위 시스템들의 23:30 UTC 일일 실행 **이후**에 동작하도록 설계되어, 항상 최신 데이터를 반영합니다.

## 📂 파일 구조

```
cycle-hub/
├── scripts/
│   └── run_hub.py              🎯 메인 파이프라인
├── docs/site/
│   └── index.html              🎨 Hub 대시보드
├── .github/workflows/
│   └── hub-pipeline.yml        ⚙️ Actions cron
├── registry.yaml               📋 시스템 등록 파일
├── data/                       💾 Git이 DB
│   ├── hub_summary.json        최신 통합 스냅샷
│   ├── hub_history.json        시스템별 일별 히스토리
│   └── snapshots/              일별 아카이브
├── requirements.txt
└── README.md
```

---

*v1.0 · Hub aggregator · Powered by GitHub Actions + Pages*
