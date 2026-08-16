# -*- coding: utf-8 -*-
"""状态变更接口鉴权回归测试。

覆盖 main.py 的三个鉴权原语：

* ``_is_trusted_local_request()`` —— 回环白名单（QUANT_API_TRUSTED_HOSTS 可配置），
  但请求只要带任一反向代理转发头（``PROXY_FORWARDING_HEADERS``）就一律不给豁免。
* ``_has_valid_quant_api_key()`` —— X-Quant-Api-Key / Bearer，定时安全比较。
* ``_require_automation_request()`` / ``_require_local_request()`` —— 端点侧闸门。

设计要点（为什么这些测试"不是摆设"）：

1. **每个 403 断言都同时挂了 tripwire**：先把端点内部真正干活的函数
   （下单、跑晨报、写 AI 决策……）换成计数桩，403 之外还要断言"桩一次都没被调用"。
   万一鉴权被绕过，测试不会因为业务函数恰好抛错而"意外变绿"，也不会真的触发自动化下单。
2. **testclient 后门回归**：默认 ``TestClient(app)`` 的对端地址就是 ``"testclient"``，
   历史白名单是 ``{"127.0.0.1", "::1", "localhost", "testclient"}``。
   把 ``testclient`` / ``localhost`` 加回白名单，本文件里的
   ``test_testclient_identity_is_not_a_backdoor`` 系列会立刻变红。
3. **端点清单用 AST 冻结**：谁把某个端点上的 ``_require_*`` 删掉，
   ``test_guard_coverage_inventory_is_frozen`` 立刻变红。
"""

import ast
import json
import secrets as secrets_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

import main


MAIN_SOURCE_PATH = Path(main.__file__).resolve()

# 外部来源（TEST-NET-3，RFC 5737 文档保留地址，永远不会是真实的本机地址）
EXTERNAL_HOST = "203.0.113.7"
EXTERNAL_HOST_V6 = "2001:db8::dead:beef"
GOOD_KEY = "regression-good-key-1234567890"


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _hermetic_auth_env(monkeypatch):
    """把鉴权相关环境变量清干净，避免开发机 .env.local / shell 里的值污染断言。"""
    monkeypatch.delenv("QUANT_AI_API_KEY", raising=False)
    monkeypatch.delenv("QUANT_API_TRUSTED_HOSTS", raising=False)
    yield


def make_client(host: Optional[str], port: int = 50000) -> TestClient:
    """按指定 TCP 对端地址构造客户端；host=None 表示 scope 里没有 client（如 unix socket）。"""
    if host is None:
        return TestClient(main.app, client=None)
    return TestClient(main.app, client=(host, port))


def loopback_client() -> TestClient:
    return make_client("127.0.0.1")


def external_client() -> TestClient:
    return make_client(EXTERNAL_HOST)


class Tripwire:
    """端点内部真正干活的函数的替身：只记账，绝不产生副作用。"""

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"__tripwire__": True, "status": "stubbed"}

    @property
    def call_count(self) -> int:
        return len(self.calls)


# --------------------------------------------------------------------------- #
# 被保护端点清单（枚举自 main.py，见 test_guard_coverage_inventory_is_frozen）
# --------------------------------------------------------------------------- #
AUTOMATION_GUARD = "_require_automation_request"
LOCAL_GUARD = "_require_local_request"


@dataclass(frozen=True)
class GuardedEndpoint:
    method: str
    path: str
    guard: str
    body: Optional[Dict[str, Any]] = None
    params: Optional[Dict[str, Any]] = None
    # main 模块内的点分路径，会被换成 Tripwire。第一个元素必须是端点里"真正干活"的那个。
    side_effects: Tuple[str, ...] = ()
    needs_report_fixture: bool = False
    # 直接关系到自动化下单 / 资金动作的端点
    trade_critical: bool = False
    note: str = ""

    @property
    def ident(self) -> str:
        return f"{self.method} {self.path}"


