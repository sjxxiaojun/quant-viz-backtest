from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from automation_store import AutomationStore


ActionHandler = Callable[[Dict[str, Any]], Dict[str, Any]]
ActionResultCallback = Callable[[Dict[str, Any]], None]


ALLOWED_ACTIONS = {
    "run_virtual_trade",
    "check_data_integrity",
    "trigger_eod_update",
    "realtime_snapshot",
    "run_factor_lab",
    "run_factor_lab_backtest",
    "run_factor_lab_stress_test",
    "promote_factor_lab_candidate",
    "start_shadow_observation",
    "approve_strategy_version",
    "activate_strategy_version",
    "generate_daily_report",
}

FORBIDDEN_ACTIONS = {
    "real_trade",
    "place_order",
    "broker_order",
    "delete_data",
    "write_code",
    "shell_command",
    "bypass_guardrails",
}


def allowed_action_catalog() -> List[Dict[str, str]]:
    return [
        {"type": "run_virtual_trade", "description": "Run audited virtual-trading catch-up only."},
        {"type": "check_data_integrity", "description": "Compute data freshness and coverage."},
        {"type": "trigger_eod_update", "description": "Run the data lake EOD update with optional dry_run."},
        {"type": "realtime_snapshot", "description": "Capture a realtime market snapshot table."},
        {"type": "run_factor_lab", "description": "Trigger a Factor Lab research run when handler is configured."},
        {"type": "run_factor_lab_backtest", "description": "Run a Factor Lab strategy backtest using current gated artifacts."},
        {"type": "run_factor_lab_stress_test", "description": "Trigger Factor Lab stress test when handler is configured."},
        {"type": "promote_factor_lab_candidate", "description": "Promote an existing Factor Lab run into a candidate strategy version."},
        {"type": "start_shadow_observation", "description": "Start shadow observation for an existing candidate version."},
        {"type": "approve_strategy_version", "description": "Approve a version through existing strategy gates."},
        {"type": "activate_strategy_version", "description": "Activate approved versions through existing gates only."},
        {"type": "generate_daily_report", "description": "Persist an AI report/summary without mutating trading state."},
    ]


