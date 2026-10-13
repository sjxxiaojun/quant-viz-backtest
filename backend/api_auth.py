"""Local service authentication, separate from optional model credentials."""
import logging
import os
import secrets
from typing import Any, Dict, List
from fastapi import HTTPException, Request
logger = logging.getLogger("momoQuantAPI")

def service_api_key():
    # An explicitly empty new key disables the legacy fallback.
    return os.getenv("QUANT_API_KEY", os.getenv("QUANT_AI_API_KEY", "")).strip()

# 可信本机来源白名单：按 TCP 对端地址判断，并额外识别反向代理特征。
# 背景：部署在 nginx / frp / cloudflare tunnel 之后时，所有外部请求的对端地址
# 都是回环地址，纯粹按对端地址做豁免等于把状态变更接口（含自动化下单相关）
# 对公网敞开。这里不粗暴删掉本机豁免（会破坏本机日常使用），而是：
# 只要请求带任何代理转发特征头，就一律不给回环豁免，只能走 X-Quant-Api-Key。
# 想彻底关闭本机豁免仍可把 QUANT_API_TRUSTED_HOSTS 设为空串。
def _trusted_local_hosts() -> set:
    raw = os.getenv("QUANT_API_TRUSTED_HOSTS", "127.0.0.1,::1")
    return {item.strip() for item in raw.split(",") if item.strip()}


# 常见反向代理 / 隧道 / CDN 的转发特征头。出现其中任意一个，
# 都说明 request.client.host 是代理自己的地址而非真实调用方。
PROXY_FORWARDING_HEADERS = (
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
)


def _detected_proxy_headers(request: Request) -> List[str]:
    headers = request.headers
    return [name for name in PROXY_FORWARDING_HEADERS if headers.get(name)]


def _is_trusted_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host not in _trusted_local_hosts():
        return False
    proxy_headers = _detected_proxy_headers(request)
    if proxy_headers:
        # 回环地址 + 转发头 = 反向代理后的外部请求，取消豁免。
        logger.warning(
            "拒绝对回环来源 %s 授予本机豁免：请求带有反向代理转发头 %s，"
            "请改用 X-Quant-Api-Key 鉴权（并确认 QUANT_API_KEY 已配置）。",
            host or "unknown",
            ",".join(proxy_headers),
        )
        return False
    return True


def _require_local_request(request: Request) -> None:
    if not _is_trusted_local_request(request):
        raise HTTPException(status_code=403, detail="状态变更接口仅允许本机访问。")


def _has_valid_quant_api_key(request: Request) -> bool:
    expected = service_api_key()
    if not expected:
        return False
    provided = request.headers.get("X-Quant-Api-Key", "").strip()
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        provided = provided or auth.split(" ", 1)[1].strip()
    if not provided:
        return False
    try:
        return secrets.compare_digest(provided, expected)
    except TypeError:
        try:
            return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
        except Exception:
            return False
    except Exception:
        return False


def _require_automation_request(request: Request) -> None:
    if _is_trusted_local_request(request):
        return
    if _has_valid_quant_api_key(request):
        return
    raise HTTPException(status_code=403, detail="自动化/AI 接口仅允许本机或有效 X-Quant-Api-Key 访问。")


def describe_api_auth_state() -> Dict[str, Any]:
    """当前鉴权口径快照，供启动日志与后续鉴权回归测试使用。"""
    hosts = sorted(_trusted_local_hosts())
    return {
        "loopback_exemption_enabled": bool(hosts),
        "trusted_hosts": hosts,
        "api_key_configured": bool(service_api_key()),
        # 带反向代理转发头的请求永远拿不到本机豁免，见 _is_trusted_local_request()。
        "proxy_headers_revoke_exemption": True,
        "proxy_headers_watched": list(PROXY_FORWARDING_HEADERS),
    }


def log_api_auth_state() -> None:
    """启动时把鉴权状态打到日志，一眼看清自己有没有暴露。"""
    if "QUANT_API_KEY" not in os.environ and os.getenv("QUANT_AI_API_KEY"):
        logger.warning("鉴权沿用 QUANT_AI_API_KEY；请迁移服务密钥至 QUANT_API_KEY，模型密钥至 QUANT_AI_MODEL_API_KEY。")
    state = describe_api_auth_state()
    summary = (
        "鉴权状态 | 本机(回环)豁免=%s [%s] | API Key(QUANT_API_KEY)=%s | 带反向代理转发头的请求一律不豁免"
        % (
            "开启" if state["loopback_exemption_enabled"] else "关闭",
            ",".join(state["trusted_hosts"]) or "空",
            "已配置" if state["api_key_configured"] else "未配置",
        )
    )
    if state["loopback_exemption_enabled"] and not state["api_key_configured"]:
        logger.warning(
            "%s —— 状态变更接口（含自动化下单相关）目前只靠【本机来源】保护。"
            "若本服务要暴露到 nginx/frp/cloudflare tunnel 之后，请先配置 QUANT_API_KEY，"
            "并把 QUANT_API_TRUSTED_HOSTS 设为空串以彻底关闭回环豁免。",
            summary,
        )
    elif not state["loopback_exemption_enabled"] and not state["api_key_configured"]:
        logger.error(
            "%s —— 回环豁免已关闭且未配置 API Key，所有状态变更接口将一律返回 403（含本机调用）。",
            summary,
        )
    else:
        logger.info("%s", summary)