GUARDED_ENDPOINTS: Tuple[GuardedEndpoint, ...] = (
    GuardedEndpoint(
        "POST", "/api/automation/jobs/virtual-trade", AUTOMATION_GUARD,
        side_effects=("automation_orchestrator.run_virtual_trade",),
        trade_critical=True, note="自动化模拟盘下单",
    ),
    GuardedEndpoint(
        "POST", "/api/virtual-trade/execute", LOCAL_GUARD,
        side_effects=("_execute_virtual_trade_locked",),
        trade_critical=True, note="手动触发模拟盘下单（更严：API Key 也不放行）",
    ),
    GuardedEndpoint(
        "POST", "/api/ai/decisions", AUTOMATION_GUARD,
        body={"actor": "regression", "source": "regression", "summary": "auth guard probe", "actions": []},
        side_effects=("ai_automation_service.execute_decision", "_configure_ai_handlers"),
        trade_critical=True, note="外部 AI 直接投递可执行动作",
    ),
    GuardedEndpoint(
        "POST", "/api/automation/jobs/ai-cycle", AUTOMATION_GUARD,
        body={"dry_run": True},
        side_effects=("automation_orchestrator.run_ai_cycle", "_configure_ai_handlers"),
        trade_critical=True, note="AI 决策循环（可下单）",
    ),
    GuardedEndpoint(
        "POST", "/api/automation/jobs/ai-managed-work", AUTOMATION_GUARD,
        body={"work_type": "simulation_supervision", "dry_run": True},
        side_effects=("automation_orchestrator.run_ai_managed_work", "_configure_ai_handlers"),
        trade_critical=True, note="AI 托管作业（可下单）",
    ),
    GuardedEndpoint(
        "POST", "/api/automation/jobs/realtime-snapshot", AUTOMATION_GUARD,
        body={"limit": 10},
        side_effects=("automation_orchestrator.run_realtime_snapshot",),
    ),
    GuardedEndpoint(
        "POST", "/api/automation/jobs/eod-update", AUTOMATION_GUARD,
        body={"dry_run": True, "limit_a_share": 1, "limit_etf": 1},
        side_effects=("automation_orchestrator.run_eod_update",),
    ),
    GuardedEndpoint(
        "POST", "/api/daily-report/generate", AUTOMATION_GUARD,
        side_effects=("_generate_daily_report_locked",),
    ),
    GuardedEndpoint(
        "GET", "/api/daily-report/latest", AUTOMATION_GUARD,
        params={"regenerate": "true"},
        side_effects=("_generate_daily_report_locked",),
        needs_report_fixture=True, note="deprecated 兼容路径：GET 触发重生成",
    ),
    GuardedEndpoint("GET", "/api/ai/context", AUTOMATION_GUARD, side_effects=("_build_ai_context",)),
    GuardedEndpoint(
        "GET", "/api/ai/decisions", AUTOMATION_GUARD,
        side_effects=("automation_store.list_ai_decisions",),
    ),
    GuardedEndpoint(
        "GET", "/api/ai/work-logs", AUTOMATION_GUARD,
        side_effects=("automation_store.list_ai_work_logs",),
    ),
    GuardedEndpoint(
        "GET", "/api/ai/work-messages", AUTOMATION_GUARD,
        side_effects=("automation_store.list_ai_work_messages",),
    ),
)

AUTOMATION_ENDPOINTS = tuple(e for e in GUARDED_ENDPOINTS if e.guard == AUTOMATION_GUARD)
LOCAL_ONLY_ENDPOINTS = tuple(e for e in GUARDED_ENDPOINTS if e.guard == LOCAL_GUARD)
TRADE_CRITICAL_ENDPOINTS = tuple(e for e in GUARDED_ENDPOINTS if e.trade_critical)
# 探针端点：自动化下单，且不需要请求体，最适合做大批量参数化
PROBE = GUARDED_ENDPOINTS[0]


def _resolve_target(dotted: str):
    """把 'automation_orchestrator.run_virtual_trade' 解析成 (owner_obj, attr_name)。"""
    obj: Any = main
    parts = dotted.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    return obj, parts[-1]


def arm_tripwires(endpoint: GuardedEndpoint, monkeypatch) -> Tripwire:
    """把端点内部所有会产生副作用的函数换成同一个 Tripwire。"""
    wire = Tripwire()
    for dotted in endpoint.side_effects:
        owner, attr = _resolve_target(dotted)
        assert hasattr(owner, attr), f"{dotted} 不存在，端点清单需要同步更新"
        monkeypatch.setattr(owner, attr, wire)
    return wire


