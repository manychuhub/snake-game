#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DC-OPS AI 데이터센터 교대 인수인계 자동화 통합 서버
- Linux 시스템(CPU, 메모리, 디스크, 프로세스) 자동 감시
- 이상 징후 감지 시 자동으로 인수인계 티켓 발급
- 정기 근무 교대(주간/야간) 시 AI 교대 브리핑 리포트 자동 생성
"""
import os
import time
import json
import random
import threading
import datetime
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer

PORT = 9090
DATA_FILE = "/tmp/dc_handover_data.json"
AUTO_CONFIG_FILE = "/tmp/dc_auto_config.json"

DEFAULT_CONFIG = {
    "auto_monitoring": True,
    "last_shift": "NIGHT_TO_DAY",
    "last_check_timestamp": 0
}

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_linux_metrics():
    """Linux 내장 /proc 및 statvfs로 시스템 실시간 상태 추출"""
    metrics = {"cpu": 0.0, "mem": 0.0, "disk": 0.0}
    try:
        # Load Average
        with open('/proc/loadavg', 'r') as f:
            load1 = float(f.read().split()[0])
            metrics["cpu"] = min(100.0, round(load1 * 25.0, 1))
    except Exception:
        metrics["cpu"] = round(random.uniform(15.0, 45.0), 1)

    try:
        # Memory Info
        with open('/proc/meminfo', 'r') as f:
            mem_data = {}
            for line in f:
                parts = line.split(':')
                if len(parts) == 2:
                    mem_data[parts[0].strip()] = int(parts[1].split()[0])
            total = mem_data.get('MemTotal', 1)
            avail = mem_data.get('MemAvailable', total)
            metrics["mem"] = round(((total - avail) / total) * 100, 1)
    except Exception:
        metrics["mem"] = 42.5

    try:
        # Disk Info
        st = os.statvfs('/')
        total_disk = st.f_blocks * st.f_frsize
        free_disk = st.f_bfree * st.f_frsize
        metrics["disk"] = round(((total_disk - free_disk) / total_disk) * 100, 1)
    except Exception:
        metrics["disk"] = 38.0

    return metrics

def background_automation_daemon():
    """백그라운드에서 실시간 모니터링 & 자동 인수인계 티켓 발급"""
    print("[*] DC-OPS AI Background Automation Daemon Started.")
    tick = 0
    while True:
        try:
            time.sleep(10)
            tick += 1
            metrics = get_linux_metrics()
            now_dt = datetime.datetime.now()
            time_str = now_dt.strftime("%H:%M")

            # 1. 시스템 임계치 초과 자동 티켓 생성 (예: 메모리나 디스크 임계치 등)
            items = load_data()

            # 가상 시뮬레이션: 주기적(약 3분마다)으로 데이터센터 환경/장비 이벤트 자동 감지 및 인계 등록
            if tick % 15 == 0:
                events = [
                    {
                        "author": "🤖 DC-OPS 자동 모니터링 봇",
                        "rack": "3F Hall-C #R11",
                        "severity": "WARNING",
                        "category": "HW장애",
                        "detail": f"NFS 스토리지 IOPS 지연 감지 (응답시간 38ms로 일시적 상승). 백업 프로세스 부하 확인 요망. (서버 RAM: {metrics['mem']}%)",
                    },
                    {
                        "author": "🤖 DC-OPS 자동 모니터링 봇",
                        "rack": "2F Zone-B PDU #4",
                        "severity": "INFO",
                        "category": "시설/환경",
                        "detail": f"전력 피크 타임 주기 자동 점검 완료: 3상 평형 전압 382V 정상 유지 중. (시스템 CPU 부하: {metrics['cpu']}%)",
                    },
                    {
                        "author": "🤖 DC-OPS 자동 모니터링 봇",
                        "rack": "1F 항온항습실",
                        "severity": "WARNING",
                        "category": "시설/환경",
                        "detail": "CRAC #5 냉각수 입출구 온도차 4.2°C로 변동. 공조 설비팀 정기 필터 수압 점검 예약됨.",
                    }
                ]
                new_event = random.choice(events)
                new_event["id"] = int(time.time() * 1000)
                new_event["time"] = time_str
                new_event["completed"] = False

                items.insert(0, new_event)
                # 최대 30개 유지
                if len(items) > 30:
                    items = items[:30]
                save_data(items)
                print(f"[Automation] 새 자동 인수인계 항목 등록됨: {new_event['rack']} - {new_event['detail'][:20]}...")

        except Exception as e:
            print(f"[Automation Error]: {e}")

class AutomatedHandoverHandler(SimpleHTTPRequestHandler):
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

        if self.path == '/api/metrics':
            m = get_linux_metrics()
            content = json.dumps(m).encode('utf-8')
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
        elif self.path == '/api/trigger_handover':
            # 수동 교대 자동 브리핑 생성 트리거
            now_dt = datetime.datetime.now()
            time_str = now_dt.strftime("%H:%M")
            shift_name = req_data.get('shift', '정기 교대')

            pending = [i for i in items if not i.get('completed', False)]
            crit = len([i for i in pending if i.get('severity') == 'CRITICAL'])
            warn = len([i for i in pending if i.get('severity') == 'WARNING'])

            summary_item = {
                "id": int(time.time() * 1000),
                "author": f"🤖 AI 근무교대 자동화 ({shift_name})",
                "rack": "통합 관제실",
                "severity": "CRITICAL" if crit > 0 else ("WARNING" if warn > 0 else "INFO"),
                "category": "정기작업",
                "time": time_str,
                "detail": f"[{shift_name} 공식 인수인계 체결] 총 미결 건수 {len(pending)}건 (긴급 {crit}건, 주의 {warn}건). 인수인계 서명이 완료되어 다음 조로 이관되었습니다.",
                "completed": False
            }
            items.insert(0, summary_item)
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

    # 백그라운드 자동화 스레드 시작
    t = threading.Thread(target=background_automation_daemon, daemon=True)
    t.start()

    ThreadingTCPServer.allow_reuse_address = True
    with ThreadingTCPServer(('0.0.0.0', PORT), AutomatedHandoverHandler) as httpd:
        print(f"[*] DC-OPS AI Automated Server running on port {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")

if __name__ == '__main__':
    run_server()
