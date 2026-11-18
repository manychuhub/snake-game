#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHIFT BRIDGE - AWS DCO AI 업무 인수인계 시스템
[Main Web Application Server]
- 정적 웹 UI와 JSON API를 제공하는 서버
- 로컬 루프백 또는 인증된 AWS ALB 뒤에서 실행
"""
import os
import sys
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer

import database as db
import gemini_client as gemini

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_PATHS = {'/', '/index.html', '/style.css', '/app.js'}

PORT = int(os.environ.get("PORT", 8000))
HOST = os.getenv('SHIFT_BRIDGE_WEB_HOST', '127.0.0.1')
EXPECTED_SIGNER = os.getenv('SHIFT_BRIDGE_ALB_ARN')
PUBLIC_ORIGIN = os.getenv('SHIFT_BRIDGE_PUBLIC_ORIGIN')
MAX_REQUEST_BYTES = 14_000_000

if EXPECTED_SIGNER:
    from alb_identity import verified_subject

class ShiftBridgeHandler(SimpleHTTPRequestHandler):
    timeout = 25

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'self'; script-src-attr 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                         "font-src 'self' https://cdnjs.cloudflare.com; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if PUBLIC_ORIGIN:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
        super().end_headers()

    def log_request(self, code='-', size='-'):
        # Do not put query strings or attacker-controlled paths into deployment logs.
        if isinstance(code, int) and code >= 500:
            self.log_message('Request failed with HTTP %d', code)

    def log_error(self, _format, *args):
        # BaseHTTPRequestHandler's error formats can include untrusted request text.
        pass

    def authorize(self):
        self.subject = None
        if EXPECTED_SIGNER:
            self.subject = verified_subject(self.headers.get('x-amzn-oidc-data', ''), EXPECTED_SIGNER)
            if not self.subject:
                self.send_json({'error': '인증된 세션이 필요합니다.'}, 401)
                return False
        else:
            port = self.server.server_address[1]
            if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
                self.send_json({'error': '로컬 웹 주소로 접속하세요.'}, 403)
                return False
        return True

    def send_json(self, data, status_code=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def parse_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length < 0 or self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1:
            raise ValueError
        if length > MAX_REQUEST_BYTES:
            raise OverflowError
        if not length:
            return {}
        if self.headers.get_content_type() != 'application/json':
            raise ValueError
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError
        return body

    # ==========================================================================
    # GET 요청 라우팅
    # ==========================================================================
    def do_GET(self):
        if self.path == '/healthz':
            return self.send_json({'status': 'ok'})
        if not self.authorize():
            return
        try:
            self.route_get()
        except gemini.BridgeError as error:
            self.send_json({'error': str(error)}, 502)

    def do_HEAD(self):
        if self.authorize():
            if urllib.parse.urlsplit(self.path).path in STATIC_PATHS:
                return super().do_HEAD()
            self.send_json({'error': '알 수 없는 경로입니다.'}, 404)

    def route_get(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # 1. API 라우트 처리
        if path == '/api/logs':
            status_filter = query.get('status', [None])[0]
            logs = db.get_work_logs(limit=100, status_filter=status_filter)
            return self.send_json({"logs": logs})

        elif path == '/api/reports':
            reports = db.get_handover_reports(limit=20)
            return self.send_json({"reports": reports})

        elif path == '/api/docs':
            docs = db.get_technical_docs()
            return self.send_json({"docs": docs})

        elif path == '/api/anomalies/stats':
            stats = db.get_anomaly_statistics()
            return self.send_json(stats)

        elif path == '/api/audit':
            trails = db.get_audit_trails(limit=50)
            return self.send_json({"audit_trails": trails})

        elif path == '/api/settings/status':
            health = gemini.get_bridge_health()
            return self.send_json({
                "api_key_configured": bool(health.get("api_key_configured")),
                "engine_ready": bool(health.get("auth_configured")),
                "masked_key": "BridgeCLI",
                "model": gemini.get_active_model(),
                "signed_in_as": self.subject,
            })

        # 2. 정적 HTML 파일 서빙
        if path not in STATIC_PATHS:
            return self.send_json({'error': '알 수 없는 경로입니다.'}, 404)
        self.path = '/index.html' if path == '/' else path
        super().do_GET()

    # ==========================================================================
    # POST 요청 라우팅
    # ==========================================================================
    def do_POST(self):
        if not self.authorize():
            return
        origin = self.headers.get('Origin')
        expected = PUBLIC_ORIGIN or f"http://{self.headers.get('Host')}"
        fetch_site = self.headers.get('Sec-Fetch-Site')
        if ((origin is not None and origin != expected) or (PUBLIC_ORIGIN and origin != expected)
                or fetch_site in {'cross-site', 'same-site'}):
            return self.send_json({'error': '같은 사이트에서 보낸 요청이 필요합니다.'}, 403)
        try:
            body = self.parse_json_body()
        except OverflowError:
            return self.send_json({'error': '요청 본문이 너무 큽니다.'}, 413)
        except (ValueError, RecursionError, OSError):
            return self.send_json({'error': '유효한 JSON 객체를 보내세요.'}, 400)
        try:
            self.route_post(body)
        except gemini.BridgeError as error:
            self.send_json({'error': str(error)}, 502)
        except (TypeError, AttributeError, ValueError):
            self.send_json({'error': '요청 항목 형식이 올바르지 않습니다.'}, 400)

    def route_post(self, body):
        path = urllib.parse.urlparse(self.path).path

        # 기능 1: 원문 분석 및 11개 필드 자동 분류
        if path == '/api/logs/classify':
            raw_text = body.get('raw_text', '').strip()
            if not raw_text:
                return self.send_json({"error": "업무 원문 텍스트가 비어 있습니다."}, 400)
            
            classified = gemini.classify_raw_work_log(raw_text)
            # 누락 정보 사전 탐지
            missing_issues = gemini.detect_missing_information(classified)
            classified['missing_alerts'] = missing_issues
            return self.send_json(classified)

        # 업무 기록 정식 저장
        elif path == '/api/logs/create':
            if body.get('status') != '완료':
                p_eval = gemini.evaluate_task_priority(body)
                body.update({
                    'priority_score': p_eval.get('priority_score', 50),
                    'priority_tier': p_eval.get('priority_tier', 'P3')
                })
            log_id = db.add_work_log(body)
            saved = db.get_work_log_by_id(log_id)
            return self.send_json({"success": True, "log": saved})

        # 업무 기록 업데이트
        elif path == '/api/logs/update':
            log_id = body.get('id')
            if not log_id:
                return self.send_json({"error": "ID가 필요합니다."}, 400)
            db.update_work_log(log_id, body)
            updated = db.get_work_log_by_id(log_id)
            return self.send_json({"success": True, "log": updated})

        # 업무 기록 삭제
        elif path == '/api/logs/delete':
            log_id = body.get('id')
            if not log_id:
                return self.send_json({"error": "ID가 필요합니다."}, 400)
            db.delete_work_log(log_id)
            return self.send_json({"success": True, "deleted_id": log_id})

        # 기능 2: 8개 섹션 인수인계 종합 보고서 생성
        elif path == '/api/reports/generate':
            shift_start, shift_end = body.get('shift_start'), body.get('shift_end')
            if shift_start or shift_end or self.subject:
                if not isinstance(shift_start, str) or not isinstance(shift_end, str):
                    return self.send_json({'error': '교대 시작과 종료 시각을 지정하세요.'}, 400)
                start, end = datetime.fromisoformat(shift_start), datetime.fromisoformat(shift_end)
                if start.tzinfo is None or end.tzinfo is None or start >= end:
                    return self.send_json({'error': '시간대를 포함한 올바른 교대 기간을 지정하세요.'}, 400)
                bounds = [value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S') for value in (start, end)]
                logs = db.get_shift_logs(*bounds)
                if len(logs) > 50:
                    return self.send_json({'error': '대상 기록이 50건을 초과합니다. 교대 기간과 이전 미완료 기록을 확인하세요.'}, 422)
            else:
                logs = db.get_work_logs(limit=50)
            if not logs:
                return self.send_json({"error": "인수인계 보고서를 생성할 업무 기록이 없습니다."}, 400)
            
            report_md = gemini.generate_handover_report_content(logs)
            report_id = db.save_handover_report({
                "shift_title": body.get("shift_title", f"{time.strftime('%Y-%m-%d')} 정기 교대 인수인계 보고서"),
                "outgoing_shift": body.get("outgoing_shift", "야간조"),
                "incoming_shift": body.get("incoming_shift", "주간조"),
                "author": self.subject or body.get("author", "DCO 당직 엔지니어"),
                "raw_markdown": report_md
            })
            return self.send_json({
                "success": True,
                "report_id": report_id,
                "raw_markdown": report_md
            })

        # 기능 2: 인수인계 보고서 최종 검토 및 공식 승인
        elif path == '/api/reports/approve':
            report_id = body.get('id')
            approver = self.subject or body.get('approver_name', 'DCO 책임자')
            edited_md = body.get('edited_markdown')
            if not report_id:
                return self.send_json({"error": "보고서 ID가 필요합니다."}, 400)
            if not db.approve_handover_report(report_id, approver, edited_md):
                return self.send_json({'error': '검토 대기 중인 보고서를 찾을 수 없습니다.'}, 409)
            return self.send_json({"success": True, "approved_by": approver, "message": f"보고서 #{report_id}가 공식 승인되었습니다."})

        # 기능 4: 음성 텍스트 정제 및 전문 용어 추출
        elif path == '/api/voice/process':
            transcript = body.get('transcript', '').strip()
            if not transcript:
                return self.send_json({"error": "음성 변환 텍스트가 비어 있습니다."}, 400)
            cleaned = gemini.clean_voice_transcript(transcript)
            return self.send_json(cleaned)

        # 기능 4: 오디오 파일 직접 업로드 처리 (Multimodal)
        elif path == '/api/voice/upload':
            audio_base64 = body.get('audio_base64', '')
            mime_type = body.get('mime_type', 'audio/wav')
            if not audio_base64:
                return self.send_json({"error": "오디오 파일 데이터가 비어 있습니다."}, 400)
            result = gemini.process_audio_file(audio_base64, mime_type)
            return self.send_json(result)

        # 기능 5: 기술 문서 업로드 및 분석
        elif path == '/api/docs/upload':
            filename = body.get('filename', '문서.txt')
            content = body.get('content', '').strip()
            if not content:
                return self.send_json({"error": "문서 내용이 비어 있습니다."}, 400)
            
            analysis = gemini.analyze_document_content(content)
            doc_id = db.add_technical_doc(
                filename=filename,
                category=analysis.get('category', 'SOP/매뉴얼'),
                summary=analysis.get('summary', ''),
                key_points=analysis.get('key_points', ''),
                full_content=content
            )
            return self.send_json({"success": True, "doc_id": doc_id, "analysis": analysis})

        # 기능 5: 기술 문서 기반 질의응답
        elif path == '/api/docs/qa':
            doc_id = body.get('doc_id')
            question = body.get('question', '').strip()
            if not doc_id or not question:
                return self.send_json({"error": "문서 ID와 질문이 필요합니다."}, 400)
            doc = db.get_technical_doc_by_id(doc_id)
            if not doc:
                return self.send_json({"error": "해당 문서를 찾을 수 없습니다."}, 404)
            answer = gemini.answer_doc_question(doc.get('full_content', ''), doc.get('filename', ''), question)
            return self.send_json({"answer": answer, "filename": doc.get('filename')})

        # 기능 5: RAG 기반 지식 질의응답
        elif path == '/api/rag/query':
            question = body.get('question', '').strip()
            if not question:
                return self.send_json({"error": "질문 내용을 입력해 주세요."}, 400)
            
            matched_items = db.search_rag_knowledge(question, limit=5)
            ai_answer = gemini.answer_rag_question(question, matched_items)
            return self.send_json({
                "answer": ai_answer,
                "sources": matched_items
            })

        # 기능 6: 통계 지표에 대한 AI 공학적 심층 해석
        elif path == '/api/anomalies/explain':
            stats = db.get_anomaly_statistics()
            explanation = gemini.explain_anomalies_and_patterns(stats)
            return self.send_json({"explanation": explanation, "stats": stats})

        # 기능 7: 미완료 업무 우선순위 재평가
        elif path == '/api/priority/evaluate':
            task_data = body.get('task')
            if not task_data:
                return self.send_json({"error": "업무 데이터가 없습니다."}, 400)
            p_eval = gemini.evaluate_task_priority(task_data)
            return self.send_json(p_eval)

        elif path == '/api/improvements':
            logs = db.get_work_logs(limit=40)
            return self.send_json({'improvements': gemini.generate_efficiency_improvements(logs)})

        # 기능 8: 전문 용어 보존 다국어 번역
        elif path == '/api/translate':
            text = body.get('text', '')
            target_lang = body.get('target_lang', 'English')
            if not text:
                return self.send_json({"error": "번역할 텍스트가 없습니다."}, 400)
            res = gemini.translate_handover_report(text, target_lang)
            return self.send_json(res)

        # 기능 9: Function Calling 기반 자연어 대화형 에이전트
        elif path == '/api/agent/command':
            cmd = body.get('command', '').strip()
            if not cmd:
                return self.send_json({"error": "명령을 입력해 주세요."}, 400)

            plan = gemini.process_agent_command(cmd)
            func_name = plan.get('function_name', '')
            params = plan.get('parameters', {})
            
            execution_result = None

            # 명령 매핑 실행
            if func_name == 'get_completed_tasks':
                execution_result = db.get_work_logs(status_filter='완료')
            elif func_name == 'get_pending_tasks':
                execution_result = db.get_work_logs(status_filter='미완료')
            elif func_name in ('search_device_history', 'search_logs'):
                dev_id = params.get('device_id') or params.get('query') or cmd
                execution_result = db.search_rag_knowledge(dev_id, limit=5)
            elif func_name == 'get_anomaly_statistics':
                execution_result = db.get_anomaly_statistics()
            elif func_name == 'trigger_handover_report':
                execution_result = '보고서 탭에서 교대 기간을 선택해 생성하세요.'

            return self.send_json({
                "plan": plan,
                "execution_result": execution_result
            })

        # API 키 연결 테스트
        elif path == '/api/settings/test':
            return self.send_json(gemini.test_gemini_connection())

        else:
            self.send_json({"error": "알 수 없는 API 경로입니다."}, 404)

def run():
    if HOST != '127.0.0.1' and (not EXPECTED_SIGNER or not PUBLIC_ORIGIN or not PUBLIC_ORIGIN.startswith('https://')):
        sys.exit('External binding requires ALB authentication and a configured HTTPS origin.')
    db.init_db()
    ThreadingTCPServer.allow_reuse_address = True
    server_address = (HOST, PORT)
    try:
        with ThreadingTCPServer(server_address, ShiftBridgeHandler) as httpd:
            print(f"============================================================")
            print(f"🌉 SHIFT BRIDGE - AWS DCO AI 인수인계 시스템 가동 완료")
            print(f"접속 주소: http://localhost:{PORT}")
            print(f"기본 탑재 모델: {gemini.get_active_model()}")
            print(f"============================================================")
            httpd.serve_forever()
    except OSError as e:
        if "Address already in use" in str(e):
            alt_port = PORT + 1
            print(f"[!] 포트 {PORT} 사용 중. 대체 포트 {alt_port}로 실행합니다...")
            with ThreadingTCPServer(('127.0.0.1', alt_port), ShiftBridgeHandler) as httpd:
                print(f"접속 주소: http://localhost:{alt_port}")
                httpd.serve_forever()
        else:
            raise e

if __name__ == '__main__':
    run()