def prepare_report_fixture(monkeypatch, tmp_path: Path) -> None:
    """GET /api/daily-report/latest 只有在『晨报存在且已过期』时才会走鉴权分支。"""
    import daily_morning_report

    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest.json").write_text(
        json.dumps({"report_date": "2026-07-26", "sections": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(daily_morning_report, "REPORT_DIR", report_dir)
    monkeypatch.setattr(main, "_daily_report_staleness", lambda data: ["regression-forced-stale"])


def call(client: TestClient, endpoint: GuardedEndpoint, headers: Optional[Dict[str, str]] = None):
    kwargs: Dict[str, Any] = {"headers": headers or {}}
    if endpoint.params:
        kwargs["params"] = endpoint.params
    if endpoint.body is not None:
        kwargs["json"] = endpoint.body
    return client.request(endpoint.method, endpoint.path, **kwargs)


@dataclass
class Probe:
    """一次完整的『发请求 + 检查副作用』。"""

    response: Any
    tripwire: Tripwire

    def assert_blocked(self, context: str) -> None:
        assert self.response.status_code == 403, (
            f"{context}: 期望 403，实际 {self.response.status_code} —— 鉴权被绕过了。"
            f" body={self.response.text[:300]}"
        )
        assert self.tripwire.call_count == 0, (
            f"{context}: 返回了 403，但端点内部的业务函数仍被调用了 "
            f"{self.tripwire.call_count} 次 —— 副作用没有被真正拦住。"
        )

    def assert_allowed(self, context: str) -> None:
        assert self.response.status_code == 200, (
            f"{context}: 期望 200，实际 {self.response.status_code}。body={self.response.text[:300]}"
        )
        assert self.tripwire.call_count >= 1, (
            f"{context}: 返回了 200，但端点内部的业务函数一次都没被调用 —— 这条『放行』断言是空的。"
        )


def probe_endpoint(
    endpoint: GuardedEndpoint,
    monkeypatch,
    tmp_path: Path,
    host: Optional[str],
    headers: Optional[Dict[str, str]] = None,
) -> Probe:
    wire = arm_tripwires(endpoint, monkeypatch)
    if endpoint.needs_report_fixture:
        prepare_report_fixture(monkeypatch, tmp_path)
    response = call(make_client(host), endpoint, headers=headers)
    return Probe(response=response, tripwire=wire)


def endpoint_ids(endpoints) -> list:
    return [e.ident for e in endpoints]


# --------------------------------------------------------------------------- #
# 1. 无 API Key + 非回环来源 → 403
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("endpoint", GUARDED_ENDPOINTS, ids=endpoint_ids(GUARDED_ENDPOINTS))
def test_external_request_without_api_key_is_forbidden(endpoint, monkeypatch, tmp_path):
    """外部 IP + 没有 API Key → 所有被保护端点必须 403，且业务代码一行都不能跑。"""
    probe_endpoint(endpoint, monkeypatch, tmp_path, EXTERNAL_HOST).assert_blocked(
        f"外部来源 {EXTERNAL_HOST} 无 Key 访问 {endpoint.ident}"
    )


@pytest.mark.parametrize("endpoint", TRADE_CRITICAL_ENDPOINTS, ids=endpoint_ids(TRADE_CRITICAL_ENDPOINTS))
def test_external_ipv6_request_without_api_key_is_forbidden(endpoint, monkeypatch, tmp_path):
    probe_endpoint(endpoint, monkeypatch, tmp_path, EXTERNAL_HOST_V6).assert_blocked(
        f"外部 IPv6 来源无 Key 访问 {endpoint.ident}"
    )


@pytest.mark.parametrize(
    "host",
    ["203.0.113.7", "10.0.0.9", "192.168.1.50", "172.17.0.1", "0.0.0.0", "127.0.0.2", "127.1.1.1", "localhost"],
)
def test_non_loopback_hosts_are_all_untrusted(host, monkeypatch, tmp_path):
    """内网地址、Docker 网关、127.0.0.2 这类"看起来像本机"的地址都不在白名单里。

    注意 ``localhost``：历史白名单里有它（对端地址不可能是字符串 localhost，
    纯属把不可信输入当可信），加固后已移除。
    """
    probe_endpoint(PROBE, monkeypatch, tmp_path, host).assert_blocked(f"来源 {host} 访问自动化下单端点")


def test_missing_client_scope_is_untrusted(monkeypatch, tmp_path):
    """scope 里没有 client（unix socket / 某些 ASGI 服务器）时不能当成本机。"""
    probe_endpoint(PROBE, monkeypatch, tmp_path, None).assert_blocked("无 client 信息的请求")


# --------------------------------------------------------------------------- #
# 2. 正确 API Key → 放行
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("endpoint", AUTOMATION_ENDPOINTS, ids=endpoint_ids(AUTOMATION_ENDPOINTS))
def test_valid_api_key_grants_access_from_external_host(endpoint, monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(
        endpoint, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": GOOD_KEY}
    ).assert_allowed(f"外部来源持正确 Key 访问 {endpoint.ident}")


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Quant-Api-Key": GOOD_KEY},
        {"x-quant-api-key": GOOD_KEY},                       # 头名大小写不敏感
        {"Authorization": f"Bearer {GOOD_KEY}"},             # Bearer 变体
        {"Authorization": f"bearer {GOOD_KEY}"},             # bearer 小写
        {"X-Quant-Api-Key": f"  {GOOD_KEY}  "},              # 两侧空白会被 strip
    ],
    ids=["header", "header-lowercase", "bearer", "bearer-lowercase", "header-padded"],
)
def test_api_key_accepted_forms(headers, monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers=headers).assert_allowed(
        f"外部来源使用 {headers} 访问自动化下单端点"
    )


def test_env_key_with_surrounding_whitespace_is_stripped(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_AI_API_KEY", f"  {GOOD_KEY}\n")
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": GOOD_KEY}
    ).assert_allowed("环境变量两侧带空白时仍应匹配")


# --------------------------------------------------------------------------- #
# 3. 错误 API Key → 403（且比较是定时安全的）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_key",
    [
        "wrong-key",
        "",
        " ",
        GOOD_KEY[:-1],                 # 少一位
        GOOD_KEY + "x",                # 多一位
        GOOD_KEY.upper(),              # 大小写不同
        GOOD_KEY.replace("-", "_"),    # 相同长度、一字之差
        GOOD_KEY[::-1],                # 相同字符集、顺序不同
    ],
    ids=["wrong", "empty", "space", "truncated", "extended", "uppercased", "one-char-diff", "reversed"],
)
def test_wrong_api_key_is_forbidden(bad_key, monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": bad_key}
    ).assert_blocked(f"外部来源使用错误 Key {bad_key!r}")


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": f"Bearer {GOOD_KEY}x"},
        {"Authorization": GOOD_KEY},                 # 没有 Bearer 前缀
        {"Authorization": f"Basic {GOOD_KEY}"},      # 错误的 scheme
        {"X-Quant-Api-Key": "wrong", "Authorization": f"Bearer {GOOD_KEY}"},  # 专用头优先，坏值不该被 Bearer 救回
    ],
    ids=["bearer-wrong", "no-scheme", "basic-scheme", "bad-header-beats-good-bearer"],
)
def test_wrong_authorization_forms_are_forbidden(headers, monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers=headers).assert_blocked(
        f"外部来源使用 {headers}"
    )


