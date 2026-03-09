#!/usr/bin/env python3

from __future__ import annotations

import argparse
import getpass
import ipaddress
import sys
from dataclasses import dataclass
from pathlib import Path

from cloudflare_ddns import CloudflareClient, DEFAULT_ENV_FILE, DDNSError, load_dotenv, parse_env_value


@dataclass(frozen=True)
class Match:
    zone_id: str
    zone_name: str
    record_id: str
    record_name: str
    proxied: bool
    ttl: int


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = parse_env_value(value)
    return values


def env_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={env_quote(value)}" for key, value in values.items() if value != ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prompt_value(prompt: str, default: str | None = None, secret: bool = False) -> str:
    if not sys.stdin.isatty():
        if default is not None:
            return default
        raise DDNSError(f"Missing interactive input for {prompt}")
    suffix = f" [{default}]" if default else ""
    reader = getpass.getpass if secret else input
    value = reader(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def prompt_optional(prompt: str, default: str | None = None) -> str:
    if not sys.stdin.isatty():
        return default or ""
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan Cloudflare zones for A records matching an IPv4 address and write a .env file."
    )
    parser.add_argument("--api-token", dest="api_token")
    parser.add_argument("--account-id", dest="account_id")
    parser.add_argument("--ip", dest="target_ip")
    parser.add_argument("--env-file", dest="env_file", default=str(DEFAULT_ENV_FILE))
    return parser.parse_args()


def discover_matches(client: CloudflareClient, account_id: str | None, target_ip: str) -> list[Match]:
    matches: list[Match] = []
    zones = client.list_zones(account_id)
    for zone in zones:
        zone_id = zone.get("id")
        zone_name = zone.get("name")
        if not isinstance(zone_id, str) or not zone_id or not isinstance(zone_name, str) or not zone_name:
            continue
        records = client.list_records_by_content(zone_id, "A", target_ip)
        for record in records:
            record_id = record.get("id")
            record_name = record.get("name")
            if not isinstance(record_id, str) or not record_id or not isinstance(record_name, str) or not record_name:
                continue
            ttl = record.get("ttl", 1)
            proxied = bool(record.get("proxied", False))
            matches.append(
                Match(
                    zone_id=zone_id,
                    zone_name=zone_name,
                    record_id=record_id,
                    record_name=record_name,
                    proxied=proxied,
                    ttl=ttl if isinstance(ttl, int) else 1,
                )
            )
    matches.sort(key=lambda item: (item.zone_name, item.record_name))
    return matches


def build_env(existing: dict[str, str], api_token: str, account_id: str | None, matches: list[Match]) -> dict[str, str]:
    values = dict(existing)
    values["CF_API_TOKEN"] = api_token
    values["CF_RECORD_TYPE"] = "A"
    values["CF_RECORDS"] = ",".join(match.record_name for match in matches)
    if account_id:
        values["CF_ACCOUNT_ID"] = account_id
    else:
        values.pop("CF_ACCOUNT_ID", None)

    zone_pairs = {(match.zone_id, match.zone_name) for match in matches}
    if len(zone_pairs) == 1:
        zone_id, zone_name = next(iter(zone_pairs))
        values["CF_ZONE_ID"] = zone_id
        values["CF_ZONE_NAME"] = zone_name
    else:
        values.pop("CF_ZONE_ID", None)
        values.pop("CF_ZONE_NAME", None)

    values.setdefault("CF_STATE_FILE", str(Path(__file__).with_name(".cloudflare_ddns_state.json")))
    return values


def main() -> int:
    args = parse_args()
    env_file = Path(args.env_file).expanduser()
    existing = read_env_file(env_file)
    if env_file.exists():
        load_dotenv(env_file)

    default_token = args.api_token or existing.get("CF_API_TOKEN")
    default_account_id = args.account_id or existing.get("CF_ACCOUNT_ID")
    default_ip = args.target_ip

    api_token = args.api_token or prompt_value("Cloudflare API token", default_token, secret=True)
    account_id = args.account_id if args.account_id is not None else prompt_optional(
        "Cloudflare account ID (optional)", default_account_id
    )
    target_ip = args.target_ip or prompt_value("IPv4 address to search for", default_ip)

    try:
        normalized_ip = str(ipaddress.IPv4Address(target_ip))
    except ipaddress.AddressValueError as exc:
        raise DDNSError(f"Invalid IPv4 address: {target_ip}") from exc

    client = CloudflareClient(api_token)
    matches = discover_matches(client, account_id or None, normalized_ip)
    if not matches:
        raise DDNSError(f"No A records found with IP {normalized_ip}")

    print(f"Found {len(matches)} matching A record(s) for {normalized_ip}:")
    for match in matches:
        proxy_label = "proxied" if match.proxied else "dns-only"
        print(f"- {match.record_name} ({match.zone_name}, ttl={match.ttl}, {proxy_label})")

    values = build_env(existing, api_token, account_id or None, matches)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    write_env_file(env_file, values)

    print(f"Wrote configuration to {env_file}")
    if "CF_ZONE_ID" not in values:
        print("Matched records span multiple zones; CF_ZONE_ID and CF_ZONE_NAME were left unset.")
    print("Run the updater with: python3 cloudflare_ddns.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DDNSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
