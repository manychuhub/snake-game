"""Data and deterministic operations for the DCO workspace assistant."""

from datetime import datetime, timezone
import json
import os
import re
from uuid import NAMESPACE_OID, uuid5

import database as db


IDENTIFIER = r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}'
DEVICE_TAGS = {
    'rackId': ('rack|랙', rf'RACK-{IDENTIFIER}|R\d+(?![\w-])'),
    'serverId': ('server|서버', rf'(?:SRV|SVR)-{IDENTIFIER}'),
    'serialNumber': ('sn|serial|시리얼', rf'SN-{IDENTIFIER}'),
}
HARDWARE = re.compile(r'HDD|SSD|NVMe|RAM|DIMM|PSU|디스크|메모리|전원|파워|하드웨어', re.I)
NIGHT_TIME = re.compile(r'(?<!\d)(2[0-3]|[01]?\d):[0-5]\d\b')
MEDIA_KIND = '저장 매체 삭제'
VERIFIED = '삭제 검증 완료'
DISPOSAL_STATUS = '폐기 대기'
NOTIFY_COMMAND = 'notify_replacement_owners'

SECRET_PATTERNS = (
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', re.S),
    re.compile(r'(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis(?:s)?)://[^\s<>"\']+', re.I),
    re.compile(r'https?://[^\s/@]+:[^\s/@]+@[^\s<>"\']+', re.I),
    re.compile(r'\b(?:(?:Bearer|Basic)\s+[\w.+/=-]+|AIza[\w-]{35}|gh[pousr]_[\w]{30,}|github_pat_[\w]{30,}|(?:AKIA|ASIA)[A-Z0-9]{16}|sk-[\w-]{20,})(?=$|[^\w=])', re.I),
    re.compile(r'\b[\w-]*?(?:password|passwd|pwd|secret|api[_ -]?key|token|credential|authorization|dsn|database[_ -]?url|[\w-]+key)["\']?\s*[:=]\s*(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;}]+)|(?:비밀번호|토큰|API\s*키)\s*[:=]\s*\S+', re.I),
)


def redact(value):
    for name, secret in os.environ.items():
        if len(secret) >= 8 and re.search(r'KEY|TOKEN|PASSWORD|DATABASE_URL|CREDENTIAL|SECRET|DSN', name, re.I):
            value = value.replace(secret, '[가림]')
    for pattern in SECRET_PATTERNS:
        value = pattern.sub('[가림]', value)
    return value


def redact_source(item):
    return {key: redact(value) if isinstance(value, str) else value for key, value in item.items()}


def device_target(device):
    device = device or ''
    target = {}
    for key, (tag, pattern) in DEVICE_TAGS.items():
        match = re.search(rf'(?<![\w-])(?:{tag})\s*[:=]\s*({IDENTIFIER})', device, re.I)
        if not match:
            match = re.search(rf'(?<![\w-])({pattern})', device, re.I)
        if match:
            target[key] = match[1]
    if not target and re.fullmatch(IDENTIFIER, device.strip()) and device.strip() != '미확인':
        target['serverId'] = device.strip()
    return target


def row_target(row):
    target = device_target(row['device_id'])
    if row['ticket_no'] and row['ticket_no'] not in ('미확인', '-'):
        target['ticketId'] = row['ticket_no']
    return {key: value for key, value in target.items() if redact(value) == value}


def matching_serial(conn, serial, lock_clause=''):
    rows = conn.execute("""SELECT id, device_id, ticket_no, status, result, execution_time, operator, incident_type
        FROM work_logs WHERE incident_type = ? AND LOWER(device_id) LIKE LOWER(?) ORDER BY id DESC""" + lock_clause,
                        (MEDIA_KIND, f'%{serial}%')).fetchall()
    return [row for row in rows if media_serial(row).casefold() == serial.casefold()]


def media_serial(row):
    device = (row['device_id'] or '').strip()
    tagged = device_target(device).get('serialNumber')
    if tagged:
        return tagged
    return device if re.fullmatch(IDENTIFIER, device) else ''


def verified_media(row):
    return row['result'] == VERIFIED and row['status'] in ('완료', DISPOSAL_STATUS)


def media_report(row, serial):
    return '\n'.join((
        '저장 매체 폐기 증적 초안',
        f'시리얼 번호  {serial}',
        f'삭제 기록  #{row["id"]} / {row["ticket_no"] or "미기재"}',
        f'삭제 검증  {row["result"] or "미기재"}',
        f'기록 시각  {row["execution_time"] or "미기재"}',
        f'기록 담당자  {row["operator"] or "미기재"}',
        f'현재 상태  {row["status"] or "미기재"}',
        '폐기 일시, 입회자, 인수증 번호 및 첨부 증적  작성 시 확인',
    ))