@pytest.mark.parametrize("provided", ["", " ", "anything", "None", "null"])
def test_unset_env_key_never_authenticates(provided, monkeypatch, tmp_path):
    """QUANT_AI_API_KEY 没配时，任何 Key（包括空串）都不能通过 —— 防"空==空"漏洞。"""
    assert main.describe_api_auth_state()["api_key_configured"] is False
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": provided}
    ).assert_blocked(f"未配置 Key 时提交 {provided!r}")


@pytest.mark.parametrize("env_value", ["", "   ", "\n"])
def test_blank_env_key_never_authenticates(env_value, monkeypatch, tmp_path):
    """把 QUANT_AI_API_KEY 配成空白等于没配，不能让空 Key 请求通过。"""
    monkeypatch.setenv("QUANT_AI_API_KEY", env_value)
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": env_value}
    ).assert_blocked(f"QUANT_AI_API_KEY={env_value!r} 时提交同样的空白 Key")


def test_api_key_comparison_goes_through_constant_time_compare(monkeypatch, tmp_path):
    """行为级证明：真实 HTTP 请求确实调用了 secrets.compare_digest，而不是 ``==``。"""
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    seen = []
    real_compare = secrets_module.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr(main.secrets, "compare_digest", spy)

    probe_endpoint(
        PROBE, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": "wrong-key"}
    ).assert_blocked("错误 Key")

    assert seen, "错误 Key 的校验没有经过 secrets.compare_digest —— 说明改回了普通字符串比较"
    assert ("wrong-key", GOOD_KEY) in seen


def _raw_header_request(header_name: bytes, header_value: bytes, host: str = EXTERNAL_HOST):
    """直接拼 ASGI scope，用来送 httpx 拒绝发送的原始字节头（真实攻击者可以随手发）。"""
    from starlette.requests import Request as StarletteRequest

    return StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/automation/jobs/virtual-trade",
            "query_string": b"",
            "headers": [(header_name, header_value)],
            "client": (host, 50000),
        }
    )


@pytest.mark.parametrize(
    "raw_value", ["密钥".encode("utf-8"), b"\xe9\xe8", b"\xff\xfe"], ids=["utf8", "latin1", "binary"]
)
def test_non_ascii_api_key_is_rejected_not_crashed(raw_value, monkeypatch):
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    assert main._has_valid_quant_api_key(_raw_header_request(b"x-quant-api-key", raw_value)) is False


def test_api_key_comparison_source_has_no_plain_equality():
    """结构级兜底：源码里不能再出现 provided == expected 这类短路比较。"""
    import inspect

    source = inspect.getsource(main._has_valid_quant_api_key)
    assert "secrets.compare_digest" in source
    for forbidden in ("provided == expected", "expected == provided", "provided != expected"):
        assert forbidden not in source, f"_has_valid_quant_api_key 里出现了非定时安全比较：{forbidden}"


