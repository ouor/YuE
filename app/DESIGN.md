# YuE2 Song Studio — UX & 아키텍처 설계

## 1. 제품 콘셉트

**"악보가 보이는 AI 작곡 스튜디오."** 사용자는 기술 용어(ABC, cot, CFG, VAE)를 몰라도
"만들기 → 듣기 → 바꿔 보기"를 반복할 수 있어야 한다.

핵심 원칙

1. **곡은 버전 트리다.** 모든 결과물은 보관함의 "곡(Song)" 노드로 저장되고, 파생 작업
   (장르 바꾸기, 악보 편집, 연주곡, 커버)은 부모 노드를 가리킨다. 원본은 절대 덮어쓰지 않는다.
2. **악보가 허브다.** 기능 간에 넘겨지는 산출물은 `score.abc` 하나. 토큰/latent는 해당 노드
   안에서만 재사용한다(재현·재디코딩용).
3. **먼저 보여 준다.** 악보가 나오는 즉시 화면에 띄우고 오디오는 이어서 채운다.
4. **다음 행동을 제안한다.** 결과 카드 아래에 "다른 장르로 / 악보 편집 / 연주곡으로" 버튼을
   두어 탭 간 이동을 결과 중심으로 만든다.
5. **고급 옵션은 접어 둔다.** seed와 악보 모드만 "고급"에 노출하고 나머지 추론 파라미터는 숨긴다.

## 2. 화면 구조

```
┌──────────────────────────────────────────────────────────────┐
│  YuE2 Song Studio          Compose in symbols. Create in sound │
├──────────────────────────────────────────────────────────────┤
│ [Create] [New Genre] [Score Editor] [Instrumental] [Cover] [Library] │
├───────────────────────────┬──────────────────────────────────┤
│  입력 영역 (좌)             │  결과 카드 (우)                   │
│  1. 사운드 설명(스타일 빌더) │  ● 진행 단계  ①악보 ②음악 ③오디오  │
│  2. 가사 (+Verse/+Chorus)  │  ▶ 오디오 플레이어                 │
│  ▸ 고급 (모드, seed)        │  ♪ 악보(오선보 | ABC 텍스트)        │
│  [ 곡 만들기 ] [ 중지 ]      │  ⚠ 경고 (잘림 등)                  │
│                           │  [다른 장르로] [악보 편집] [연주곡으로] │
└───────────────────────────┴──────────────────────────────────┘
```

### 탭별 흐름

| 탭 | 사용자 목표 | 흐름 | 모델 호출 |
|---|---|---|---|
| **Create** | 가사로 노래 만들기 | 스타일 빌더 → 가사 → (선택) "녹음 전에 악보 확인" → 결과 | plan → semantic → synth → decode |
| ↳ 악보 확인 모드 | 악보를 보고 결정 | 악보만 생성 → [이 악보로 녹음] 또는 [악보 편집으로] | plan 저장 후 `SymbolicPlan.load`로 정확히 재사용 |
| **New Genre** | 같은 멜로디를 다른 장르로 | 곡 선택 → 새 스타일 → (선택) 원래 코드 유지 → 원곡/새 버전 A/B | 원곡 `score.abc`(코드 제거 시 melody 모드) |
| **Score Editor** | 멜로디·코드·템포 직접 수정 | 곡 선택 → ABC 편집(실시간 오선보) → [악보 검사] → 렌더 → 변경 요약 + A/B | 편집한 ABC를 새 입력으로 |
| **Instrumental** | 보컬 없는 BGM | 설명으로 만들기 / 보관함 곡을 연주곡으로 → 결과 + 변환 리포트 | (설명: plan →) Vocal→Ins 변환 → 렌더 |
| **Cover** | 레퍼런스 곡 재해석 | ① 음원/ABC 업로드(구간 선택) → 멜로디 추출 → ② 노래 커버(새 가사) / 연주곡 커버 → A/B | SheetSage2 → (연주곡이면 변환) → 렌더 |
| **Library** | 결과 관리 | 목록(필터·검색) → 상세(오디오·악보·계보) → 다른 탭에서 열기 / 다운로드 / 이름 변경 / 삭제 | 없음 |

### 공통 컴포넌트

