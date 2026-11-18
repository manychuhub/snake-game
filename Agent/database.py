#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHIFT BRIDGE - AWS DCO AI 업무 인수인계 시스템
[Database & Knowledge Storage Module]
- SQLite3 기반 Zero-dependency 데이터베이스
- FTS(Full-Text Search) 및 하이브리드 RAG 검색 지원
- 업무 기록, 보고서, 누락 질의, 기술 문서, 감사 이력 관리
"""
import os
import sqlite3
import json
import time
import datetime
from contextlib import contextmanager, closing
from pathlib import Path

DB_PATH = Path(os.getenv("SHIFT_BRIDGE_DB_PATH", Path(__file__).resolve().parent / "shift_bridge.db"))

@contextmanager
def get_connection():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn

def init_db():
    """데이터베이스 스키마 초기화 및 샘플 데이터 시딩"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. 정규 업무 기록 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS work_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text TEXT NOT NULL,
            execution_time TEXT,
            operator TEXT,
            device_id TEXT,
            ticket_no TEXT,
            incident_type TEXT,
            cause TEXT,
            action_taken TEXT,
            result TEXT,
            status TEXT DEFAULT '미완료',
            follow_up TEXT,
            remarks TEXT,
            audio_source TEXT,
            missing_alerts TEXT,
            priority_score INTEGER DEFAULT 50,
            priority_tier TEXT DEFAULT 'P3',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 2. 근무 종합 인수인계 보고서 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS handover_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_title TEXT NOT NULL,
            outgoing_shift TEXT,
            incoming_shift TEXT,
            author TEXT,
            status TEXT DEFAULT '검토대기',
            summary TEXT,
            completed_tasks TEXT,
            pending_tasks TEXT,
            critical_alerts TEXT,
            parts_awaiting TEXT,
            follow_up_tasks TEXT,
            carried_over_tasks TEXT,
            next_shift_actions TEXT,
            raw_markdown TEXT,
            approved_by TEXT,
            approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 3. 기술 문서 및 SOP 테이블 (RAG 지식 베이스)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS technical_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            category TEXT,
            summary TEXT,
            key_points TEXT,
            full_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 4. 누락 정보 질의 및 엔지니어 피드백 이력
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS missing_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_log_id INTEGER,
            question TEXT NOT NULL,
            missing_field TEXT,
            operator_reply TEXT,
            status TEXT DEFAULT '답변대기',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (work_log_id) REFERENCES work_logs (id)
        );
        """)

        # 5. 감사 추적(Audit Trail) 이력
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_trails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT,
            action TEXT NOT NULL,
            target TEXT,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 6. FTS(Full Text Search) 가상 테이블 생성 (RAG 고속 검색)
        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS work_logs_fts USING fts5(
            raw_text, device_id, ticket_no, incident_type, action_taken, follow_up,
            content='work_logs', content_rowid='id'
        );
        """)

        # FTS 트리거 등록 (동기화)
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_work_logs_ai AFTER INSERT ON work_logs BEGIN
            INSERT INTO work_logs_fts(rowid, raw_text, device_id, ticket_no, incident_type, action_taken, follow_up)
            VALUES (new.id, new.raw_text, new.device_id, new.ticket_no, new.incident_type, new.action_taken, new.follow_up);
        END;
        """)

        # 샘플 AWS DCO 현장 데이터 시딩
        cursor.execute("SELECT COUNT(*) FROM work_logs;")
        if cursor.fetchone()[0] == 0 and os.getenv("SHIFT_BRIDGE_SEED_DEMO", "1") == "1":
            seed_sample_data(cursor)

        conn.commit()
    print("[*] SHIFT BRIDGE Database Initialized Successfully.")

def seed_sample_data(cursor):
    """현업 AWS DCO 데이터센터 실제 시나리오 샘플 시딩"""
    sample_records = [
        (
            "02:40 Hall-A 랙 #R14의 EC2 호스트 서버 svr-kr-a14-03에서 DIMM 채널B2 다중 ECC 에러 발생. 티켓 #TT-49211 접수 후 해당 블레이드 오프라인 전환하고 여분 DDR5 64GB 모듈로 교체 장착함. POST 통과 및 메모리 진단 정상 확인 완료. 결함 부품은 RMA 랙에 보관함.",
            "02:40", "김인프라 (야간조)", "Hall-A R14 svr-kr-a14-03", "TT-49211", "HW장애 / 메모리(DIMM)",
            "DDR5 메모리 채널B2 하드웨어 결함", "블레이드 오프라인, 64GB DDR5 모듈 교체, POST 및 진단 완료",
            "정상 복구 및 온라인 재투입", "완료", "결함 부품 RMA 반납 승인", "장비 이상 없음", "", "[]", 65, "P2"
        ),
        (
            "04:15 Hall-C 광케이블 분배함(FDP #02)에서 코어 스위치 sw-core-c01 포트 48번 간 100G 링크 플래핑 현상. 현장 OTDR 측정 결과 감쇠율 7.8dB로 기준치(3.5dB) 초과 확인. MPO-LC 광패치코드 신규 포설 필요하나 현재 5m 케이블 재고 소진 상태. 주간조 자재창고 입고 즉시 교체 요망.",
            "04:15", "이당직 (야간조)", "Hall-C FDP#02 / sw-core-c01", "TT-49280", "네트워크 / 광선로",
            "광선로 감쇠 초과 (7.8dB)", "OTDR 측정, 링크 플래핑 현장 원인 규명", "케이블 교체 대기",
            "미완료", "주간조 5m MPO-LC 광패치 입고 즉시 재가설", "현재 포트 임시 Disable 조치", "",
            json.dumps(["부품 입고 대기 상태", "주간조 교체 작업 연계 필요"], ensure_ascii=False), 88, "P1"
        ),
        (
            "01:10 Hall-B 랙 #32 EC2 32번 서버 svr-kr-b32-01에서 PSU#1 전원 입력 전압 강하 알람 발생. 티켓 #TT-49195 접수 후 PDU 분기 차단기 점검 및 예비 전원선 체결 완료. 전원 정상 인입 확인됨.",
            "01:10", "김인프라 (야간조)", "Hall-B R32 32번서버 (svr-kr-b32-01)", "TT-49195", "시설 / 전원(PSU)",
            "PDU 분기 전원선 헐거움", "PDU 분기 차단기 전압 확인 및 전원선 재체결", "정상 전원 공급 확인",
            "완료", "차주 정기 열화상 점검 시 단자 온도 재확인", "부하율 정상 45%", "", "[]", 55, "P3"
        ),
        (
            "05:00 Hall-B 랙 #32 EC2 32번 서버 svr-kr-b32-01에서 동일 PSU#1 쿨링팬 RPM 급감 및 과열 경보 재발. 티켓 #TT-49330. PDU 전원은 정상이나 PSU 모듈 자체 팬 베어링 마모 결함 추정. 예비 1200W PSU 핫스왑 교체 요망.",
            "05:00", "이당직 (야간조)", "Hall-B R32 32번서버 (svr-kr-b32-01)", "TT-49330", "HW장애 / 파워(PSU)",
            "PSU#1 쿨링팬 베어링 마모 및 회전수 저하", "iDRAC 텔레메트리 팬 알람 확인 및 격리", "부품 교체 대기",
            "미완료", "주간조 자재실 1200W Hot-swap PSU 불출 후 현장 즉시 교체", "현재 PSU#2 싱글 라인으로 운용 중이므로 위험도 높음", "",
            json.dumps(["부품 교체 긴급 필요", "리던던시 상실 상태"], ensure_ascii=False), 92, "P1"
        ),
        (
            "05:30 전력실 UPS #3 유니트 배터리 내부 저항 이상 알람 경보 수신. 주간조 시설팀 합동 정기 실사 시 분기 차단기 전압 및 배터리 셀 정밀 점검 필요.",
            "05:30", "김인프라 (야간조)", "전력실 UPS-03", "TT-49302", "시설 / 전력(UPS)",
            "배터리 셀 내부 저항치 기준치 초과", "알람 1차 수신 및 로깅, 시설팀 유선 통보", "시설팀 합동 점검 대기",
            "추가점검", "오전 10시 시설팀 배터리 셀 교체 여부 협의", "현재 부하 42%로 안정 운용 중", "",
            json.dumps(["시설팀 공동 점검 절차 확인 요망"], ensure_ascii=False), 75, "P2"
        ),
        (
            "06:20 Hall-B 백본 스위치 BGP 피어링 세션 일시적 리셋. 원인 분석 결과 광트랜시버(QSFP28) 이상 온도 감지. 장비 샤시 쿨링 팬 동작 상태 양호 확인.",
            "06:20", "박네트워크 (야간조)", "Hall-B sw-bb-b02", "TT-49340", "네트워크 / BGP",
            "QSFP28 트랜시버 국소 과열", "트랜시버 텔레메트리 모니터링", "온도 정상 범위 복귀",
            "완료", "차주 정기 점검 시 트랜시버 모듈 예방 교체 검토", "트래픽 우회 없이 정상 소통", "",
            "[]", 45, "P3"
        )
    ]

    for r in sample_records:
        cursor.execute("""
        INSERT INTO work_logs (
            raw_text, execution_time, operator, device_id, ticket_no, incident_type,
            cause, action_taken, result, status, follow_up, remarks, audio_source,
            missing_alerts, priority_score, priority_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, r)

    # 샘플 기술 문서 (SOP / 장비 매뉴얼) 시딩
    sample_docs = [
        (
            "AWS_DCO_SOP_Optical_Fiber_Loss_Standard.pdf",
            "작업절차서(SOP)",
            "100G/400G 광선로 감쇠 허용치 및 패치코드 유지보수 기준 가이드",
            "- 100GBASE-LR4 단일모드 허용 감쇠치: 최대 6.3dB 이내 (권장 3.0dB 이하)\n- MPO/LC 커넥터 삽입 손실: 개당 0.35dB 이하\n- OTDR 측정 시 반사 손실(ORL) -35dB 이하 유지\n- 링크 플래핑 발생 시 1차 청소, 2차 패치코드 교체, 3차 트랜시버 점검 순으로 진행",
            "AWS 데이터센터 광케이블 현장 점검 표준 작업 절차서\n1. 목적: 고속 이더넷 인터페이스의 광 신호 품질 유지 및 링크 다운 방지\n2. 장비: Anritsu/Fluke OTDR 테스터, 광 파이버 스코프(400x), 원클릭 클리너\n3. 조치 순서: 포트 Disable -> 커넥터 단면 검사 -> 클리너 3회 세척 -> 재측정 -> 3.5dB 초과 시 케이블 전면 교체."
        ),
        (
            "Server_PSU_Redundant_Replacement_Manual.pdf",
            "장비매뉴얼",
            "엔터프라이즈 서버 파워서플라이(PSU) 핫스왑 교체 지침",
            "- 리던던트 이중화 구조에서 PSU 1개 고장 시 서버 다운 없이 무중단 교체 가능\n- 교체 전 반드시 iDRAC/BMC에서 고장 파워 위치(PSU#1 vs PSU#2) 확인 필수\n- 교체 후 녹색 LED 정상 점등 및 OS 텔레메트리 복구 여부 3분간 관찰",
            "서버 전원 모듈 핫스왑 교체 가이드\n주의: 교체 전 정상 가동 중인 반대편 PSU의 입력 전원 케이블이 견고하게 체결되어 있는지 손으로 흔들어 확인한다. 실수로 정상 PSU 케이블을 건드리면 서버 전체 정전 발생 위험."
        ),
        (
            "AWS_DCO_Memory_DIMM_Fault_Handling_Runbook.pdf",
            "장애대응런북",
            "DDR4/DDR5 서버 메모리 다중 비트 ECC 에러 격리 및 교체 절차",
            "- Correctable ECC 다발(시간당 10회 이상) 시 예방 교체 등록\n- Uncorrectable ECC 발생 시 즉시 커널 패닉 방지를 위해 인스턴스 실시간 마이그레이션 및 블레이드 오프라인 전환\n- DIMM 교체 후 최소 15분간 MemTest 진단 루프 완주 확인 후 호스트 복귀",
            "메모리 결함 대응 표준 지침\n1. SEL 로그 추출 및 에러 발생 슬롯(예: CPU1 DIMM B2) 확인\n2. 장비 파워 다운 및 정전기 방지(ESD) 스트랩 착용\n3. 규격 일치(동일 클럭/용량) 예비 모듈 장착\n4. 부품 시리얼 바코드 스캔 후 RMA 티켓 생성."
        )
    ]

    for d in sample_docs:
        cursor.execute("""
        INSERT INTO technical_documents (filename, category, summary, key_points, full_content)
        VALUES (?, ?, ?, ?, ?)
        """, d)