# --------------------------------------------------------------------------- #
# 4. 回环 + 反向代理转发头 → 403（本次加固的核心）
# --------------------------------------------------------------------------- #
EXPECTED_PROXY_HEADERS = frozenset(
    {
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-forwarded-server",
        "x-original-forwarded-for",
        "forwarded",
        "x-real-ip",
        "x-client-ip",
        "true-client-ip",
        "cf-connecting-ip",
        "fastly-client-ip",
        "fly-client-ip",
        "x-cluster-client-ip",
    }
)

PROXY_HEADER_SAMPLE_VALUES = {
    "forwarded": "for=203.0.113.7;proto=https;host=quant.example.com",
    "x-forwarded-proto": "https",
    "x-forwarded-port": "443",
    "x-forwarded-host": "quant.example.com",
    "x-forwarded-server": "nginx-1",
}


def proxy_header_value(name: str) -> str:
    return PROXY_HEADER_SAMPLE_VALUES.get(name, EXTERNAL_HOST)


def test_proxy_forwarding_header_list_is_frozen():
    """转发头清单被冻结：删掉任何一个（例如 x-forwarded-for）都会让这条变红。"""
    actual = main.PROXY_FORWARDING_HEADERS
    assert isinstance(actual, tuple)
    assert len(actual) == len(set(actual)) == 14, f"转发头清单被改动了：{actual}"
    assert set(actual) == EXPECTED_PROXY_HEADERS, (
        f"缺失={EXPECTED_PROXY_HEADERS - set(actual)} 新增={set(actual) - EXPECTED_PROXY_HEADERS}"
    )
    assert all(name == name.lower() for name in actual), "头名必须全小写，否则匹配会漏"


@pytest.mark.parametrize("header", sorted(EXPECTED_PROXY_HEADERS))
@pytest.mark.parametrize("loopback", ["127.0.0.1", "::1"])
def test_loopback_with_proxy_header_loses_exemption(header, loopback, monkeypatch, tmp_path):
    """反代场景：对端是回环，但带了转发头 → 必须 403（14 个头 × 2 个回环地址逐个覆盖）。"""
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, loopback, headers={header: proxy_header_value(header)}
    ).assert_blocked(f"回环 {loopback} + 转发头 {header}")


@pytest.mark.parametrize("endpoint", GUARDED_ENDPOINTS, ids=endpoint_ids(GUARDED_ENDPOINTS))
def test_every_guarded_endpoint_rejects_proxied_loopback(endpoint, monkeypatch, tmp_path):
    """所有被保护端点（含全部自动化下单相关）在反代场景下都必须 403。"""
    probe_endpoint(
        endpoint, monkeypatch, tmp_path, "127.0.0.1", headers={"X-Forwarded-For": EXTERNAL_HOST}
    ).assert_blocked(f"反代场景访问 {endpoint.ident}")


@pytest.mark.parametrize(
    "header",
    ["X-Forwarded-For", "x-forwarded-for", "X-FORWARDED-FOR", "X-Real-IP", "CF-Connecting-IP", "Forwarded"],
)
def test_proxy_header_match_is_case_insensitive(header, monkeypatch, tmp_path):
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, "127.0.0.1", headers={header: proxy_header_value(header.lower())}
    ).assert_blocked(f"回环 + 大小写变体 {header}")


def test_all_proxy_headers_at_once_is_rejected(monkeypatch, tmp_path):
    headers = {name: proxy_header_value(name) for name in sorted(EXPECTED_PROXY_HEADERS)}
    probe_endpoint(PROBE, monkeypatch, tmp_path, "127.0.0.1", headers=headers).assert_blocked(
        "回环 + 14 个转发头全带"
    )


def test_proxied_loopback_logs_the_reason(monkeypatch, tmp_path, caplog):
    with caplog.at_level("WARNING", logger=main.logger.name):
        probe_endpoint(
            PROBE, monkeypatch, tmp_path, "127.0.0.1", headers={"X-Forwarded-For": EXTERNAL_HOST}
        ).assert_blocked("反代场景")
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "x-forwarded-for" in messages, f"没有打出拒绝原因，实际日志：{messages[:500]}"


@pytest.mark.parametrize("header", sorted(EXPECTED_PROXY_HEADERS))
def test_empty_proxy_header_value_does_not_break_local_usage(header, monkeypatch, tmp_path):
    """空值转发头不算"带头"，本机日常使用（curl / vite proxy）不能被误伤。"""
    probe_endpoint(PROBE, monkeypatch, tmp_path, "127.0.0.1", headers={header: ""}).assert_allowed(
        f"回环 + 空值 {header}"
    )