- **Style Builder**: 언어, 보컬, 장르, 분위기, 악기, 템포, 추가 설명 → 스타일 프롬프트를 자동으로
  조립(직접 수정 가능). 연주곡 탭에서는 보컬 선택을 숨긴다.
- **Song Picker**: 보관함 곡 드롭다운 + 미리듣기. 기본값은 "방금 작업한 곡".
- **Result Panel**: 진행 단계 표시, 오디오, 악보(abcjs 오선보 + 재생 / ABC 텍스트), 경고, 다음 행동 버튼.
- **Score View**: abcjs(CDN)로 브라우저에서 렌더. 편집기에서는 서버 왕복 없이 JS로 실시간 갱신.

### 진행 상태 UX

- 단계: ① Writing the score ② Composing the music ③ Rendering audio(합성 + 디코딩)
- 토큰 수와 경과 시간을 표시. 중지 버튼은 실제 모델 루프의 `cancelled` 콜백까지 전달된다.
- GPU 작업은 큐 하나로 직렬화되며, 대기 순번은 Gradio 큐가 보여 준다.

## 3. 아키텍처

```
app/
  app.py                  # 진입점: python app/app.py
  studio/
    config.py             # Settings (환경변수/CLI)
    i18n/                 # en.json(기본), ko.json + 서버 메시지 번역
    core/                 # Gradio 비의존 — API·UI·테스트가 공유
      models.py           # SongMeta, Operation, Status
      store.py            # SongStore: 노드 디렉터리, 메타, 계보, 내보내기
      engine.py           # Engine: GPU 락, YuE2/SheetSage2 수명 관리, 단계 실행
      jobs.py             # JobContext/이벤트, 스레드→제너레이터 브리지
      scores.py           # ABC 도구 브리지(skills/yue2-music 헬퍼 재사용)
      styles.py           # 스타일 빌더 데이터 + compose_style()
      audio.py            # ffmpeg: 미리듣기 mp3, 구간 자르기, 길이
      workflows/          # 기능 = 워크플로 하나 (레지스트리)
        base.py, create.py, restyle.py, edit.py, instrumental.py, cover.py
    ui/                   # Gradio 레이어
      layout.py           # 헤더 + 탭 레지스트리 조립
      components/         # style_builder, score_view, song_picker, result_panel
      tabs/               # 탭 = 모듈 하나 (레지스트리)
      assets/             # app.css, head.html(abcjs)
    api.py                # gr.api / 숨은 이벤트로 공개 API
  tests/                  # 단위 테스트(GPU 불필요) + gradio_client E2E
```

### 확장 포인트

| 추가하려는 것 | 할 일 |
|---|---|
| 새 생성 기능 | `core/workflows/<name>.py`에 `Workflow` 하위 클래스 + `@register` |
| 새 화면 | `ui/tabs/<name>.py`에 `Tab` 하위 클래스 + `TABS`에 등록 |
| 새 API | `api.py`에 함수 하나(워크플로 호출) |
| 새 언어 | `i18n/<lang>.json` 추가 |
| 스타일 옵션 | `core/styles.py` 데이터만 수정 |
| 새 모델(예: MERT2 태깅) | `Engine`에 lazy loader 추가, GPU 락 공유 |

### 곡 노드 저장 구조

```
data/songs/<song_id>/
  meta.json            # id, title, operation, status, parent_id, style, lyrics, mode, seed, ...
  score.abc            # 기능 간 허브
  score.melody.abc     # 파생(코드 제거) — 필요 시 생성
  plan/                # SymbolicPlan.save() (같은 요청 재렌더 전용)
  audio.flac           # 48kHz 24bit 원본
  preview.mp3          # 웹 재생용
  latent.npy, semantic.npy
  source.<ext>         # 커버 레퍼런스(구간 자른 파일)
  transcription/       # SheetSage2 원본 출력
  conversion.json      # 연주곡 변환 리포트
```

`status`: `planned`(악보만) → `rendering` → `complete` | `failed` | `cancelled`.
악보 단계가 끝나면 즉시 `plan/`과 `score.abc`를 기록하므로, 오디오 단계가 실패해도 악보는 남는다.

### GPU/메모리 정책 (RTX 3090 24GB 기준)