class AIAutomationService:
    def __init__(self, store: AutomationStore):
        self.store = store

    def execute_decision(
        self,
        decision: Dict[str, Any],
        *,
        handlers: Dict[str, ActionHandler],
        source: str = "external_ai",
        dry_run: bool = False,
        on_action_result: Optional[ActionResultCallback] = None,
    ) -> Dict[str, Any]:
        actions = decision.get("actions") if isinstance(decision.get("actions"), list) else []
        actor = str(decision.get("actor") or source or "external_ai")
        summary = str(decision.get("summary") or "")
        confidence = decision.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except Exception:
            confidence_value = None

        action_results: List[Dict[str, Any]] = []

        def append_result(result: Dict[str, Any]) -> None:
            action_results.append(result)
            if on_action_result is None:
                return
            try:
                on_action_result(result)
            except Exception:
                pass

        for action in actions:
            if not isinstance(action, dict):
                append_result({"status": "rejected", "reason": "action_not_object", "action": action})
                continue
            action_type = str(action.get("type") or "").strip()
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            if not action_type:
                append_result({"status": "rejected", "reason": "missing_type", "action": action})
                continue
            if action_type in FORBIDDEN_ACTIONS or action_type not in ALLOWED_ACTIONS:
                append_result({"type": action_type, "status": "rejected", "reason": "action_not_allowed"})
                continue
            if dry_run or bool(decision.get("dry_run")):
                append_result({"type": action_type, "status": "planned", "params": params})
                continue
            handler = handlers.get(action_type)
            if handler is None:
                append_result({"type": action_type, "status": "skipped", "reason": "handler_not_configured"})
                continue
            try:
                handler_result = handler(params)
                append_result({"type": action_type, "status": "executed", "result": handler_result})
            except Exception as exc:
                append_result({"type": action_type, "status": "failed", "error": str(exc)})

        status = self._decision_status(action_results, bool(dry_run or decision.get("dry_run")))
        record = self.store.record_ai_decision(
            decision_id=str(decision.get("decision_id") or "") or None,
            actor=actor,
            source=source,
            status=status,
            summary=summary,
            confidence=confidence_value,
            actions=actions,
            result={"actions": action_results},
            error=None if status not in {"failed", "rejected"} else self._first_error(action_results),
        )
        return {"decision": record, "action_results": action_results, "allowed_actions": allowed_action_catalog()}

    def call_external_ai(self, context: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = os.getenv("QUANT_AI_ENDPOINT", "").strip()
        if not endpoint:
            return {
                "actor": "local_guardrail",
                "source": "local_fallback",
                "summary": "No QUANT_AI_ENDPOINT configured. Generated local daily report only.",
                "confidence": 1.0,
                "actions": [{"type": "generate_daily_report", "params": {"mode": "local_fallback"}}],
            }

        api_key = os.getenv("QUANT_AI_API_KEY", "").strip()
        compatible = os.getenv("QUANT_AI_OPENAI_COMPATIBLE", "").strip().lower() in {"1", "true", "yes"}
        payload: Dict[str, Any]
        if compatible:
            model = os.getenv("QUANT_AI_MODEL", "").strip()
            if not model:
                payload = {"context": context, "response_format": "json"}
            else:
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Return strict JSON with keys summary, confidence, actions. "
                                "Use only allowed action types. Do not include markdown, XML thinking, "
                                "or explanations outside JSON."
                            ),
                        },
                        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                    ],
                    "response_format": {"type": "json_object"},
                }
        else:
            payload = {"context": context, "allowed_actions": allowed_action_catalog()}

        raw = self._post_json(endpoint, api_key, payload)
        decoded = json.loads(raw)
        if compatible and isinstance(decoded, dict):
            choices = decoded.get("choices")
            if choices:
                content = choices[0].get("message", {}).get("content")
                if isinstance(content, str):
                    return self._with_external_defaults(self._parse_decision_text(content))
        if isinstance(decoded, dict):
            return self._with_external_defaults(decoded)
        return self._with_external_defaults({"summary": raw, "actions": []})

    def _post_json(self, endpoint: str, api_key: str, payload: Dict[str, Any]) -> str:
        if os.getenv("QUANT_AI_FORCE_CURL", "").strip().lower() in {"1", "true", "yes"}:
            return self._post_json_with_curl(endpoint, api_key, payload)

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(api_key),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=min(self._request_timeout(), 30)) as response:
                return response.read().decode("utf-8")
        except Exception:
            return self._post_json_with_curl(endpoint, api_key, payload)

    def _post_json_with_curl(self, endpoint: str, api_key: str, payload: Dict[str, Any]) -> str:
        body_path = ""
        config_path = ""
        timeout_seconds = self._request_timeout()
        attempts = self._request_retries()
        last_error: Optional[Exception] = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as body:
                body_path = body.name
                os.chmod(body_path, 0o600)
                body.write(json.dumps(payload, ensure_ascii=False))

            config_lines = [
                f'url = "{endpoint}"',
                'request = "POST"',
                "silent",
                "show-error",
                f'max-time = "{timeout_seconds}"',
                'header = "Content-Type: application/json"',
                f'data-binary = "@{body_path}"',
                'write-out = "\\n__HTTP_STATUS__:%{http_code}"',
            ]
            if api_key:
                config_lines.insert(6, f'header = "Authorization: Bearer {api_key}"')
                config_lines.insert(7, f'header = "X-Quant-Api-Key: {api_key}"')

            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config:
                config_path = config.name
                os.chmod(config_path, 0o600)
                config.write("\n".join(config_lines))

            for attempt in range(1, attempts + 1):
                try:
                    completed = subprocess.run(
                        ["/usr/bin/curl", "--config", config_path],
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds + 10,
                        check=False,
                    )
                    if completed.returncode != 0:
                        raise RuntimeError(completed.stderr.strip() or f"curl exited {completed.returncode}")
                    body_text, status_text = self._split_curl_response(completed.stdout)
                    if status_text and int(status_text) >= 400:
                        raise RuntimeError(f"HTTP Error {status_text}: {body_text[:500]}")
                    return body_text
                except Exception as exc:
                    last_error = exc
                    if attempt < attempts:
                        time.sleep(min(2 * attempt, 6))
            raise RuntimeError(str(last_error) if last_error else "curl request failed")
        finally:
            for path in (body_path, config_path):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    @staticmethod
    def _split_curl_response(raw: str) -> tuple[str, str]:
        marker = "\n__HTTP_STATUS__:"
        if marker not in raw:
            return raw, ""
        body, status = raw.rsplit(marker, 1)
        return body, status.strip()

    @staticmethod
    def _request_timeout() -> int:
        try:
            return max(10, min(int(os.getenv("QUANT_AI_TIMEOUT_SECONDS", "90")), 300))
        except Exception:
            return 90

    @staticmethod
    def _request_retries() -> int:
        try:
            return max(1, min(int(os.getenv("QUANT_AI_RETRIES", "2")), 5))
        except Exception:
            return 2

    @staticmethod
    def _headers(api_key: str) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-Quant-Api-Key"] = api_key
        return headers

    @classmethod
    def _parse_decision_text(cls, text: str) -> Dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            return {"summary": "", "actions": []}
        try:
            decoded = json.loads(stripped)
            return decoded if isinstance(decoded, dict) else {"summary": stripped, "actions": []}
        except json.JSONDecodeError:
            pass

        parsed_candidates: List[Dict[str, Any]] = []
        for candidate in cls._json_object_candidates(stripped):
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                parsed_candidates.append(decoded)

        for candidate in parsed_candidates:
            if "actions" in candidate or "summary" in candidate:
                return candidate
        if parsed_candidates:
            return parsed_candidates[-1]
        return {"summary": stripped, "actions": []}

    @staticmethod
    def _with_external_defaults(decision: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(decision)
        normalized.setdefault("actor", os.getenv("QUANT_AI_MODEL", "").strip() or "external_ai")
        normalized.setdefault("source", os.getenv("QUANT_AI_SOURCE", "").strip() or "external_ai")
        return normalized

    @staticmethod
    def _json_object_candidates(text: str) -> List[str]:
        candidates: List[str] = []
        depth = 0
        start: Optional[int] = None
        in_string = False
        escaped = False

        for idx, char in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif char == "}" and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start : idx + 1])
                    start = None
        return candidates

    @staticmethod
    def _decision_status(action_results: List[Dict[str, Any]], dry_run: bool) -> str:
        if dry_run:
            return "dry_run"
        if not action_results:
            return "skipped"
        statuses = {str(item.get("status")) for item in action_results}
        if statuses <= {"rejected"}:
            return "rejected"
        if "failed" in statuses:
            return "partial" if "executed" in statuses else "failed"
        if "executed" in statuses:
            return "executed"
        if "planned" in statuses:
            return "dry_run"
        return "skipped"

    @staticmethod
    def _first_error(action_results: List[Dict[str, Any]]) -> Optional[str]:
        for item in action_results:
            if item.get("error"):
                return str(item["error"])
            if item.get("reason"):
                return str(item["reason"])
        return None
