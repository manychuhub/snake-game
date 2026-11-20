# SHIFT BRIDGE AWS 사설 웹 파일럿

웹앱과 BridgeCLI를 Amazon Linux EC2에서 함께 실행합니다. 사용자는 사내망 또는 VPN에서 내부 Application Load Balancer의 HTTPS 주소로 접속하고 Cognito 로그인과 MFA를 거칩니다. 웹앱은 ALB 서명과 서명자 ARN을 확인해 보고서 승인자를 기록합니다. Cognito 사용자 풀은 관리자 초대 방식입니다. 이 파일럿에서는 초대된 사용자 모두가 같은 애플리케이션 권한을 갖습니다.

Gemini 키는 AWS Secrets Manager에 두고 EC2 역할이 해당 시크릿만 읽습니다. 호스트는 키를 `/run`의 관리자 전용 파일로 가져옵니다. 시작 프로세스가 BridgeCLI에만 키를 전달합니다. 웹과 BridgeCLI는 각각 다른 OS 사용자로 실행되며 웹에는 별도 로컬 토큰이 전달됩니다. GitHub는 OIDC 단기 AWS 자격 증명을 사용합니다. 이미지에 `.env`, 데이터베이스와 업로드 파일은 포함되지 않습니다.

## 첫 배포

1. 승인된 일반 AWS 리전과 VPC에 사설 서브넷을 준비합니다. ALB는 서로 다른 가용 영역의 서브넷 두 개를 사용합니다. 사내망이나 VPN에서 내부 ALB로 접근하고, ALB와 EC2는 NAT 등을 통해 IPv4 HTTPS로 Cognito, AWS 서비스 및 Gemini에 접근할 수 있어야 합니다.
2. 접속할 호스트 이름에 맞는 ACM 인증서를 같은 리전에 준비합니다. Secrets Manager에 기본 관리형 KMS 키를 사용해 `GEMINI_API_KEY` 필드가 있는 JSON 시크릿을 생성합니다. 키는 콘솔에서 입력합니다. 앱과 AWS 배포 설정에는 시크릿의 전체 ARN만 전달합니다.
3. 계정에서 GitHub Actions용 `token.actions.githubusercontent.com` IAM OIDC 공급자에 `sts.amazonaws.com` 대상이 설정되어 있는지 확인합니다. 배포 브랜치 `shift-bridge`의 쓰기와 검토 권한을 배포 담당자에게 제한합니다.
4. [CloudFormation 템플릿](aws.yml)으로 스택을 만들고 IAM 리소스 생성을 확인합니다. `ClientCidr`는 사내 또는 VPN 대역, `GitHubRepository`는 `소유자/저장소`, `GeminiModel`은 조직에서 승인한 모델 ID를 사용합니다. 스택이 만들어지면 사설 DNS에서 `WebHostname`을 `PrivateDnsTarget`에 연결합니다. Cognito 사용자 풀에 테스트 사용자를 만들고 SSM에서 EC2가 온라인인지 확인합니다.
5. GitHub 저장소의 **Settings → Secrets and variables → Actions → Variables**에 아래 값을 등록합니다. 그 후 배포 브랜치에 반영하거나 **SHIFT BRIDGE AWS release**를 그 브랜치에서 수동 실행합니다.

| GitHub Actions 변수 | 값 |
| --- | --- |
| `AWS_REGION` | 스택 리전 |
| `AWS_RELEASE_BRANCH` | 스택의 `GitHubReleaseBranch` 값. 생략하면 `shift-bridge` |
| `AWS_RELEASE_ROLE_ARN` | `ReleaseRoleArn` 출력 |
| `AWS_ECR_REPOSITORY_URI` | `EcrRepositoryUri` 출력 |
| `AWS_APPLICATION_INSTANCE` | `ApplicationInstance` 출력 |
| `AWS_RELEASE_DOCUMENT` | `ReleaseDocument` 출력 |

첫 성공 후 VPN에서 `WebUrl`을 엽니다. 로그아웃 상태에서 Cognito 로그인으로 이동하는지 확인한 뒤 테스트 계정과 가상 기록으로 **BridgeCLI 연결 테스트 → 업무 기록 등록 → 교대 기간 선택 → 보고서 생성 및 승인**을 확인합니다. 다음 배포에서는 동일 기록이 남아 있는지 확인합니다. AWS 리소스 비용과 Gemini 사용량이 발생할 수 있습니다.

## 웹 업데이트와 복구

- 배포 브랜치 변경 시 GitHub Actions가 Python 테스트, JavaScript 구문 및 이미지 빌드를 확인합니다. 이후 커밋 SHA로 이미지를 ECR에 올리고 전용 Systems Manager 문서로 교체합니다. 템플릿 자체의 변경은 CloudFormation에서 별도로 적용합니다.
- 교체 전 데이터베이스를 `/var/lib/shift-bridge/backup`에 백업합니다. 새 웹의 상태 확인이 실패하면 이전 컨테이너로 복귀합니다. 상태 확인은 웹 서버와 초기 BridgeCLI 기동을 확인하며 실제 Gemini 호출과 사용자 로그인을 검증하는 단계는 위의 브라우저 점검입니다.
- 단일 EC2와 암호화된 EBS를 사용하는 파일럿으로 웹 교체 중 짧은 중단이 있을 수 있습니다. 컨테이너 교체 시 데이터 볼륨이 유지됩니다. EC2가 교체되면 이전 EBS 볼륨은 별도로 보존되며 스냅샷이나 기존 볼륨에서 데이터를 복원해야 합니다. 호스트 로컬 백업의 최신 버전은 다음 교체 시 갱신됩니다.
- 키 교체는 동일한 시크릿의 새 버전을 등록하고 재배포합니다. GitHub 작업이 실패하면 작업에 기록된 SSM 명령 ID로 결과를 확인합니다.

## 데이터 범위

Gemini는 AWS 밖의 Google API입니다. 파일럿은 가상 데이터로 검증하고, 실제 티켓·장비 식별자·로그·문서·음성의 사용 여부는 조직의 데이터 반출 및 서비스 승인 범위를 따릅니다. 브라우저 음성 인식은 AWS HTTPS 배포에서 비활성화되어 있으며, 오디오 업로드 분석은 설정한 Gemini를 사용합니다.

보고서는 교대 기간에 등록된 업무와 그 전에 등록되어 아직 완료되지 않은 업무를 포함합니다. 시작과 종료에는 브라우저의 현지 시각을 사용하며 서버는 UTC로 조회합니다. 파일럿에서 보고서당 최대 50건을 처리합니다. 웹과 기존 CLI의 업무 DB는 별개입니다. 이 스택에는 Amazon 내부 티켓·알림·운영 시스템 연결이 들어 있지 않습니다.

## 앱 관리자 계정

AWS에서는 Cognito 인증 후 앱 계정으로 로그인합니다. 배포 후 EC2의 관리 세션에서 아래 명령의 컨테이너 이름을 현재 실행 중인 컨테이너 이름으로 바꿔 실행하고, 프롬프트에 관리자 비밀번호를 입력합니다.

```sh
docker exec -it --user 10001:10001 -e SHIFT_BRIDGE_DB_PATH=/data/web/shift_bridge.db <container> python /app/Agent/accounts.py admin
```