- YuE2 파이프라인은 프로세스당 1개, 처음 필요할 때 로드한다.
- SheetSage2가 필요하면 `pipe.close()`로 YuE2 가중치를 GPU에서 내리고, 변환이 끝나면
  SheetSage2를 CPU로 옮긴다. 두 모델이 동시에 GPU에 올라가지 않는다.
- 모든 GPU 작업은 `Engine`의 락 + Gradio `concurrency_id="gpu"`(limit 1)로 직렬화한다.

### i18n

- 정적 UI 문구: `gr.I18n(en=..., ko=...)` — 브라우저 언어로 자동 선택.
- 서버가 만드는 동적 문구(진행 상태, 오류): 같은 번역 테이블을 `Accept-Language` 기준으로 조회.
- 기본은 영어, 누락 키는 영어로 대체.

### API (gradio_client)

| 이름 | 설명 |
|---|---|
| `/health` | 버전, GPU, 모델 로드 상태 |
| `/style_options`, `/compose_style` | 스타일 빌더 데이터/조립 |
| `/create_song` | 곡 생성(`review_first=True`면 악보만) |
| `/render_planned` | 악보만 만든 곡을 그대로 녹음 |
| `/restyle_song` | 같은 멜로디, 새 스타일 |
| `/check_score`, `/edit_song` | 악보 검사 / 편집 악보로 렌더 |
| `/create_instrumental` | 설명 또는 보관함 곡으로 연주곡 |
| `/transcribe_reference` | 음원(파일)·ABC → 멜로디 악보 노드 |
| `/create_cover` | 노래 커버 / 연주곡 커버 |
| `/list_songs`, `/get_song`, `/rename_song`, `/delete_song` | 보관함 |
| `/song_audio`, `/export_song` | 오디오 / zip 파일 다운로드 |

## 4. 구현하며 정한 것

- **중지**: Gradio가 끊은 이벤트의 남은 화면 갱신은 버려지므로, 중지 핸들러가 작업이 정리될 때까지
  기다린 뒤 결과를 직접 그린다. 악보 단계가 끝났으면 악보와 "이 악보로 녹음하기"가 남는다.
  세션별 마지막 작업을 기억해서 중지 클릭이 작업 종료와 겹쳐도 해당 곡을 찾는다.
- **진행 표시**: 합성·디코딩처럼 이벤트가 없는 구간에도 1초마다 경과 시간을 갱신한다.
- **예시 가사**: `gr.Examples` 표 헤더는 번역 라벨을 표시하지 못해 프리셋과 같은 버튼 방식으로 바꿨다.
- **프리셋과 언어**: 장르 바꾸기·커버에서는 가사가 이미 정해져 있으므로 프리셋이 언어를 바꾸지 않는다.
- **채보 악보 정규화**(연주곡 변환 직전에만): SheetSage2의 `% silence` 같은 비표준 구간 주석을 지우고,
  쉼표 안에서 바뀌는 조표(`z2[K:Ab]z8`)를 다음 마디 시작으로 옮긴다. 정리 전후 음표가 정확히 같을 때만 적용한다.
- **제목**: 파생 버전은 `원래 제목 · 작업` 형태로 짓고, 작업 이력은 보관함의 계보로 보여 준다.
- **SheetSage2 로딩**: 원격 코드 모델이라 Hub ID로 불러온다. 로컬 폴더로 부르면 모듈 캐시가 폴더 이름으로
  잡혀 다른 스냅샷의 파일과 섞일 수 있다.
- **모바일(폭 767px 이하)**: 상단 탭 줄은 "…" 메뉴로 접히므로 숨기고 하단 고정 탭 바로 대신한다.
  스타일 세부 설정은 접어서 프리셋과 프롬프트만 보이게 하고, 실행하면 결과 카드로, 탭을 바꾸면 맨 위로 스크롤한다.
  악보는 폭에 맞춰 한 줄 2마디로 다시 배치하고(성부 이름 생략), 보관함 표는 제목·종류·길이만 보인다.
- **Gradio 6 제약**: `launch(css=)`는 `.gradio-container .contain` 안으로 범위가 제한되므로 바깥 프레임 규칙은
  `assets/page.css`를 `<head>`로 넣는다. `launch(js=)`는 호출되지 않고 `<script>`로 삽입되므로 `app.js`는 스스로 실행한다.
