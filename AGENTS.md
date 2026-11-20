# SHIFT BRIDGE 개발 작업

- 개발 변경을 검증한 뒤 GitHub `manychuhub/snake-game`의 `shift-bridge` 브랜치에 반영하고, 원격 커밋에서 반영 여부를 확인합니다.
- Windows에서는 `Publish.bat --once`로 지금 반영할 수 있고, `Publish.bat --install`로 로그인 때 자동 반영을 시작합니다. Git 네트워크 접근이 제한되면 연결된 GitHub 도구를 사용합니다.
- 공개 업로드에는 `publish.py`의 `PATHS`에 지정한 소스만 사용합니다. 새 소스는 필요할 때 목록에 추가합니다. API 키, 인증 토큰, 업무 DB, 업로드 자료는 게시하지 않습니다.
