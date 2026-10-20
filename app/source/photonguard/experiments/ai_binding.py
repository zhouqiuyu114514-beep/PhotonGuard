"""Portable, loopback-only BYOK connection. Credentials never enter persistence.

The durable quota counts dispatched attempts, including ambiguous failures. It is
a request/token bound, not a monetary estimate or a provider billing statement.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import ssl
import threading
import time
import uuid
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from ..backend import _NoRedirects, _strict_json
from ..workflow import WorkflowError, atomic_json
from ..workflow_model import wire

MODEL = 'deepseek-flash'
API = 'https://api.deepseek.com'
TOKEN_BOUND = wire.INPUT_BOUND + wire.OUTPUT_BOUND


def account_check(key):
    """Only official read-only endpoints; no generation, retries or proxy routing."""
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirects())
    values = []
    for path in ('/models', '/user/balance'):
        url = API + path
        request = Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}, method='GET')
        try:
            started = time.monotonic()
            with opener.open(request, timeout=12) as response:
                if response.geturl() != url or response.status != 200:
                    raise WorkflowError('连接验证未通过；拒绝跳转或异常响应。', 502)
                raw = bytearray()
                while len(raw) <= 65536:
                    if time.monotonic() - started > 12:
                        raise TimeoutError()
                    chunk = response.read1(min(8192, 65537 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if len(raw) > 65536:
                    raise ValueError()
                values.append(_strict_json(raw.decode('utf-8')))
        except HTTPError as exc:
            code = exc.code
            exc.close()
            message = {401: 'API key 无效或已撤销，请检查后重新填写。',
                       402: 'DeepSeek 账户余额不足，请在官方平台处理。',
                       429: 'DeepSeek 暂时限流，请稍后手动验证。'}.get(code, 'DeepSeek 未接受验证请求，请稍后手动重试。')
            raise WorkflowError(message, 422) from None
        except WorkflowError:
            raise
        except Exception:
            # Never serialize provider error text, headers, key or raw body.
            raise WorkflowError('无法连接 DeepSeek；请检查网络后手动重试。未发送生成请求。', 502) from None
    models, balance = values
    if (not isinstance(models, dict) or not isinstance(models.get('data'), list) or
            not any(isinstance(m, dict) and m.get('id') == MODEL for m in models['data'])):
        raise WorkflowError('账户未提供工作台所需的 deepseek-flash 模型。', 422)
    if not isinstance(balance, dict) or balance.get('is_available') is not True:
        raise WorkflowError('账户暂不可调用，请在 DeepSeek 官方平台核对余额与账户状态。', 422)


class RequestQuota:
    def __init__(self, owner):
        self.owner = owner
        self.lock = threading.RLock()
        self.authorization = SimpleNamespace(model=MODEL)
        self.state = self.read() if self.path.exists() else {
            'version': 1, 'managed': False, 'limit': 20, 'attempts': 0,
            'pending': None, 'halted': False, 'unknown_hashes': [],
            'settled_tokens': 0, 'held_tokens': 0}

    @property
    def path(self):
        return self.owner.safe('ai-binding', 'quota.json')

    def read(self):
        value = _strict_json(self.path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('version') != 1 or
                any(type(value.get(k)) is not int or value[k] < 0 for k in
                    ('limit', 'attempts', 'settled_tokens', 'held_tokens')) or
                not 1 <= value['limit'] <= 100 or value['attempts'] > value['limit'] or
                type(value.get('managed')) is not bool or type(value.get('halted')) is not bool or
                not isinstance(value.get('unknown_hashes'), list) or
                any(not isinstance(h, str) or not re.fullmatch('[a-f0-9]{64}', h) for h in value['unknown_hashes']) or
                (value.get('pending') is not None and
                 (not isinstance(value['pending'], dict) or set(value['pending']) != {'id', 'sha256'} or
                  not re.fullmatch('[a-f0-9]{32}', str(value['pending']['id'])) or
                  not re.fullmatch('[a-f0-9]{64}', str(value['pending']['sha256']))))):
            raise WorkflowError('AI 请求额度记录无效；请保留资料并检查本地记录。', 422)
        return value

    def write(self):
        self.owner.safe('ai-binding').mkdir(exist_ok=True)
        atomic_json(self.path, self.state)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def reserve_worst(self, live, require_existing=True):
        with self.lock:
            s = self.state
            if s['halted'] or s['pending'] or s['attempts'] >= s['limit']:
                raise WorkflowError('AI 已暂停或请求次数已用完，请打开连接设置核对。', 409)
            if self.request_hash in s['unknown_hashes']:
                raise WorkflowError('上次相同请求的扣费状态不明，禁止原样重发；请先核对已有记录。', 409)
            s['attempts'] += 1
            s['pending'] = {'id': uuid.uuid4().hex, 'sha256': self.request_hash}
            self.write()
            return self.snapshot()

    def estimated_cny(self, usage):
        return None

    def halt(self):
        with self.lock:
            self.state['halted'] = True
            self.write()

    def settle_usage(self, reservation_id, usage):
        with self.lock:
            s = self.state
            if (not s['pending'] or s['pending']['id'] != reservation_id or
                    usage['prompt_tokens'] > wire.INPUT_BOUND or usage['completion_tokens'] > wire.OUTPUT_BOUND):
                raise ValueError('Usage exceeds reservation')
            s['settled_tokens'] += usage['total_tokens']
            s['pending'] = None
            self.write()
            return self.snapshot()

    def configure(self, limit, resume):
        with self.lock:
            s = self.state
            if limit <= s['attempts']:
                raise WorkflowError('累计请求上限必须大于已经发送的次数。', 422)
            if s['halted'] or s['pending']:
                if resume is not True:
                    raise WorkflowError('上次请求未能完整确认；核对后勾选保留该次额度并继续。', 409)
                if s['pending']:
                    s['unknown_hashes'].append(s['pending']['sha256'])
                    s['held_tokens'] += TOKEN_BOUND
                s.update(pending=None, halted=False)
            s.update(managed=True, limit=limit)
            self.write()


class BoundClient:
    def __init__(self, manager, key):
        self.manager = manager
        self._key = key
        self.ledger = manager.quota

    def preflight(self, require_key=True):
        s = self.ledger.snapshot()
        if self.manager.client is not self or not self._key:
            raise WorkflowError('AI 已断开，请重新连接自己的 API key。', 409)
        if s['halted'] or s['pending'] or s['attempts'] >= s['limit']:
            raise WorkflowError('AI 已暂停或达到请求上限，请打开连接设置核对。', 409)

    def status(self):
        return self.manager.status()

    def complete(self, ident, payload):
        if not self.manager.operation.acquire(blocking=False):
            raise WorkflowError('AI 请求正在处理，请等待后再操作连接。', 409)
        try:
            self.preflight()
            if not isinstance(ident, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', ident):
                raise WorkflowError('AI 请求编号无效。')
            raw = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
            self.ledger.request_hash = hashlib.sha256(raw).hexdigest()
            result = wire.complete(payload, self._key, self.ledger, require_existing_ledger=True)
            audit = result['audit']
            # Only sanitized transport metadata lives outside experiment exports.
            folder = self.manager.owner.safe('ai-binding', 'requests')
            folder.mkdir(exist_ok=True)
            atomic_json(self.manager.owner.safe('ai-binding', 'requests', uuid.uuid4().hex + '.json'), audit)
            if audit['status'] != 'ASSISTANT_RETURNED':
                raise WorkflowError('AI 本次未完整返回，已暂停且不会自动重试。请在连接设置核对；该次请求可能已扣费。', 502)
            return result
        finally:
            self.manager.operation.release()


class BindingManager:
    def __init__(self, owner):
        self.owner = owner
        self.operation = threading.Lock()
        self.quota = RequestQuota(owner)
        self.client = None

    @property
    def managed(self):
        return self.quota.snapshot()['managed']

    def status(self):
        s = self.quota.snapshot()
        enabled = bool(self.client and self.client._key and not s['halted'] and not s['pending'] and s['attempts'] < s['limit'])
        reason = ('已连接；发送实验资料仍需逐次同意。' if enabled else
                  '上次请求未完整确认；请核对并确认保留该次额度。' if s['halted'] or s['pending'] else
                  '已达到累计请求上限；可明确提高上限后重新连接。' if s['attempts'] >= s['limit'] else
                  '请填写自己的 API key。服务重启后需要重新填写。')
        return {'live_enabled': enabled, 'connected': bool(self.client and self.client._key),
                'mode': 'PERSONAL_DEEPSEEK', 'model': MODEL, 'reason': reason,
                'managed': s['managed'], 'request_limit': s['limit'], 'requests_used': s['attempts'],
                'requests_remaining': max(0, s['limit'] - s['attempts']),
                'needs_recovery': bool(s['halted'] or s['pending']), 'in_flight': self.operation.locked(),
                'key_storage': 'SERVER_MEMORY_ONLY', 'max_output_tokens': wire.OUTPUT_BOUND}

    def connect(self, data):
        if (set(data) - {'api_key', 'request_limit', 'approve', 'resume'} or data.get('approve') is not True or
                type(data.get('request_limit')) is not int or not 1 <= data['request_limit'] <= 100):
            raise WorkflowError('请确认使用自己的账户，并设置 1–100 次累计请求上限。')
        key = data.get('api_key')
        if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,200}', key.strip()):
            raise WorkflowError('请填写完整的 DeepSeek API key，勿填写聊天账号密码。')
        if getattr(self.owner, 'simulation_context', None):
            raise WorkflowError('模拟使用环境不能绑定收费账户。', 403)
        if not self.operation.acquire(blocking=False):
            raise WorkflowError('连接或 AI 请求正在处理，请等待后再操作。', 409)
        try:
            key = key.strip()
            account_check(key)
            self.quota.configure(data['request_limit'], data.get('resume'))
            if self.client:
                self.client._key = None
            self.client = BoundClient(self, key)
            return {**self.status(), 'in_flight': False}
        finally:
            self.operation.release()

    def disconnect(self):
        if not self.operation.acquire(blocking=False):
            raise WorkflowError('AI 请求正在处理；结束后可断开连接。', 409)
        try:
            with self.quota.lock:
                self.quota.state['managed'] = True
                self.quota.write()
            self.close()
            return {**self.status(), 'in_flight': False}
        finally:
            self.operation.release()

    def close(self):
        if self.client:
            self.client._key = None
        self.client = None


def manager_for(owner):
    with owner.lock:
        if not hasattr(owner, 'ai_binding'):
            owner.ai_binding = BindingManager(owner)
        return owner.ai_binding
