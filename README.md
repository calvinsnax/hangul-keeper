# hangul-keeper

한국어로 대화하는 동안 Claude Code가 영어로 답하지 못하게 붙잡는 훅 플러그인.

`"language": "한국어"` 설정은 시스템 프롬프트 맨 앞에 한 번 들어갈 뿐이라, 대화가 길어지고 영어 도구 출력이 쌓이면 힘이 빠진다. 이 플러그인은 지시를 매 턴 다시 넣고, 그래도 영어가 나오면 훅으로 붙잡는다.

## 설치

Claude Code 안에서:

```
/plugin marketplace add calvinsnax/hangul-keeper
/plugin install hangul-keeper@hangul-keeper
```

또는 터미널에서:

```
claude plugin marketplace add calvinsnax/hangul-keeper
claude plugin install hangul-keeper@hangul-keeper
```

새 세션부터 적용된다. Python 3.9 이상이 필요하다(표준 라이브러리만 사용).

## 계층

| 훅 | 하는 일 |
|---|---|
| UserPromptSubmit | 사용자 프롬프트로 이번 턴 언어를 정하고, 한국어면 지시를 최신 메시지 옆에 다시 주입 |
| PostToolUse | 도구 호출 앞에 쓴 중간 문장이 영어면 "이어서는 한국어로" 통보 (메시지당 1회) |
| Stop | 최종 답변이 사실상 영어면 한 번 막고 한국어로 다시 쓰게 함 |

## 판정

- **턴 언어**: 직접 친 부분(붙여넣기, 슬래시 명령, system-reminder 제외)에 한글이 2자 이상이면 ko, 한글 없이 영문 15자 이상이면 en, 그 밖에는 직전 상태 유지. "영어로", "in English" 같은 요청이 있으면 en. 세션별로 `~/.claude/hangul-keeper/state/`에 저장.
- **답변 언어**: 코드블록, 인라인 코드, URL, 경로, 파일명을 빼고 단어 단위로 센다. 한글이 섞인 단어(`Stop만` 포함)는 한국어. 한국어 단어 비율이 0.3 미만이면 영어로 본다. 12단어(중간 문장은 6단어) 미만은 판정하지 않는다.
- 글자 단위가 아니라 단어 단위인 이유: 한글 한 음절이 영문 여러 글자 몫을 해서, 글자로 세면 용어 많은 한국어 답변이 영어로 오판된다.

실제 사용 기록의 답변 1,821건으로 재생 검증했을 때 한국어 답변을 영어로 오판한 사례는 없었다.

## 설정

`~/.claude/hangul-keeper/config.json`에 바꿀 키만 쓰면 `config.default.json` 위에 병합된다.

- 전체 끄기: `HANGUL_KEEPER_OFF=1`
- 계층별: `HANGUL_KEEPER_PROMPT=0`, `HANGUL_KEEPER_POSTTOOL=0`, `HANGUL_KEEPER_STOP=0`
- 발화 기록: `~/.claude/hangul-keeper/hits.log`

## 개발

```
python3 tests/test_keeper.py
claude --plugin-dir .   # 설치본 대신 소스로 실행
```

## 라이선스

MIT
