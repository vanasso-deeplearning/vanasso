# 📂 VAN협회 예산/결산 관리 및 사내 시스템 개발 명세서

## 1. 프로젝트 개요

- **목표:** 엑셀로 관리하던 현금출납장, 예산 관리, 결산 보고서 작성을 웹 기반으로 자동화.
- **핵심 가치:**

1. **예산 통제:** 지출 시 잔여 예산 즉시 확인.
2. **결산 자동화:** 버튼 클릭 한 번으로 [대차대조표/수지결산서] PDF 출력.
3. **편의성:** 법인카드 엑셀 일괄 업로드 및 자동 분류.
4. **안정성:** 사용자 인증, 데이터 백업, 에러 처리를 통한 운영 안정성 확보.

- **사용 환경:** 사내 PC 1대에 설치하여 내부망 공유 (On-Premise). 향후 외부 호스팅 전환 가능.
- **사용자:** 총 3명 (동시 접속, 기본 로그인 인증 적용).

## 1.1 프로젝트 디렉토리 구조 (Directory Structure)

> **설계 원칙:** 관심사의 분리(Separation of Concerns). 화면(View)과 비즈니스 로직(Service), 데이터 접근(Selector)을 명확히 분리하여 유지보수성을 극대화한다.

````text
vanasso/ (루트 프로젝트)
├── 📂 .venv/                   # 가상환경 (Virtual Environment)
├── 📂 config/                  # [설정] Django 전역 설정
│   ├── settings.py             # DB연결, 앱 등록 등 환경설정
│   ├── urls.py                 # 사이트 전체 주소 관리
│   └── wsgi.py                 # 서버 실행 진입점
│
├── 📂 common/                  # [공통] 범용적으로 쓰이는 도구 모음
│   ├── __init__.py
│   ├── constants.py            # ★ 상수 (결재상태 코드, 계정타입 등)
│   ├── utils.py                # ★ 범용 유틸 (날짜 계산, 포맷팅 등)
│   └── decorators.py           # 권한 체크 등 장식자
│
├── 📂 finance/                 # [핵심] 재무관리 메인 앱
│   ├── 📂 migrations/          # DB 변경 이력 관리
│   ├── 📂 static/              # [UX] 디자인 리소스
│   │   └── finance/
│   │       ├── css/            # 스타일시트 (custom.css, adminlte.css)
│   │       ├── js/             # 스크립트 (chart.js, excel_upload.js)
│   │       └── img/            # 이미지, 아이콘
│   │
│   ├── 📂 templates/           # [Screens] 화면 HTML
│   │   └── finance/
│   │       ├── base.html       # 레이아웃 (상단바, 메뉴바 공통)
│   │       ├── dashboard.html  # 대시보드
│   │       ├── transaction_form.html # 입력 팝업
│   │       └── reports/        # 리포트 관련 화면들
│   │
│   ├── __init__.py
│   ├── admin.py                # 관리자 페이지 설정
│   ├── apps.py                 # 앱 설정
│   ├── models.py               # [DB] 데이터베이스 구조 정의
│   ├── selectors.py            # [DB Control] 복잡한 데이터 조회/리포트 쿼리 분리
│   ├── services.py             # [Service] ★ 핵심 비즈니스 로직 (예산체크, 결산)
│   ├── urls.py                 # finance 앱 내부 주소 관리
│   └── views.py                # [Screens] 화면과 로직을 연결하는 컨트롤러
│
├── .gitignore                  # 깃 제외 목록
├── manage.py                   # 실행 명령어 관리자
└── requirements.txt            # 설치 라이브러리 목록
---

## 2. 사전 준비 (Prerequisites)

> 개발 시작 전 아래 단계를 순서대로 완료해야 합니다. 각 단계의 ✅ 확인 방법을 통해 정상 설치 여부를 검증하세요.

### Step 1: Python 설치

1. https://www.python.org/downloads/ 접속
2. **Python 3.11 이상** 버전 다운로드 (Windows installer 64-bit 권장)
3. 설치 시 **"Add Python to PATH"** 체크 필수
4. 설치 완료