# ==============================================================================
# 데이터베이스 CRUD 및 비즈니스 쿼리 함수
# ==============================================================================

def add_work_log(log_data):
    """신규 업무 기록 추가 (FTS 동기화 자동)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO work_logs (
            raw_text, execution_time, operator, device_id, ticket_no, incident_type,
            cause, action_taken, result, status, follow_up, remarks, audio_source,
            missing_alerts, priority_score, priority_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_data.get('raw_text', ''),
            log_data.get('execution_time', '미확인'),
            log_data.get('operator', '미확인'),
            log_data.get('device_id', '미확인'),
            log_data.get('ticket_no', '미확인'),
            log_data.get('incident_type', '기타'),
            log_data.get('cause', '미확인'),
            log_data.get('action_taken', '미확인'),
            log_data.get('result', '미확인'),
            log_data.get('status', '미완료'),
            log_data.get('follow_up', '미확인'),
            log_data.get('remarks', '미확인'),
            log_data.get('audio_source', ''),
            json.dumps(log_data.get('missing_alerts', []), ensure_ascii=False),
            log_data.get('priority_score', 50),
            log_data.get('priority_tier', 'P3')
        ))
        conn.commit()
        log_id = cursor.lastrowid
        record_audit(log_data.get('operator', '시스템'), "ADD_LOG", f"ID #{log_id}", log_data.get('device_id', ''))
        return log_id

def get_work_logs(limit=100, status_filter=None):
    """업무 기록 목록 조회"""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM work_logs"
        params = []
        if status_filter:
            query += " WHERE status = ?"
            params.append(status_filter)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def get_shift_logs(start, end):
    """Include records entered during the shift and earlier work still open."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM work_logs WHERE created_at < ?
               AND (created_at >= ? OR status <> '완료')
               ORDER BY created_at DESC, id DESC LIMIT 51""", (end, start),
        )
        return [dict(row) for row in rows]


def get_work_log_by_id(log_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM work_logs WHERE id = ?", (log_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_work_log(log_id, update_data):
    """업무 기록 수정 및 보완"""
    with get_connection() as conn:
        cursor = conn.cursor()
        fields = []
        values = []
        for k, v in update_data.items():
            if k not in ('id', 'created_at'):
                fields.append(f"{k} = ?")
                values.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        values.append(log_id)
        cursor.execute(f"UPDATE work_logs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        record_audit("담당자", "UPDATE_LOG", f"ID #{log_id}", "내용 보완 업데이트")
        return True

def delete_work_log(log_id):
    """업무 기록 삭제"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM work_logs WHERE id = ?", (log_id,))
        cursor.execute("DELETE FROM work_logs_fts WHERE rowid = ?", (log_id,))
        conn.commit()
        record_audit("담당자", "DELETE_LOG", f"ID #{log_id}", "업무 기록 삭제")
        return True