def filter_logs(logs, name):
    if name == 'open_replacements':
        return [row for row in logs if row['status'] in ('미완료', '추가점검', '대기')
                and HARDWARE.search(f'{row["incident_type"]} {row["device_id"]} {row["action_taken"]} {row["follow_up"]} {row["raw_text"]}')
                and re.search(r'교체|replace|replacement|swap',
                              f'{row["action_taken"]} {row["follow_up"]} {row["raw_text"]}', re.I)]
    if name == 'night_incidents':
        return [row for row in logs if row_target(row).get('ticketId')
                and (match := NIGHT_TIME.search(row['execution_time'] or ''))
                and (int(match[1]) >= 20 or int(match[1]) < 8)]
    return []


def notify_replacement_owners(member):
    logs = filter_logs(db.get_work_logs(), 'open_replacements')
    if not logs:
        return {'type': 'answer', 'reply': '담당자에게 알릴 미완료 하드웨어 교체 기록이 없습니다.'}
    timestamp = datetime.now(timezone.utc)
    now = timestamp.isoformat(timespec='seconds')
    window = int(timestamp.timestamp()) // 900
    sent, skipped = 0, 0
    with db.get_connection(db.DB_PATH, account_id=member['id']) as conn:
        delivered = set()
        for row in logs:
            ticket = row_target(row).get('ticketId')
            username = (row['operator'] or '').strip().lower()
            if not ticket or not re.fullmatch(IDENTIFIER, ticket):
                skipped += 1
                continue
            recipient = conn.execute('SELECT id FROM web_users WHERE username = ? AND retired = 0',
                                     (username,)).fetchone()
            if recipient is None:
                skipped += 1
                continue
            key = (recipient['id'], ticket.casefold())
            if key in delivered:
                continue
            delivered.add(key)
            identifier = uuid5(NAMESPACE_OID, f'{member["id"]}/{recipient["id"]}/{ticket.casefold()}/{window}').hex
            created = conn.execute("""INSERT INTO ai_notifications
                (id, sender_id, recipient_id, sender, ticket_no, created_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                                   (identifier, member['id'], recipient['id'], member['username'], ticket, now))
            sent += created.rowcount
    if sent:
        reply = f'담당자 작업 알림함에 교체 확인 요청 {sent}건을 등록했습니다.'
    elif delivered:
        reply = '최근에 같은 티켓의 교체 확인 알림을 등록했습니다.'
    else:
        reply = '알림을 등록할 수 있는 담당자 계정이 없습니다.'
    if skipped:
        reply += f' 티켓 또는 담당자 계정이 확인되지 않은 기록은 {skipped}건입니다.'
    if not sent:
        return {'type': 'answer', 'reply': reply}
    return {'type': 'action_executed', 'reply': reply, 'action': {'name': NOTIFY_COMMAND},
            'auditLog': {'timestamp': now, 'actor': member['username'], 'command': NOTIFY_COMMAND,
                         'result': 'executed'}}


def activity(member, audit_commands):
    placeholders = ', '.join('?' for _ in audit_commands)
    with db.get_connection() as conn:
        rows = conn.execute(f"""SELECT operator, action, target, detail, created_at FROM audit_trails
            WHERE action IN ({placeholders}) ORDER BY id DESC LIMIT 50""", audit_commands).fetchall()
    events = []
    for row in rows:
        try:
            detail = json.loads(row['detail'] or '{}')
        except ValueError:
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        stamp = str(row['created_at']).replace(' ', 'T')
        if not re.search(r'(?:Z|[+-]\d\d(?::?\d\d)?)$', stamp):
            stamp += 'Z'
        events.append(redact_source({'timestamp': stamp, 'actor': row['operator'], 'command': row['action'],
                                     'targetId': detail.get('serialNumber') or (row['target'] or '').removeprefix('ID #'),
                                     'result': detail.get('result', '')}))
    with db.get_connection(db.DB_PATH, account_id=member['id']) as conn:
        notifications = conn.execute("""SELECT sender, sender_id, recipient_id, ticket_no, created_at
            FROM ai_notifications WHERE sender_id = ? OR recipient_id = ?
            ORDER BY created_at DESC, id DESC LIMIT 100""", (member['id'], member['id'])).fetchall()
    inbox = []
    for row in notifications:
        if row['sender_id'] == member['id']:
            events.append(redact_source({'timestamp': row['created_at'], 'actor': row['sender'],
                                         'command': NOTIFY_COMMAND, 'targetId': row['ticket_no'], 'result': 'executed'}))
        if row['recipient_id'] == member['id']:
            inbox.append(redact_source({'timestamp': row['created_at'], 'sender': row['sender'],
                                        'ticketId': row['ticket_no']}))
    events.sort(key=lambda event: event['timestamp'], reverse=True)
    return {'auditLogs': events[:50], 'notifications': inbox[:50]}