**✅ 확인 방법:**
```cmd
python --version
````

→ `Python 3.11.x` 이상 출력되면 성공

---

### Step 2: 프로젝트 폴더 이동

1. 명령 프롬프트(cmd) 또는 PowerShell 실행
2. 프로젝트 폴더로 이동

```cmd
cd c:\Users\user\Documents\vanasso
```

**✅ 확인 방법:**

```cmd
dir
```

→ `finance_setup_template.xlsx`, `development_plan.md`, `rules.md` 파일이 보이면 성공

---

### Step 3: 가상환경 생성 및 활성화

1. 가상환경 생성

```cmd
python -m venv .venv
```

2. 가상환경 활성화

```cmd
.venv\Scripts\activate
```

**✅ 확인 방법:**

- 명령 프롬프트 앞에 `(.venv)` 표시되면 성공
- 예: `(.venv) c:\Users\user\Documents\vanasso>`

> **참고:** 이후 모든 작업은 가상환경이 활성화된 상태에서 진행합니다.

---

### Step 4: 필수 라이브러리 설치

가상환경 활성화 상태에서 아래 명령 실행:

```cmd
pip install django pandas openpyxl django-jazzmin weasyprint
```

**✅ 확인 방법:**

```cmd
pip list
```

→ `Django`, `pandas`, `openpyxl`, `django-jazzmin`, `weasyprint` 목록에 표시되면 성공

---

### Step 5: WeasyPrint 의존성 설치 (Windows 전용)

WeasyPrint는 PDF 생성을 위해 GTK 라이브러리가 필요합니다.

**방법 A) MSYS2 설치 (권장)**

1. https://www.msys2.org/ 에서 MSYS2 설치
2. MSYS2 터미널 실행 후 아래 명령 입력:

```bash
pacman -S mingw-w64-x86_64-pango mingw-w64-x86_64-gtk3
```

3. 시스템 환경변수 PATH에 `C:\msys64\mingw64\bin` 추가

**방법 B) GTK Runtime 설치**

1. https://github.com/nickvanosdijk/gtk-for-windows-runtime-environment-installer/releases 에서 다운로드
2. 설치 후 시스템 재부팅

**✅ 확인 방법:**

```cmd
python -c "from weasyprint import HTML; print('WeasyPrint OK')"
```

→ `WeasyPrint OK` 출력되면 성공 (에러 발생 시 GTK 설치 재확인)

---

### Step 6: Git 초기화 (선택사항)

버전 관리를 위해 Git 저장소 초기화를 권장합니다.

```cmd
git init
git add .
git commit -m "Initial commit: 프로젝트 초기 설정"
```

**✅ 확인 방법:**

```cmd
git status
```

→ `On branch master` 또는 `On branch main` 표시되면 성공

---

### Step 7: 프로젝트 파일 확인

아래 파일들이 프로젝트 폴더에 존재하는지 확인:

| 파일명                        | 용도                                           |
| ----------------------------- | ---------------------------------------------- |
| `finance_setup_template.xlsx` | 초기 데이터 (계정과목, 회원사, 고정자산, 예산) |
| `development_plan.md`         | 개발 명세서 (본 문서)                          |
| `rules.md`                    | 개발 규칙/지침                                 |

**✅ 모든 준비 완료 체크리스트:**

- [ ] Python 3.11+ 설치됨
- [ ] 가상환경 `.venv` 생성 및 활성화됨
- [ ] Django, pandas, openpyxl, django-jazzmin, weasyprint 설치됨
- [ ] WeasyPrint GTK 의존성 설치됨
- [ ] 프로젝트 파일 3개 존재함
- [ ] (선택) Git 초기화됨

> **다음 단계:** 위 체크리스트 완료 후 "Phase 1: 환경 구축 및 기초 설정" 진행

---

## 3. 기술 스택 (Tech Stack)

- **Backend:** Python 3.11+, Django 5.0+
- **Database:** SQLite (초기) -> 추후 PostgreSQL 마이그레이션 용이하도록 ORM 사용
- **Frontend:** Django Template + **Bootstrap 5 (AdminLTE or Jazzmin 테마 권장)**
- **Reporting:** `WeasyPrint` (HTML to PDF 변환 라이브러리)
- **Data Process:** `pandas` (엑셀 업로드/다운로드 처리)

---

## 4. 데이터베이스 설계 (Models)

> **Note:** 초기 데이터는 제공된 `finance_setup_template.xlsx`를 통해 마이그레이션한다.

### 4.1. 기초 정보 (Master Data)

**A. 계정 과목 (AccountSubject)**

- 관리항목: `계정코드`, `대분류(관)`, `중분류(항)`, `소분류(목)`, `계정성격(자산/부채/수입/비용)`, `결산서_위치`
- _활용:_ 엑셀 Sheet1 데이터 로드.

**B. 예산 관리 (Budget)**

- 관리항목: `회계연도`, `계정과목_FK`, `연간예산액`, `추경예산액`
- _활용:_ 엑셀 Sheet4 데이터 로드. 지출 입력 시 잔액 체크에 사용.

**C. 거래처/회원사 (Partner)**

- 관리항목: `상호명`, `사업자번호`, `유형(일반/회원사)`, `담당자`
- _활용:_ 엑셀 Sheet2 데이터 로드. 수입 입력 시 회원사 매핑.

**D. 고정자산 (FixedAsset)**

- 관리항목: `자산명`, `취득일`, `취득가액`, `내용연수`, `상각방법(정액법)`, `현재잔액`
- _활용:_ 엑셀 Sheet3 데이터 로드. 결산 시 감가상각비 자동 계산용.

### 4.2. 거래 내역 (Transaction Data)

**E. 거래 내역 (Transaction)**

- `일자 (date)`
- `구분 (type)`: 수입 / 지출 / 대체(결산분개용)
- `계정과목_FK (account)`: AccountSubject 모델 연결
- `적요 (description)`: 거래 상세 내역
- `거래처_FK (partner)`: (선택) Partner 모델 연결
- `금액 (amount)`
- `결제수단 (method)`: 현금 / 예금 / 법인카드 / 기타
- `증빙파일 (receipt)`: 영수증 이미지 경로 (Media 폴더 저장)
- `상태 (state)`: **승인(Approved)** (향후 결재 기능 확장 대비 필드)

---

## 5. 핵심 기능 상세 (Functional Specs)

### 5.1. 초기 세팅 (Setup)

- **기능:** `finance_setup_template.xlsx` 파일을 읽어 DB를 초기화하는 파이썬 스크립트(`load_initial_data.py`) 구현.
- **로직:**
  - Sheet1 -> `AccountSubject` 테이블 적재
  - Sheet2 -> `Partner` 테이블 적재
  - Sheet3 -> `FixedAsset` 테이블 적재
  - Sheet4 -> `Budget` 테이블 적재

### 5.2. 지출/수입 입력 (Transaction Input)

- **개별 입력:** 날짜, 구분, 계정과목(SelectBox), 금액, 적요 입력.
- **★ 예산 통제 로직:**
  - 지출 계정 선택 시 -> 해당 계정의 **[잔여 예산]**을 실시간으로 화면에 표시.
  - 예산 초과 시 -> 경고 모달(Alert) 띄움 (입력 차단은 하지 않음).
- **★ 카드 엑셀 업로드:**
  - 카드사 엑셀 업로드 -> 화면에 리스트 표시 -> 사용자가 '계정과목' 일괄 지정 -> 저장.
  - _편의기능:_ 키워드 매칭 (예: '스타벅스' 포함 시 -> '식대' 자동 프리셋).

### 5.3. 결산 및 리포트 (Closing & Reporting)

- **감가상각 자동화:** '결산' 버튼 클릭 시, 고정자산 대장의 데이터를 기반으로 감가상각비 지출 내역을 자동 생성(분개).
- **월간 예산 집행 내역서 (PDF):**
  - 제공된 PDF 양식 준수.
  - [예산액] - [누적 지출액] = [잔액] 및 [집행률(%)] 자동 계산 표시.
- **연차 결산서 (PDF):**
  - **대차대조표:** 자산/부채 계정 집계.
  - **수지결산서:** 수입/비용 계정 집계 (협회비 수입 명세서 포함).

### 5.4. 인증 (Authentication)

- **로그인 시스템:** Django 내장 인증(`django.contrib.auth`) 활용.
- **기능:**
  - 사용자 로그인/로그아웃
  - 비로그인 사용자 접근 차단 (`@login_required` 데코레이터)
  - 초기 관리자 계정 생성 (`createsuperuser`)
- **세션 관리:** 30분 미활동 시 자동 로그아웃.

### 5.5. 백업 및 복구 (Backup & Recovery)

- **자동 백업 스크립트:** `backup_db.py` 구현.
  - SQLite 파일(`db.sqlite3`)을 `backups/` 폴더에 날짜별 복사.
  - 형식: `db_backup_YYYYMMDD_HHMMSS.sqlite3`
- **백업 주기:** Windows 작업 스케줄러로 매일 자동 실행 권장.
- **보관 정책:** 최근 30일분 유지, 이전 백업은 자동 삭제.
- **복구 절차:** 백업 파일을 `db.sqlite3`로 교체 후 서버 재시작.

### 5.6. 에러 처리 (Error Handling)

- **공통 에러 처리:**
  - 모든 View에 `try-except` 적용.
  - 사용자 친화적 에러 메시지 표시 (기술적 내용 노출 금지).
  - 에러 발생 시 로그 파일(`logs/error.log`)에 기록.
- **엑셀 업로드 검증:**
  - 파일 형식 검증 (`.xlsx`, `.xls`만 허용).
  - 필수 컬럼 누락 시 상세 오류 안내.
  - 데이터 타입 오류(날짜, 숫자) 검출 및 해당 행 표시.
- **트랜잭션 처리:**
  - 일괄 저장 시 `@transaction.atomic` 적용.
  - 중간 실패 시 전체 롤백으로 데이터 정합성 보장.

---

## 6. 개발 로드맵 (Milestones)

### Phase 1: 환경 구축 및 기초 설정

1. Django 프로젝트 생성 및 `startapp finance`.
2. `models.py` 작성 및 DB 마이그레이션.
3. `load_initial_data.py` 스크립트 작성 (업로드된 엑셀 데이터 DB 적재).
4. Django Admin(Jazzmin) 설정으로 기초 데이터 관리 화면 구성.
5. **[추가] 사용자 인증 설정:** 로그인/로그아웃 페이지, `@login_required` 적용.
6. **[추가] 백업 스크립트 작성:** `backup_db.py` 구현 및 테스트.

### Phase 2: 거래 처리 및 엑셀 연동

1. 메인 대시보드 (현재 잔액, 예산 현황 요약) 구현.
2. 거래 내역 등록 폼 (수입/지출) 개발.
3. 법인카드 사용 내역 엑셀 업로드 및 매핑 기능 개발.
4. 지출 입력 시 예산 잔액 체크 API 연동.
5. **[추가] 엑셀 업로드 에러 처리:** 파일 검증, 데이터 타입 오류 처리, 사용자 안내 메시지.

### Phase 3: 리포트 및 결산

1. 월간 예산 집행 내역 화면 및 PDF 출력 기능(`WeasyPrint`).
2. 결산 로직 구현 (감가상각비 계산 등).
3. 최종 결산서(대차대조표, 수지결산서) PDF 템플릿 제작.
4. **[추가] 에러 로깅 시스템:** `logs/error.log` 파일 기록 설정.

### Phase 4: 테스트 및 배포

1. 통합 테스트: 주요 기능 시나리오별 검증.
2. 에러 처리 테스트: 잘못된 입력, 파일 업로드 실패 등 예외 상황 테스트.
3. 사무실 메인 PC에 Python 및 프로젝트 설치.
4. 네트워크 공유 설정 (`python manage.py runserver 0.0.0.0:8000`).
5. **[추가] 백업 자동화:** Windows 작업 스케줄러에 백업 스크립트 등록.
6. 사용자 교육 및 인계 (로그인 방법, 백업 복구 절차 포함).