@pytest.mark.parametrize("endpoint", GUARDED_ENDPOINTS, ids=endpoint_ids(GUARDED_ENDPOINTS))
def test_plain_loopback_still_works(endpoint, monkeypatch, tmp_path):
    """加固不能误伤本机：不带转发头的 127.0.0.1 仍然放行（这是回归保护的另一半）。"""
    probe_endpoint(endpoint, monkeypatch, tmp_path, "127.0.0.1").assert_allowed(
        f"纯本机访问 {endpoint.ident}"
    )


def test_ipv6_loopback_still_works(monkeypatch, tmp_path):
    probe_endpoint(PROBE, monkeypatch, tmp_path, "::1").assert_allowed("IPv6 回环访问自动化下单端点")


@pytest.mark.parametrize("endpoint", AUTOMATION_ENDPOINTS, ids=endpoint_ids(AUTOMATION_ENDPOINTS))
def test_proxied_loopback_can_still_pass_with_valid_api_key(endpoint, monkeypatch, tmp_path):
    """反代场景下唯一的合法通路：X-Quant-Api-Key。"""
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(
        endpoint, monkeypatch, tmp_path, "127.0.0.1",
        headers={"X-Forwarded-For": EXTERNAL_HOST, "X-Quant-Api-Key": GOOD_KEY},
    ).assert_allowed(f"反代 + 正确 Key 访问 {endpoint.ident}")


@pytest.mark.parametrize("endpoint", LOCAL_ONLY_ENDPOINTS, ids=endpoint_ids(LOCAL_ONLY_ENDPOINTS))
def test_local_only_endpoints_reject_even_valid_api_key(endpoint, monkeypatch, tmp_path):
    """``_require_local_request`` 比自动化闸门更严：持有正确 Key 的外部调用方也进不来。"""
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(
        endpoint, monkeypatch, tmp_path, EXTERNAL_HOST, headers={"X-Quant-Api-Key": GOOD_KEY}
    ).assert_blocked(f"外部来源持正确 Key 访问仅本机端点 {endpoint.ident}")

    probe_endpoint(
        endpoint, monkeypatch, tmp_path, "127.0.0.1",
        headers={"X-Forwarded-For": EXTERNAL_HOST, "X-Quant-Api-Key": GOOD_KEY},
    ).assert_blocked(f"反代 + 正确 Key 访问仅本机端点 {endpoint.ident}")


# --------------------------------------------------------------------------- #
# 5. testclient 后门回归测试
# --------------------------------------------------------------------------- #
BACKDOOR_HOSTS = ["testclient", "localhost", "TESTCLIENT", "Localhost", "test", "unknown", ""]


@pytest.mark.parametrize("endpoint", GUARDED_ENDPOINTS, ids=endpoint_ids(GUARDED_ENDPOINTS))
def test_testclient_identity_is_not_a_backdoor(endpoint, monkeypatch, tmp_path):
    """默认 ``TestClient(app)`` 的对端地址就是 ``testclient``。

    历史白名单 ``{"127.0.0.1", "::1", "localhost", "testclient"}`` 意味着：
    只要请求声称自己是测试客户端就能免鉴权。把 ``testclient`` 加回白名单，这条立刻变红。
    """
    wire = arm_tripwires(endpoint, monkeypatch)
    if endpoint.needs_report_fixture:
        prepare_report_fixture(monkeypatch, tmp_path)
    response = call(TestClient(main.app), endpoint)  # 不指定 client → host == "testclient"
    Probe(response, wire).assert_blocked(f"默认 TestClient 身份访问 {endpoint.ident}")


@pytest.mark.parametrize("host", BACKDOOR_HOSTS)
def test_backdoor_hostnames_are_not_trusted(host, monkeypatch, tmp_path):
    probe_endpoint(PROBE, monkeypatch, tmp_path, host).assert_blocked(f"伪装成 {host!r} 的来源")


@pytest.mark.parametrize("host", ["testclient", "localhost"])
def test_backdoor_hostnames_absent_from_default_whitelist(host, monkeypatch):
    """白名单默认值里不能出现 testclient / localhost。"""
    monkeypatch.delenv("QUANT_API_TRUSTED_HOSTS", raising=False)
    assert host not in main._trusted_local_hosts()
    assert host not in main.describe_api_auth_state()["trusted_hosts"]


def test_default_whitelist_is_exactly_the_two_loopback_addresses(monkeypatch):
    monkeypatch.delenv("QUANT_API_TRUSTED_HOSTS", raising=False)
    assert main._trusted_local_hosts() == {"127.0.0.1", "::1"}


def test_guard_source_contains_no_hardcoded_testclient_whitelist():
    """结构级兜底：整个鉴权代码段里不能出现 'testclient' 字面量。"""
    import inspect

    for func in (main._is_trusted_local_request, main._trusted_local_hosts, main._require_automation_request,
                 main._require_local_request, main._has_valid_quant_api_key):
        source = inspect.getsource(func)
        assert "testclient" not in source.lower(), f"{func.__name__} 里出现了 testclient 白名单"


