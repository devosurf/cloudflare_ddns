#!/usr/bin/env python3
"""Update Cloudflare DNS records when the public IP changes.

Environment variables:
  CF_API_TOKEN        Required. Cloudflare API token with Zone:Read and DNS:Edit.
  CF_ZONE_ID          Optional. Cloudflare zone ID.
  CF_ZONE_NAME        Optional if CF_ZONE_ID is set. Zone name, e.g. example.com.
  CF_RECORDS          Required. Comma-separated record names, e.g. home.example.com,vpn.example.com.
  CF_RECORD_TYPE      Optional. Force A or AAAA. Defaults to the detected IP family.
  CF_IP_URLS          Optional. Comma-separated IP discovery endpoints.
  CF_STATE_FILE       Optional. Path to the local cache file.

Examples:
  CF_API_TOKEN=... \
  CF_ZONE_NAME=example.com \
  CF_RECORDS=home.example.com,vpn.example.com \
  python3 cloudflare_ddns.py
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_IP_URLS = (
    "https://1.1.1.1/cdn-cgi/trace",
    "https://api.ipify.org?format=json",
    "https://ipv4.icanhazip.com",
)
DEFAULT_ENV_FILE = Path(__file__).with_name(".env")
DEFAULT_STATE_FILE = Path(__file__).with_name(".cloudflare_ddns_state.json")
CF_API_BASE = "https://api.cloudflare.com/client/v4"


class DDNSError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_token: str
    account_id: str | None
    zone_id: str | None
    zone_name: str | None
    record_names: tuple[str, ...]
    record_type: str | None
    ip_urls: tuple[str, ...]
    state_file: Path


def parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DDNSError(f"Failed to read env file {path}: {exc}") from exc

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = parse_env_value(value)


def load_config() -> Config:
    api_token = os.environ.get("CF_API_TOKEN", "").strip()
    account_id = os.environ.get("CF_ACCOUNT_ID", "").strip() or None
    zone_id = os.environ.get("CF_ZONE_ID", "").strip() or None
    zone_name = os.environ.get("CF_ZONE_NAME", "").strip() or None
    record_type = os.environ.get("CF_RECORD_TYPE", "").strip().upper() or None
    record_names = tuple(
        name.strip() for name in os.environ.get("CF_RECORDS", "").split(",") if name.strip()
    )
    ip_urls = tuple(
        url.strip() for url in os.environ.get("CF_IP_URLS", "").split(",") if url.strip()
    ) or DEFAULT_IP_URLS
    state_file = Path(os.environ.get("CF_STATE_FILE", str(DEFAULT_STATE_FILE))).expanduser()

    if not api_token:
        raise DDNSError("CF_API_TOKEN is required")
    if not record_names:
        raise DDNSError("CF_RECORDS must contain at least one DNS name")
    if record_type not in {None, "A", "AAAA"}:
        raise DDNSError("CF_RECORD_TYPE must be A or AAAA when set")

    return Config(
        api_token=api_token,
        account_id=account_id,
        zone_id=zone_id,
        zone_name=zone_name,
        record_names=record_names,
        record_type=record_type,
        ip_urls=ip_urls,
        state_file=state_file,
    )


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DDNSError(f"Failed to read state file {path}: {exc}") from exc


def write_state(path: Path, state: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise DDNSError(f"Failed to write state file {path}: {exc}") from exc


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | str:
    data = None
    request_headers = {"User-Agent": "cloudflare-ddns/1.0"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=15) as response:
            payload = response.read().decode("utf-8").strip()
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise DDNSError(f"HTTP {exc.code} for {url}: {details}") from exc
    except error.URLError as exc:
        raise DDNSError(f"Request failed for {url}: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload


def detect_public_ip(ip_urls: tuple[str, ...]) -> str:
    errors_seen: list[str] = []
    for url in ip_urls:
        try:
            payload = http_request(url)
            ip_text = extract_ip(payload)
            return str(ipaddress.ip_address(ip_text))
        except (DDNSError, ValueError) as exc:
            errors_seen.append(f"{url}: {exc}")
    raise DDNSError("Unable to detect public IP from configured endpoints: " + "; ".join(errors_seen))


def extract_ip(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, dict):
        for key in ("ip", "origin"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise DDNSError(f"Unsupported JSON payload while detecting IP: {payload}")

    text = payload.strip()
    if text.startswith("ip="):
        for line in text.splitlines():
            if line.startswith("ip="):
                return line.split("=", 1)[1].strip()
    return text


class CloudflareClient:
    def __init__(self, api_token: str) -> None:
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        }

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = CF_API_BASE + path
        if params:
            url += "?" + parse.urlencode(params)
        payload = http_request(url, method=method, headers=self.headers, body=body)
        if not isinstance(payload, dict):
            raise DDNSError(f"Unexpected Cloudflare response for {path}: {payload}")
        if not payload.get("success", False):
            errors_text = ", ".join(
                item.get("message", "unknown error")
                for item in payload.get("errors", [])
                if isinstance(item, dict)
            )
            raise DDNSError(f"Cloudflare API request failed for {path}: {errors_text or payload}")
        return payload

    def resolve_zone_id(self, zone_id: str | None, zone_name: str | None) -> str:
        if zone_id:
            return zone_id
        assert zone_name is not None
        payload = self.request(
            "/zones",
            params={"name": zone_name, "status": "active", "per_page": "1"},
        )
        result = payload.get("result", [])
        if not result:
            raise DDNSError(f"Zone not found for CF_ZONE_NAME={zone_name}")
        zone = result[0]
        zone_id_value = zone.get("id")
        if not isinstance(zone_id_value, str) or not zone_id_value:
            raise DDNSError(f"Cloudflare returned an invalid zone for {zone_name}: {zone}")
        return zone_id_value

    def list_zones(self, account_id: str | None = None) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        page = 1
        while True:
            params = {"status": "active", "per_page": "50", "page": str(page)}
            if account_id:
                params["account.id"] = account_id
            payload = self.request("/zones", params=params)
            result = payload.get("result", [])
            if not isinstance(result, list):
                raise DDNSError(f"Invalid zone list payload: {payload}")
            zones.extend(zone for zone in result if isinstance(zone, dict))
            result_info = payload.get("result_info")
            total_pages = result_info.get("total_pages", page) if isinstance(result_info, dict) else page
            if page >= int(total_pages):
                break
            page += 1
        return zones

    def get_record(self, zone_id: str, name: str, record_type: str) -> dict[str, Any]:
        payload = self.request(
            f"/zones/{zone_id}/dns_records",
            params={"name.exact": name, "type": record_type, "per_page": "1"},
        )
        result = payload.get("result", [])
        if not result:
            raise DDNSError(f"DNS record not found: {record_type} {name}")
        record = result[0]
        if not isinstance(record, dict):
            raise DDNSError(f"Invalid DNS record payload for {name}: {record}")
        return record

    def list_records_by_content(self, zone_id: str, record_type: str, content: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.request(
                f"/zones/{zone_id}/dns_records",
                params={
                    "type": record_type,
                    "content[exact]": content,
                    "match": "all",
                    "per_page": "100",
                    "page": str(page),
                },
            )
            result = payload.get("result", [])
            if not isinstance(result, list):
                raise DDNSError(f"Invalid DNS record list payload: {payload}")
            records.extend(record for record in result if isinstance(record, dict))
            result_info = payload.get("result_info")
            total_pages = result_info.get("total_pages", page) if isinstance(result_info, dict) else page
            if page >= int(total_pages):
                break
            page += 1
        return records

    def update_record(self, zone_id: str, record: dict[str, Any], new_ip: str) -> dict[str, Any]:
        record_id = record.get("id")
        record_name = record.get("name")
        record_type = record.get("type")
        if not all(isinstance(value, str) and value for value in (record_id, record_name, record_type)):
            raise DDNSError(f"Record is missing required fields: {record}")

        body: dict[str, Any] = {
            "type": record_type,
            "name": record_name,
            "content": new_ip,
            "ttl": record.get("ttl", 1),
            "proxied": record.get("proxied", False),
        }

        for key in ("comment", "tags"):
            if key in record:
                body[key] = record[key]
        settings = record.get("settings")
        if isinstance(settings, dict) and settings:
            body["settings"] = settings

        payload = self.request(f"/zones/{zone_id}/dns_records/{record_id}", method="PATCH", body=body)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise DDNSError(f"Invalid update response for {record_name}: {payload}")
        return result


def is_record_within_zone(record_name: str, zone_name: str) -> bool:
    return record_name == zone_name or record_name.endswith(f".{zone_name}")


def resolve_record_zones(config: Config, client: CloudflareClient) -> dict[str, dict[str, str]]:
    if config.zone_id or config.zone_name:
        zone_id = client.resolve_zone_id(config.zone_id, config.zone_name)
        zone_name = config.zone_name
        if not zone_name:
            zones = client.list_zones(config.account_id)
            zone_match = next((zone for zone in zones if zone.get("id") == zone_id), None)
            zone_name = str(zone_match.get("name", "")).strip() if isinstance(zone_match, dict) else ""
        return {
            record_name: {"zone_id": zone_id, "zone_name": zone_name or ""}
            for record_name in config.record_names
        }

    zones = client.list_zones(config.account_id)
    zone_entries: list[tuple[str, str]] = []
    for zone in zones:
        zone_id = zone.get("id")
        zone_name = zone.get("name")
        if isinstance(zone_id, str) and zone_id and isinstance(zone_name, str) and zone_name:
            zone_entries.append((zone_name, zone_id))
    if not zone_entries:
        raise DDNSError("No active zones available for this API token")

    resolved: dict[str, dict[str, str]] = {}
    for record_name in config.record_names:
        matches = [entry for entry in zone_entries if is_record_within_zone(record_name, entry[0])]
        if not matches:
            raise DDNSError(
                f"Could not infer zone for record {record_name}; set CF_ZONE_ID or CF_ZONE_NAME explicitly"
            )
        zone_name, zone_id = max(matches, key=lambda entry: len(entry[0]))
        resolved[record_name] = {"zone_id": zone_id, "zone_name": zone_name}
    return resolved


def desired_record_type(ip_text: str, configured_type: str | None) -> str:
    if configured_type:
        return configured_type
    version = ipaddress.ip_address(ip_text).version
    return "AAAA" if version == 6 else "A"


def config_fingerprint(config: Config) -> dict[str, Any]:
    return {
        "account_id": config.account_id,
        "record_names": config.record_names,
        "zone_id": config.zone_id,
        "zone_name": config.zone_name,
    }


def main() -> int:
    load_dotenv(DEFAULT_ENV_FILE)
    config = load_config()
    state = read_state(config.state_file)
    current_ip = detect_public_ip(config.ip_urls)
    record_type = desired_record_type(current_ip, config.record_type)
    last_ip = state.get("public_ip")
    current_fingerprint = config_fingerprint(config)

    if (
        last_ip == current_ip
        and state.get("record_type") == record_type
        and state.get("config_fingerprint") == current_fingerprint
    ):
        print(f"Public IP unchanged at {current_ip}; skipping Cloudflare update.")
        return 0

    client = CloudflareClient(config.api_token)
    record_zones = resolve_record_zones(config, client)
    updated_records: list[str] = []
    unchanged_records: list[str] = []

    for record_name in config.record_names:
        zone_id = record_zones[record_name]["zone_id"]
        record = client.get_record(zone_id, record_name, record_type)
        existing_ip = str(record.get("content", "")).strip()
        same_ip = False
        if existing_ip:
            try:
                same_ip = ipaddress.ip_address(existing_ip) == ipaddress.ip_address(current_ip)
            except ValueError:
                same_ip = existing_ip == current_ip
        if same_ip:
            unchanged_records.append(record_name)
            continue
        client.update_record(zone_id, record, current_ip)
        updated_records.append(record_name)

    new_state = {
        "public_ip": current_ip,
        "record_type": record_type,
        "config_fingerprint": current_fingerprint,
        "updated_records": config.record_names,
        "zones": record_zones,
    }
    write_state(config.state_file, new_state)

    print(f"Detected public IP: {current_ip} ({record_type})")
    if updated_records:
        print("Updated records: " + ", ".join(updated_records))
    if unchanged_records:
        print("Already current: " + ", ".join(unchanged_records))
    if not updated_records and not unchanged_records:
        print("No records were processed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DDNSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
