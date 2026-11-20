"""Fixed, fictional records for the visitor dashboard."""

LOGS = (
    {
        'id': 1, 'execution_time': '02:40', 'operator': '예시 당직자',
        'device_id': 'DEMO-SRV-01', 'ticket_no': 'DEMO-001', 'incident_type': '전원 모듈',
        'cause': '전원 모듈 경보', 'action_taken': '예비 전원 모듈로 교체', 'result': '정상 복귀 확인',
        'status': '완료', 'follow_up': '다음 근무조에서 경보 재발 확인', 'remarks': '공개 체험용 기록',
        'raw_text': '02:40 예시 서버의 전원 모듈을 교체하고 정상 복귀를 확인했습니다. 다음 조는 경보 재발을 확인하세요.',
        'priority_tier': 'P3', 'priority_score': 45,
    },
    {
        'id': 2, 'execution_time': '05:15', 'operator': '예시 당직자',
        'device_id': 'DEMO-SW-02', 'ticket_no': 'DEMO-002', 'incident_type': '광 링크',
        'cause': '링크 불안정', 'action_taken': '예비 케이블 입고 요청', 'result': '입고 대기',
        'status': '미완료', 'follow_up': '예비 케이블 도착 시 교체 후 링크 상태 확인', 'remarks': '공개 체험용 기록',
        'raw_text': '05:15 예시 스위치 링크가 불안정해 예비 케이블 입고를 요청했습니다.',
        'priority_tier': 'P2', 'priority_score': 75,
    },
)

REPORTS = [{
    'id': 1, 'shift_title': '가상 교대 인수인계 보고서', 'status': '최종승인',
    'author': '예시 당직자', 'approved_by': '예시 검토자', 'outgoing_shift': '야간조', 'incoming_shift': '주간조',
    'raw_markdown': '## 교대 요약\n가상 업무 2건을 인계합니다.\n\n## 완료된 업무\n- DEMO-001 전원 모듈 교체 후 정상 복귀.\n\n## 미완료 업무\n- DEMO-002 예비 케이블 입고 대기.\n\n## 다음 교대 조치\n- 전원 경보 재발 및 케이블 입고 여부 확인.',
}]

DOCUMENTS = [{
    'id': 1, 'filename': '체험용_인수인계_체크리스트.md', 'category': 'SOP 예시',
    'summary': '교대 직전에 확인할 기록 항목을 담은 예시 문서입니다.',
    'key_points': '티켓 상태 확인\n미완료 업무와 다음 조 할 일 기록',
}]


def read(path, status=None):
    if path == '/demo/api/logs':
        return {'logs': [log for log in LOGS if not status or log['status'] == status]}
    if path == '/demo/api/reports':
        return {'reports': REPORTS}
    if path == '/demo/api/docs':
        return {'docs': DOCUMENTS}
    if path == '/demo/api/anomalies/stats':
        return {'total_logs': len(LOGS), 'status_counts': {'완료': 1, '미완료': 1},
                'incident_types': [{'incident_type': '전원 모듈', 'count': 1}, {'incident_type': '광 링크', 'count': 1}]}
    return None