# --------------------------------------------------------------------------- #
# 6. QUANT_API_TRUSTED_HOSTS 配成空串 → 回环也必须鉴权
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("endpoint", GUARDED_ENDPOINTS, ids=endpoint_ids(GUARDED_ENDPOINTS))
def test_empty_trusted_hosts_forces_auth_on_loopback(endpoint, monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", "")
    probe_endpoint(endpoint, monkeypatch, tmp_path, "127.0.0.1").assert_blocked(
        f"关闭回环豁免后本机访问 {endpoint.ident}"
    )


@pytest.mark.parametrize("raw", ["", "   ", ",", " , ,, "])
def test_blank_trusted_hosts_values_all_disable_exemption(raw, monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", raw)
    assert main._trusted_local_hosts() == set()
    assert main.describe_api_auth_state()["loopback_exemption_enabled"] is False
    probe_endpoint(PROBE, monkeypatch, tmp_path, "127.0.0.1").assert_blocked(
        f"QUANT_API_TRUSTED_HOSTS={raw!r} 时的本机访问"
    )


def test_empty_trusted_hosts_still_allows_valid_api_key(monkeypatch, tmp_path):
    """关闭回环豁免后，自动化端点仍可用 API Key 访问（否则运维会被彻底锁死）。"""
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", "")
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, "127.0.0.1", headers={"X-Quant-Api-Key": GOOD_KEY}
    ).assert_allowed("关闭豁免 + 正确 Key")


def test_empty_trusted_hosts_locks_down_local_only_endpoint(monkeypatch, tmp_path):
    """仅本机端点在关闭豁免后彻底不可达（连正确 Key 也没用）—— 与启动日志的 ERROR 提示一致。"""
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", "")
    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    for endpoint in LOCAL_ONLY_ENDPOINTS:
        probe_endpoint(
            endpoint, monkeypatch, tmp_path, "127.0.0.1", headers={"X-Quant-Api-Key": GOOD_KEY}
        ).assert_blocked(f"关闭豁免后访问 {endpoint.ident}")


def test_trusted_hosts_env_actually_drives_the_whitelist(monkeypatch, tmp_path):
    """白名单确实来自环境变量，而不是写死的常量。"""
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", "10.0.0.5, 10.0.0.6 ")
    assert main._trusted_local_hosts() == {"10.0.0.5", "10.0.0.6"}
    probe_endpoint(PROBE, monkeypatch, tmp_path, "10.0.0.5").assert_allowed("自定义白名单命中")
    probe_endpoint(PROBE, monkeypatch, tmp_path, "127.0.0.1").assert_blocked("自定义白名单未包含 127.0.0.1")


def test_custom_trusted_host_still_loses_exemption_when_proxied(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", "10.0.0.5")
    probe_endpoint(
        PROBE, monkeypatch, tmp_path, "10.0.0.5", headers={"X-Forwarded-For": EXTERNAL_HOST}
    ).assert_blocked("自定义白名单 + 转发头")


# --------------------------------------------------------------------------- #
# 7. 端点覆盖清单（AST 冻结）—— 谁删掉某个端点上的守卫，这里立刻变红
# --------------------------------------------------------------------------- #
EXPECTED_GUARD_MAP = {e.ident: e.guard for e in GUARDED_ENDPOINTS}

# 已知未鉴权的状态变更端点。它们是回测 / 因子实验 / 策略版本管理类接口，
# 本轮加固未纳入（不属于本测试的产品改动范围），在此显式记录：
# 新增未鉴权的状态变更端点会让 test_guard_coverage_inventory_is_frozen 变红，
# 逼迫改动者要么加守卫、要么明确把它写进这份清单。
KNOWN_UNGUARDED_MUTATING_ROUTES = frozenset(
    {
        "POST /api/backtest",
        "POST /api/backtest/jobs",
        "POST /api/backtest/compare",
        "POST /api/backtest/compare/jobs",
        "POST /api/factor-lab/readiness",
        "POST /api/factor-lab/run",
        "POST /api/factor-lab/backtest",
        "POST /api/factor-lab/stress-test",
        "POST /api/factor-lab/candidates/{run_id}/promote",
        "POST /api/factor-lab/artifacts/cleanup",
        "POST /api/strategy-versions/{version_id}/shadow",
        "POST /api/strategy-versions/{version_id}/approve",
        "POST /api/strategy-versions/{version_id}/iterate",
        "POST /api/strategies/{strategy_id}/activate-version",
        "POST /api/strategies/{strategy_id}/rollback",
        "POST /api/overnight/scan",
    }
)

GUARD_NAMES = {AUTOMATION_GUARD, LOCAL_GUARD}


def _scan_routes():
    """用 AST 扫出 main.py 里所有 @app.<method> 路由以及各自调用的鉴权守卫。"""
    tree = ast.parse(MAIN_SOURCE_PATH.read_text(encoding="utf-8"))
    routes = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        guards = {
            sub.func.id
            for sub in ast.walk(node)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in GUARD_NAMES
        }
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                continue
            if not isinstance(deco.func.value, ast.Name) or deco.func.value.id != "app":
                continue
            method = deco.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if not deco.args or not isinstance(deco.args[0], ast.Constant):
                continue
            routes[f"{method} {deco.args[0].value}"] = guards
    return routes


def test_guard_coverage_inventory_is_frozen():
    routes = _scan_routes()
    assert routes, "AST 没扫到任何路由，扫描逻辑本身坏了"

    actual_guarded = {ident: sorted(guards) for ident, guards in routes.items() if guards}
    missing = {i: g for i, g in EXPECTED_GUARD_MAP.items() if i not in actual_guarded}
    assert not missing, f"这些端点的鉴权守卫被删掉了：{missing}"

    for ident, guard in EXPECTED_GUARD_MAP.items():
        assert actual_guarded[ident] == [guard], (
            f"{ident} 的守卫从 {guard} 变成了 {actual_guarded[ident]}"
        )

    extra = set(actual_guarded) - set(EXPECTED_GUARD_MAP)
    assert not extra, (
        f"新增了受保护端点 {sorted(extra)}，请同步加进 GUARDED_ENDPOINTS 以便纳入回归覆盖"
    )


def test_no_new_unguarded_mutating_route_appears():
    routes = _scan_routes()
    unguarded_mutating = {
        ident for ident, guards in routes.items() if ident.split(" ", 1)[0] != "GET" and not guards
    }
    new = unguarded_mutating - KNOWN_UNGUARDED_MUTATING_ROUTES
    assert not new, (
        f"新增了未鉴权的状态变更端点：{sorted(new)}。"
        "请加 _require_automation_request / _require_local_request，"
        "或在 KNOWN_UNGUARDED_MUTATING_ROUTES 里显式登记并说明原因。"
    )


def test_every_trade_critical_endpoint_is_covered_by_this_file():
    """自动化下单 / 资金动作相关端点必须在本文件的回归清单里。"""
    trade_related = {
        ident
        for ident in _scan_routes()
        if any(token in ident for token in ("/virtual-trade/execute", "/automation/jobs/", "/api/ai/decisions"))
    }
    covered = {e.ident for e in GUARDED_ENDPOINTS}
    assert trade_related <= covered, f"下单相关端点没有被鉴权回归覆盖：{sorted(trade_related - covered)}"


# --------------------------------------------------------------------------- #
# 8. describe_api_auth_state() 自省快照
# --------------------------------------------------------------------------- #
def test_describe_api_auth_state_reflects_env(monkeypatch):
    monkeypatch.delenv("QUANT_AI_API_KEY", raising=False)
    monkeypatch.delenv("QUANT_API_TRUSTED_HOSTS", raising=False)
    state = main.describe_api_auth_state()
    assert state["loopback_exemption_enabled"] is True
    assert state["trusted_hosts"] == ["127.0.0.1", "::1"]
    assert state["api_key_configured"] is False
    assert state["proxy_headers_revoke_exemption"] is True
    assert set(state["proxy_headers_watched"]) == EXPECTED_PROXY_HEADERS

    monkeypatch.setenv("QUANT_AI_API_KEY", GOOD_KEY)
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", "")
    hardened = main.describe_api_auth_state()
    assert hardened["loopback_exemption_enabled"] is False
    assert hardened["trusted_hosts"] == []
    assert hardened["api_key_configured"] is True


@pytest.mark.parametrize(
    "trusted,api_key,expected_level",
    [
        ("127.0.0.1,::1", "", "WARNING"),   # 只靠本机来源保护
        ("127.0.0.1,::1", GOOD_KEY, "INFO"),
        ("", GOOD_KEY, "INFO"),
        ("", "", "ERROR"),                  # 全锁死
    ],
)
def test_log_api_auth_state_levels(trusted, api_key, expected_level, monkeypatch, caplog):
    monkeypatch.setenv("QUANT_API_TRUSTED_HOSTS", trusted)
    monkeypatch.setenv("QUANT_AI_API_KEY", api_key)
    caplog.clear()
    with caplog.at_level("INFO", logger=main.logger.name):
        main.log_api_auth_state()
    records = [r for r in caplog.records if "鉴权状态" in r.getMessage()]
    assert len(records) == 1, f"启动鉴权日志应恰好打印 1 条，实际 {len(records)} 条"
    assert records[0].levelname == expected_level
