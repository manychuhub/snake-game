# ☁️ DC-OPS AI | 데이터센터 엔지니어 클라우드 인수인계 시스템

GitHub 저장소와 연동하여 24시간 365일 무중단으로 동작하는 클라우드 웹 서버입니다.

## 🚀 클라우드 무료 배포 방법 (내 PC를 꺼도 상시 가동)

GitHub 저장소(`https://github.com/manychuhub/snake-game`)를 연동하여 무료 클라우드 호스팅 서비스에 원클릭 배포할 수 있습니다.

### 방법 1: Render.com (가장 추천 / 완전 무료)
1. [render.com](https://render.com) 접속 후 **GitHub 계정으로 로그인**
2. **[New +]** 버튼 클릭 ➔ **[Web Service]** 선택
3. **`manychuhub/snake-game`** 저장소 선택
4. 설정값 확인:
   - **Environment**: `Node`
   - **Build Command**: `npm install`
   - **Start Command**: `node server.js`
5. 맨 아래 **[Deploy Web Service]** 클릭!
6. 약 1분 후 `https://xxx.onrender.com` 형태의 **영구 클라우드 주소**가 발급됩니다.

### 방법 2: Glitch 또는 Railway
- GitHub 저장소를 Import하면 즉시 Node.js 클라우드 컨테이너가 생성되어 전 세계 어디서든 접근 가능합니다.

---

## 🛠️ 기능 구성
- **실시간 양방향 동기화**: 모든 엔지니어 화면에서 1.5초 내 동기화
- **완료 체크 및 삭제**: 인수인계 상태 추적 및 DB 저장
- **AI 교대 브리핑**: 미결 이슈 분석 및 우선순위 행동 가이드 자동 생성
- **통합 관제 대시보드**: 장애 티켓, 전력/공조 시설 텔레메트리, 보안 출입 통제