# ==============================================================================
# RAG 검색 엔진 (FTS5 + 키워드/디바이스 매칭)
# ==============================================================================

def search_rag_knowledge(query_text, limit=5):
    """
    RAG 검색: FTS5 가상 테이블을 활용하여 질문과 연관된 과거 업무 기록 및 SOP 문서를 정밀 검색
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        results = []

        # 1. 과거 업무 기록 검색 (FTS5 또는 LIKE)
        clean_tokens = [w for w in "".join([c if c.isalnum() else " " for c in query_text]).split() if len(w) > 1]
        fts_query = " OR ".join(clean_tokens) if clean_tokens else query_text

        try:
            cursor.execute("""
            SELECT w.*, rank FROM work_logs w
            JOIN work_logs_fts f ON w.id = f.rowid
            WHERE work_logs_fts MATCH ?
            ORDER BY rank LIMIT ?
            """, (fts_query, limit))
            logs = cursor.fetchall()
            for l in logs:
                d = dict(l)
                d['source_type'] = 'WORK_LOG'
                results.append(d)
        except Exception:
            pass

        # 부족할 경우 일반 LIKE 매칭 폴백
        if len(results) < limit:
            cursor.execute("""
            SELECT * FROM work_logs 
            WHERE raw_text LIKE ? OR device_id LIKE ? OR ticket_no LIKE ? OR incident_type LIKE ? OR cause LIKE ?
            ORDER BY id DESC LIMIT ?
            """, (f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", limit))
            existing_ids = {r['id'] for r in results}
            for l in cursor.fetchall():
                d = dict(l)
                if d['id'] not in existing_ids:
                    d['source_type'] = 'WORK_LOG'
                    results.append(d)

        # 2. 기술 문서(SOP) 검색
        cursor.execute("""
        SELECT * FROM technical_documents
        WHERE summary LIKE ? OR key_points LIKE ? OR full_content LIKE ? OR filename LIKE ?
        LIMIT 3
        """, (f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", f"%{query_text}%"))
        for doc in cursor.fetchall():
            d = dict(doc)
            d['source_type'] = 'SOP_DOC'
            results.append(d)

        return results

# ==============================================================================
# 패턴 탐지 및 통계 계산 함수 (순수 프로그램 계산)
# ==============================================================================

def get_anomaly_statistics():
    """
    과거 누적 기록을 분석하여 통계 기반 6대 반복 문제 및 이상 징후 추출:
    1. 동일 장비 반복 장애 Top 5
    2. 동일 부품의 반복 교체 현황
    3. 동일 오류 코드의 반복 발생 현황
    4. 장기간 해결되지 않는 미완료 문제
    5. 특정 장애 유형의 발생 빈도 분포
    6. 반복적인 작업 실수 / 누락 패턴
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. 동일 장비의 반복 장애 Top 5
        cursor.execute("""
        SELECT device_id, COUNT(*) as count 
        FROM work_logs 
        WHERE device_id != '미확인' AND device_id != ''
        GROUP BY device_id 
        ORDER BY count DESC LIMIT 5;
        """)
        repeated_devices = [dict(r) for r in cursor.fetchall()]

        # 2. 장애 유형별 분포
        cursor.execute("""
        SELECT incident_type, COUNT(*) as count 
        FROM work_logs 
        GROUP BY incident_type 
        ORDER BY count DESC;
        """)
        incident_types = [dict(r) for r in cursor.fetchall()]

        # 3. 진행 상태별 카운트
        cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM work_logs 
        GROUP BY status;
        """)
        status_counts = {r['status']: r['count'] for r in cursor.fetchall()}

        # 4. 동일 부품 반복 교체 집계 (키워드 매칭 분석)
        parts_keywords = [("DDR5/DIMM 메모리", "%DIMM%"), ("MPO/LC 광패치코드", "%광%"), ("Hot-swap PSU 전원모듈", "%PSU%"), ("QSFP28 광트랜시버", "%트랜시버%"), ("UPS 배터리 셀", "%배터리%")]
        repeated_parts = []
        for part_name, pattern in parts_keywords:
            cursor.execute("SELECT COUNT(*) FROM work_logs WHERE raw_text LIKE ? OR action_taken LIKE ? OR cause LIKE ?", (pattern, pattern, pattern))
            c = cursor.fetchone()[0]
            if c > 0:
                repeated_parts.append({"part_name": part_name, "count": c})
        repeated_parts.sort(key=lambda x: x['count'], reverse=True)

        # 5. 동일 오류 코드 / 알람 반복 발생
        error_keywords = [("ECC Uncorrectable / Memory Error", "%ECC%"), ("Optical Attenuation High (7.8dB / 감쇠초과)", "%감쇠%"), ("BGP Session Flap / Peer Reset", "%BGP%"), ("Battery Internal Resistance High", "%저항%"), ("PSU Fan RPM Warning", "%팬%")]
        repeated_errors = []
        for err_name, pattern in error_keywords:
            cursor.execute("SELECT COUNT(*) FROM work_logs WHERE raw_text LIKE ? OR cause LIKE ?", (pattern, pattern))
            c = cursor.fetchone()[0]
            if c > 0:
                repeated_errors.append({"error_code": err_name, "count": c})
        repeated_errors.sort(key=lambda x: x['count'], reverse=True)

        # 6. 장기 미완료 업무 (체류 목록)
        cursor.execute("""
        SELECT id, device_id, ticket_no, incident_type, follow_up, priority_score, priority_tier, created_at 
        FROM work_logs 
        WHERE status IN ('미완료', '추가점검', '대기')
        ORDER BY priority_score DESC, id ASC LIMIT 6;
        """)
        unresolved_tasks = [dict(r) for r in cursor.fetchall()]

        # 7. 반복적인 작업 실수 / 누락 패턴 집계
        cursor.execute("SELECT COUNT(*) FROM work_logs WHERE ticket_no = '미확인';")
        missing_ticket_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM work_logs WHERE result = '미확인';")
        missing_result_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM work_logs WHERE device_id = '미확인';")
        missing_device_count = cursor.fetchone()[0]

        frequent_omissions = [
            {"issue": "작업 티켓 번호(TT-xxxxx) 미등록", "count": missing_ticket_count},
            {"issue": "부품 교체 후 정상 동작 검증 결과 누락", "count": missing_result_count},
            {"issue": "작업 대상 장비/랙 번호 불명확", "count": missing_device_count}
        ]

        total_logs = sum(status_counts.values()) if status_counts else 0

        return {
            "total_logs": total_logs,
            "status_counts": status_counts,
            "repeated_devices": repeated_devices,
            "incident_types": incident_types,
            "repeated_parts": repeated_parts,
            "repeated_errors": repeated_errors,
            "unresolved_tasks": unresolved_tasks,
            "frequent_omissions": frequent_omissions
        }

# ==============================================================================
# 인수인계 보고서 및 감사 이력
# ==============================================================================

def save_handover_report(report_data):
    """인수인계 보고서 저장 (검토 대기 상태)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO handover_reports (
            shift_title, outgoing_shift, incoming_shift, author, status,
            summary, completed_tasks, pending_tasks, critical_alerts,
            parts_awaiting, follow_up_tasks, carried_over_tasks, next_shift_actions,
            raw_markdown
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_data.get('shift_title', '정기 교대 인수인계 보고서'),
            report_data.get('outgoing_shift', '야간조'),
            report_data.get('incoming_shift', '주간조'),
            report_data.get('author', 'DCO 당직'),
            '검토대기',
            report_data.get('summary', ''),
            report_data.get('completed_tasks', ''),
            report_data.get('pending_tasks', ''),
            report_data.get('critical_alerts', ''),
            report_data.get('parts_awaiting', ''),
            report_data.get('follow_up_tasks', ''),
            report_data.get('carried_over_tasks', ''),
            report_data.get('next_shift_actions', ''),
            report_data.get('raw_markdown', '')
        ))
        conn.commit()
        report_id = cursor.lastrowid
        record_audit(report_data.get('author', '시스템'), "GENERATE_REPORT", f"보고서 #{report_id}", "인수인계 보고서 자동 생성")
        return report_id

