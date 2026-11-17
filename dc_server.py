#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DC-OPS AI - WSL 기반 자율형 AI 엔지니어 백엔드
- 실제 Antigravity AI CLI (`agy`) 추론 엔진 직접 연동
- 엔지니어 인수인계 내용을 AI가 심층 분석하여 전문 대응 절차 수립
- 사용자 질문/진단 명령을 실제 AI가 답변 및 셸 작업 가이드 제공
"""
import os
import time
import json
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer

PORT = 9090
DATA_FILE = "/tmp/dc_handover_data.json"
AGY_BIN = "/home/ulsan/.local/bin/agy"

DEFAULT_ITEMS = [
    {
        "id": 1,
        "author": "이당직 (야간조)",
        "rack": "Hall-A #R07",
        "severity": "CRITICAL",
        "category": "HW장애",
        "time": "03:40 AM",
        "detail": "웹서버 4호기 파워서플라이(PSU #2) 장애 알람 발생. 현재 PSU #1으로 리던던트 구동 중이나 여분 파워 모듈 교체 작업 주간조 진행 필요.",
        "completed": False
    },
    {
        "id": 2,
        "author": "박인프라 (야간조)",
        "rack": "Hall-C 공조실",
        "severity": "WARNING",
        "category": "시설/환경",
        "time": "05:15 AM",
        "detail": "CRAC #3 습도 센서 일시적 68% 상승 후 현재 55%로 안정화. 시설팀 오전 10시 정기 실사 시 필터 점검 요청 권장.",
        "completed": False
    }
]

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_ITEMS)
        return DEFAULT_ITEMS
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_ITEMS

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ask_agy_llm(prompt_text, timeout_sec=25):
    """WSL 내 설치된 agy AI 엔진에 프롬프트를 전송하고 추론 결과를 반환"""
    try:
        env = os.environ.copy()
        env["HOME"] = "/home/ulsan"
        cmd = [AGY_BIN, "-p", prompt_text, "--print-timeout", f"{timeout_sec}s"]
        res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_sec + 5)
        out = res.stdout.strip()
        if out:
            return out
        return res.stderr.strip() or "AI 분석 응답을 수신하지 못했습니다."
    except Exception as e:
        return f"[AI 엔진 응답 대기 초과 또는 오류]: {e}"

def generate_real_ai_briefing(pending_items):
    """실제 AI LLM을 호출하여 데이터센터 교대 브리핑 리포트를 생성"""
    if not pending_items:
        return "🎉 [AI 브리핑]: 현재 미조치된 인수인계 및 장애 항목이 없습니다. 모든 인프라가 정상 운용 중입니다."

    items_text = ""
    for i, item in enumerate(pending_items[:5], 1):
        items_text += f"{i}. [{item.get('severity')}] 위치: {item.get('rack')} | 내용: {item.get('detail')}\n"

    prompt = (
        "너는 베테랑 데이터센터 수석 인프라 엔지니어 AI야. "
        "다음은 교대 근무조로부터 인계받은 미결 장애 및 작업 목록이다:\n\n"
        f"{items_text}\n"
        "다음 세 가지 형식으로 한국어로 아주 전문적이고 명확하게 5줄 내외로 요약 리포트를 작성해줘:\n"
        "1. 🚨 [최우선 주간조 착수 액션]\n"
        "2. ⚠️ [관찰 및 모니터링 포인트]\n"
        "3. 💡 [수석 엔지니어 현장 조언]"
    )
    return ask_agy_llm(prompt)

class AIAgentHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def address_string(self):
        return self.client_address[0]

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/items':
            data = load_data()
            content = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return

        super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len).decode('utf-8')
        
        try:
            req_data = json.loads(post_body) if post_body else {}
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        items = load_data()

        # 1. 실제 AI 심층 분석 요청 API
        if self.path == '/api/ai_analyze':
            item_detail = req_data.get('detail', '')
            rack = req_data.get('rack', '')
            prompt = (
                f"너는 데이터센터 하드웨어 엔지니어 어시스턴트 AI다. 다음 장애 건에 대해 엔지니어가 즉시 현장에서 실행해야 할 구체적이고 전문적인 1차/2차 점검 및 조치 절차 3가지를 번호 매겨 간결하게 제시해줘.\n"
                f"장소: {rack}\n내용: {item_detail}"
            )
            analysis = ask_agy_llm(prompt)
            res_content = json.dumps({"analysis": analysis}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(res_content)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(res_content)
            return

        # 2. 실제 AI 교대 브리핑 생성 요청 API
        if self.path == '/api/ai_briefing':
            pending = [i for i in items if not i.get('completed', False)]
            briefing = generate_real_ai_briefing(pending)
            res_content = json.dumps({"briefing": briefing}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(res_content)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(res_content)
            return

        # 3. 기본 인수인계 CRUD
        if self.path == '/api/add':
            items.insert(0, req_data)
            save_data(items)
        elif self.path == '/api/toggle':
            item_id = req_data.get('id')
            for item in items:
                if item.get('id') == item_id:
                    item['completed'] = not item.get('completed', False)
                    break
            save_data(items)
        elif self.path == '/api/delete':
            item_id = req_data.get('id')
            items = [item for item in items if item.get('id') != item_id]
            save_data(items)
        else:
            self.send_response(404)
            self.end_headers()
            return

        content = json.dumps(items, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(content)

def run_server():
    target_dir = '/mnt/c/Users/통신운용/Desktop/Agent'
    if os.path.exists(target_dir):
        os.chdir(target_dir)

    ThreadingTCPServer.allow_reuse_address = True
    with ThreadingTCPServer(('0.0.0.0', PORT), AIAgentHandler) as httpd:
        print(f"[*] DC-OPS AI Real LLM Agent Server running on port {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")

if __name__ == '__main__':
    run_server()
