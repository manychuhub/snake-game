"""Allowlisted DCO inventory, read-only diagnostics, and approved work requests."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryFile
from urllib.parse import urlsplit

from ai_workspace import redact
import database as db


NAVIGATE = 'navigate_rack_ports'
CHECK_LINK = 'check_switch_port_link'
OPEN_CONSOLE = 'open_bmc_console'
HDD_STOCK = 'query_hdd_stock'
HDD_REQUEST = 'request_hdd_release'
WIPE_REQUEST = 'register_disk_wipe'
READ_TOOLS = (NAVIGATE, CHECK_LINK, HDD_STOCK)
APPROVAL_TOOLS = (OPEN_CONSOLE, HDD_REQUEST, WIPE_REQUEST)
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}', re.ASCII)


class ToolUnavailable(Exception):
    pass


class TargetChanged(ToolUnavailable):
    pass


@dataclass(frozen=True)
class Inventory:
    racks: dict
    servers: dict
    hdd: dict

    @classmethod
    def load(cls):
        try:
            data = json.loads(os.getenv('SHIFT_BRIDGE_DCO_INVENTORY_JSON', '{}'))
            sections = tuple(data.get(key, {}) for key in ('racks', 'servers', 'hdd'))
            if all(isinstance(section, dict) for section in sections):
                return cls(*sections)
        except (ValueError, AttributeError, RecursionError):
            pass
        raise ToolUnavailable('DCO 장비·재고 설정을 확인하세요.')

    def rack_switches(self, rack_id):
        rack = self.racks.get(rack_id)
        switches = rack.get('switches') if isinstance(rack, dict) else None
        if not isinstance(switches, dict):
            return {}
        return {key: values for key, values in switches.items()
                if identifier(key) and isinstance(values, list) and all(identifier(value) for value in values)}

    def has_rack(self, rack_id):
        return identifier(rack_id) and isinstance(self.racks.get(rack_id), dict)

    def server(self, server_id):
        server = self.servers.get(server_id)
        if isinstance(server, dict) and self.has_rack(server.get('rackId')):
            return server
        return None

    def stock(self):
        return {sku: quantity for sku, quantity in self.hdd.items()
                if identifier(sku) and type(quantity) is int and 0 <= quantity <= 10**9}


def identifier(value):
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None and redact(value) == value


def permitted(member):
    return bool(member['admin']) and db.workspace_id.get() == 0


def mentioned(value, message):
    return bool(re.search(rf'(?<![\w./:-]){re.escape(value)}(?![\w./:-])', message, re.IGNORECASE | re.ASCII))


def selected(plan, context, message, key):
    value = plan.get(key)
    if value is None:
        value = context.get(key)
    if value is None:
        return None
    if not identifier(value) or (value != context.get(key) and not mentioned(value, message)):
        raise ToolUnavailable('도구의 대상 식별자를 메시지나 현재 화면에서 확인해 주세요.')
    return value


def rack_plan(tool, inventory, values):
    rack_id, switch_id, port_id = (values[key] for key in ('rackId', 'switchId', 'portId'))
    if rack_id is None and switch_id:
        matches = [key for key in inventory.racks if identifier(key) and switch_id in inventory.rack_switches(key)]
        rack_id = matches[0] if len(matches) == 1 else None
    if not inventory.has_rack(rack_id):
        raise ToolUnavailable('등록된 랙 ID를 입력하세요. 스위치 번호가 여러 랙에 있으면 랙도 지정하세요.')
    switches = inventory.rack_switches(rack_id)
    if switch_id is None and port_id is not None and len(switches) == 1:
        switch_id = next(iter(switches))
    if (switch_id is not None and switch_id not in switches) or (
        port_id is not None and port_id not in switches.get(switch_id, ())
    ):
        raise ToolUnavailable('해당 랙에 등록된 스위치와 포트를 지정하세요.')
    if tool == CHECK_LINK and switch_id is None:
        raise ToolUnavailable('링크 상태를 확인할 스위치를 지정하세요.')
    return {'rackId': rack_id, 'switchId': switch_id, 'portId': port_id}


def listed_serials(server):
    serials = server.get('serialNumbers', ())
    return serials if isinstance(serials, list) else ()


def asset_target(inventory, values, *, require_serial=False, require_server=False):
    rack_id, server_id, serial = (values.get(key) for key in ('rackId', 'serverId', 'serialNumber'))
    if require_serial and not serial:
        raise ToolUnavailable('등록할 디스크의 시리얼 번호를 지정하세요.')
    if serial and not server_id:
        matches = [key for key in inventory.servers if identifier(key)
                   and (server := inventory.server(key)) and serial in listed_serials(server)
                   and (rack_id is None or server['rackId'] == rack_id)]
        if len(matches) != 1:
            raise ToolUnavailable('시리얼에 연결된 서버를 한 대로 특정할 수 없습니다.')
        server_id = matches[0]
    if require_server and not server_id:
        raise ToolUnavailable('콘솔을 열 등록된 서버 ID를 지정하세요.')
    if server_id:
        server = inventory.server(server_id)
        if (server is None or (rack_id and rack_id != server['rackId'])
                or (serial and serial not in listed_serials(server))):
            raise ToolUnavailable('등록된 랙·서버·시리얼의 연결을 확인하세요.')
        rack_id = server['rackId']
    if not inventory.has_rack(rack_id):
        raise ToolUnavailable('작업 대상 랙 또는 서버를 지정하세요.')
    return {key: value for key, value in
            (('rackId', rack_id), ('serverId', server_id), ('serialNumber', serial)) if value is not None}


def console_url(inventory, target):
    server = inventory.server(target['serverId'])
    url = server.get('consoleUrl') if server else None
    if isinstance(url, str) and url.isascii() and not re.search(r'[\x00-\x20\x7f\\?#]', url):
        try:
            parsed = urlsplit(url)
            if (parsed.scheme == 'https' and parsed.hostname and '%' not in parsed.netloc and parsed.username is None
                    and parsed.password is None and (parsed.port is None or parsed.port > 0)):
                return url
        except ValueError:
            pass
    raise ToolUnavailable('서버의 콘솔 연결 설정을 확인하세요.')


def console_fingerprint(inventory, target):
    return hashlib.sha256(console_url(inventory, target).encode()).hexdigest()


def plan(tool, model, context, message, inventory):
    if tool in (NAVIGATE, CHECK_LINK):
        values = {key: selected(model, context, message, key) for key in ('rackId', 'switchId', 'portId')}
        return rack_plan(tool, inventory, values)
    if tool in (HDD_REQUEST, HDD_STOCK):
        sku = selected(model, context, message, 'sku')
        if sku is not None and sku not in inventory.stock():
            raise ToolUnavailable('설정된 교체용 HDD 품목 코드를 확인하세요.')
        if tool == HDD_STOCK:
            return {'sku': sku}
        if sku is None:
            raise ToolUnavailable('반출할 HDD 품목 코드를 지정하세요.')
        quantity = model.get('quantity', 1)
        if type(quantity) is not int or not 1 <= quantity <= 100 or (
            quantity != 1 and not mentioned(str(quantity), message)
        ):
            raise ToolUnavailable('반출 수량을 1~100 사이의 숫자로 지정하세요.')
    values = {key: selected(model, context, message, key) for key in ('rackId', 'serverId', 'serialNumber')}
    target = asset_target(inventory, values, require_serial=tool == WIPE_REQUEST, require_server=tool == OPEN_CONSOLE)
    ticket = selected(model, context, message, 'ticketId')
    if ticket:
        target['ticketId'] = ticket
    if tool == OPEN_CONSOLE:
        return {'target': target, 'console': console_fingerprint(inventory, target)}
    if tool == HDD_REQUEST:
        return {'target': target, 'sku': sku, 'quantity': quantity}
    return {'target': target}


def link_status(values, ports):
    configured = os.getenv('SHIFT_BRIDGE_DCO_PORT_SCRIPT')
    script = Path(configured) if configured else None
    if not script or not script.is_absolute() or not script.is_file():
        raise ToolUnavailable('링크 상태 점검 스크립트가 설정되어 있지 않습니다.')
    port_id = values['portId']
    args = [sys.executable, '-I', str(script), values['rackId'], values['switchId'], port_id or '--all']
    child_env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ}
    try:
        with TemporaryFile() as output:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                    env=child_env, cwd=script.parent, timeout=8, check=False)
            if result.returncode == 0:
                output.seek(0)
                raw = output.read(4097)
                if len(raw) <= 4096:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        allowed = ('up', 'down', 'unknown')
                        if port_id is not None and parsed.get('link') in allowed:
                            return {'link': parsed['link']}
                        reported = parsed.get('ports')
                        if port_id is None and isinstance(reported, dict):
                            return {'ports': [
                                {'portId': port, 'link': reported[port] if reported.get(port) in allowed else 'unknown'}
                                for port in ports
                            ]}
    except (OSError, ValueError, subprocess.TimeoutExpired, RecursionError):
        pass
    raise ToolUnavailable('링크 상태를 확인하지 못했습니다. 점검 스크립트를 확인하세요.')


def stock_rows(conn, inventory, sku=None):
    reserved = {row['item_id']: row['quantity'] for row in conn.execute(
        "SELECT item_id, SUM(quantity) AS quantity FROM dco_work_requests WHERE kind = ? GROUP BY item_id",
        (HDD_REQUEST,))}
    return [{'sku': item, 'available': max(0, quantity - reserved.get(item, 0))}
            for item, quantity in sorted(inventory.stock().items()) if sku is None or item == sku]


def describe(conn, tool, payload, inventory):
    target = payload['target']
    if tool == OPEN_CONSOLE:
        return target['serverId'], {'console': 'BMC/IPMI 콘솔 접근 링크 발급'}
    if tool == HDD_REQUEST:
        sku, quantity = payload['sku'], payload['quantity']
        available = stock_rows(conn, inventory, sku)[0]['available']
        if quantity > available:
            raise ToolUnavailable(f'{sku} 반출 가능 수량은 {available}개입니다.')
        target_id = target.get('serialNumber') or target.get('serverId') or target['rackId']
        return target_id, {'sku': sku, 'quantity': quantity, 'request': '반출 요청서 등록 및 재고 예약'}
    return target['serialNumber'], {'wipe': '작업 등록', 'artifacts': ['폐기 라벨 초안', '증적 리포트 초안']}


def save_request(conn, request_id, tool, item_id, quantity, details):
    conn.execute('INSERT INTO dco_work_requests (id, kind, item_id, quantity, details) VALUES (?, ?, ?, ?, ?)',
                 (request_id, tool, item_id, quantity, json.dumps(details, ensure_ascii=False)))


def execute(conn, tool, request_id, payload, requester):
    inventory = Inventory.load()
    target = payload['target']
    resolved = asset_target(inventory, target, require_serial=tool == WIPE_REQUEST, require_server=tool == OPEN_CONSOLE)
    if any(resolved.get(key) != target.get(key) for key in ('rackId', 'serverId', 'serialNumber')):
        raise TargetChanged('작업 대상 장비 정보가 바뀌었습니다. 새 요청을 보내 주세요.')
    if tool == OPEN_CONSOLE:
        if console_fingerprint(inventory, target) != payload['console']:
            raise TargetChanged('콘솔 연결 설정이 바뀌었습니다. 새 요청을 보내 주세요.')
        return f"BMC/IPMI 콘솔을 열 수 있습니다.\n/api/ai/console/{request_id}"
    details = {**payload, 'requestedBy': requester,
               'requestedAt': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if tool == HDD_REQUEST:
        if db.postgres_enabled():
            conn.execute('SELECT pg_advisory_xact_lock(1098792721)')
        sku, quantity = payload['sku'], payload['quantity']
        stock = stock_rows(conn, inventory, sku)
        if not stock or stock[0]['available'] < quantity:
            raise TargetChanged('반출 가능 수량이 변경되었습니다. 재고를 다시 확인하세요.')
        save_request(conn, request_id, tool, sku, quantity, details)
        destination = target.get('serverId') or target['rackId']
        return f'반출 요청서 #{request_id}을 등록했습니다. {destination}용 {sku} {quantity}개를 예약했습니다.'

    serial = target['serialNumber']
    if db.postgres_enabled():
        conn.execute('SELECT pg_advisory_xact_lock(1098792722)')
    if conn.execute('SELECT id FROM dco_work_requests WHERE kind = ? AND item_id = ?', (tool, serial)).fetchone():
        raise TargetChanged('이 시리얼의 와이핑 작업이 이미 등록되어 있습니다.')
    label = f"폐기 라벨 초안 | {serial} | 랙 {target['rackId']} | 서버 {target['serverId']} | 와이핑 대기"
    report = (f"증적 리포트 초안 | 작업 #{request_id} | 시리얼 {serial}\n"
              "작업 시각: 미입력\n작업자·검증자: 미입력\n와이핑 결과: 미확인\n검증 증적: 미첨부")
    save_request(conn, request_id, tool, serial, 0, {**details, 'labelDraft': label, 'evidenceDraft': report})
    return f'와이핑 작업을 등록했습니다.\n{label}\n{report}'