def approve_handover_report(report_id, approver_name, edited_markdown=None):
    """인수인계 보고서 최종 검토 및 공식 승인"""
    with get_connection() as conn:
        cursor = conn.cursor()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if edited_markdown:
            cursor.execute("""
            UPDATE handover_reports 
            SET status = '최종승인', approved_by = ?, approved_at = ?, raw_markdown = ?
            WHERE id = ? AND status = '검토대기'
            """, (approver_name, now_str, edited_markdown, report_id))
        else:
            cursor.execute("""
            UPDATE handover_reports 
            SET status = '최종승인', approved_by = ?, approved_at = ?
            WHERE id = ? AND status = '검토대기'
            """, (approver_name, now_str, report_id))
        if not cursor.rowcount:
            return False
        cursor.execute(
            "INSERT INTO audit_trails (operator, action, target, detail) VALUES (?, ?, ?, ?)",
            (approver_name, "APPROVE_REPORT", f"보고서 #{report_id}", "교대 인수인계 최종 서명 완료"),
        )
        return True

def get_handover_reports(limit=10):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM handover_reports ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]

def record_audit(operator, action, target, detail):
    """감사 로그 저장"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO audit_trails (operator, action, target, detail)
            VALUES (?, ?, ?, ?)
            """, (operator, action, target, detail))
            conn.commit()
    except Exception:
        pass

def get_audit_trails(limit=50):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_trails ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]

# 기술 문서 추가/조회
def add_technical_doc(filename, category, summary, key_points, full_content):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO technical_documents (filename, category, summary, key_points, full_content)
        VALUES (?, ?, ?, ?, ?)
        """, (filename, category, summary, key_points, full_content))
        conn.commit()
        doc_id = cursor.lastrowid
        record_audit("시스템", "ADD_DOC", f"SOP #{doc_id}", filename)
        return doc_id

def get_technical_docs():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, filename, category, summary, key_points, created_at FROM technical_documents ORDER BY id DESC")
        return [dict(r) for r in cursor.fetchall()]

def get_technical_doc_by_id(doc_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM technical_documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

if __name__ == '__main__':
    init_db()
