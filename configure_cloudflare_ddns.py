#!/usr/bin/env python3

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cloudflare_ddns import (
    CloudflareClient,
    DEFAULT_ENV_FILE,
    DEFAULT_RECORD_MAP_FILE,
    DDNSError,
    load_dotenv,
    parse_env_value,
)


@dataclass(frozen=True)
class Match:
    zone_id: str
    zone_name: str
    record_id: str
    record_name: str
    proxied: bool
    ttl: int


def parse_selection(raw: str, max_index: int) -> list[int]:
    selected: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise DDNSError(f"Invalid range: {token}")
            for index in range(start, end + 1):
                if index < 1 or index > max_index:
                    raise DDNSError(f"Selection out of range: {index}")
                selected.add(index)
            continue
        index = int(token)
        if index < 1 or index > max_index:
            raise DDNSError(f"Selection out of range: {index}")
        selected.add(index)
    return sorted(selected)


def choose_matches(matches: list[Match], *, non_interactive: bool) -> list[Match]:
    if not matches:
        return []
    if non_interactive:
        return matches

    print("Select which records to include in the record map.")
    print("Enter comma-separated numbers or ranges like 1,3,5-7.")
    print("Type 'all' to keep every match or 'none' to cancel.")

    while True:
        response = input("Selection [all]: ").strip().lower()
        if response in {"", "all"}:
            confirm = input(f"Include all {len(matches)} records? [y/N]: ").strip().lower()
            if confirm in {"y", "yes"}:
                return matches
            response = input("Selection: ").strip().lower()
        if response == "none":
            raise DDNSError("No records selected")
        try:
            selected_indexes = parse_selection(response, len(matches))
        except (DDNSError, ValueError) as exc:
            print(f"Invalid selection: {exc}")
            continue
        if not selected_indexes:
            print("Select at least one record.")
            continue
        return [matches[index - 1] for index in selected_indexes]


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


def render_env_file(values: dict[str, str]) -> str:
    lines = [f"{key}={env_quote(value)}" for key, value in values.items() if value != ""]
    return "\n".join(lines) + "\n"


def build_record_map_payload(matches: list[Match]) -> dict[str, object]:
    zones: dict[tuple[str, str], list[str]] = {}
    for match in matches:
        key = (match.zone_id, match.zone_name)
        zones.setdefault(key, []).append(match.record_name)

    return {
        "zones": [
            {
                "zone_id": zone_id,
                "zone_name": zone_name,
                "records": sorted(records),
            }
            for zone_id, zone_name, records in sorted(
                ((zone_id, zone_name, records) for (zone_id, zone_name), records in zones.items()),
                key=lambda item: (item[1], item[0]),
            )
        ]
    }


def render_record_map(matches: list[Match]) -> str:
    return json.dumps(build_record_map_payload(matches), indent=2) + "\n"


def write_record_map_file(path: Path, matches: list[Match]) -> None:
    path.write_text(render_record_map(matches), encoding="utf-8")


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
    parser.add_argument("--record-map-file", dest="record_map_file", default=str(DEFAULT_RECORD_MAP_FILE))
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("--all-matches", dest="all_matches", action="store_true")
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


def build_env(existing: dict[str, str], api_token: str, record_map_file: Path) -> dict[str, str]:
    values = dict(existing)
    values["CF_API_TOKEN"] = api_token
    if record_map_file != DEFAULT_RECORD_MAP_FILE:
        values["CF_RECORD_MAP_FILE"] = str(record_map_file)
    else:
        values.pop("CF_RECORD_MAP_FILE", None)

    for key in (
        "CF_ACCOUNT_ID",
        "CF_ZONE_ID",
        "CF_ZONE_NAME",
        "CF_RECORDS",
        "CF_RECORD_TYPE",
        "CF_STATE_FILE",
    ):
        values.pop(key, None)
    return values


def main() -> int:
    args = parse_args()
    env_file = Path(args.env_file).expanduser()
    record_map_file = Path(args.record_map_file).expanduser()
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
    for index, match in enumerate(matches, start=1):
        proxy_label = "proxied" if match.proxied else "dns-only"
        print(f"{index}. {match.record_name} ({match.zone_name}, ttl={match.ttl}, {proxy_label})")

    selected_matches = choose_matches(
        matches,
        non_interactive=args.all_matches or args.dry_run or not sys.stdin.isatty(),
    )
    if len(selected_matches) != len(matches):
        print(f"Selected {len(selected_matches)} of {len(matches)} matching records.")

    values = build_env(existing, api_token, record_map_file)
    env_content = render_env_file(values)
    record_map_content = render_record_map(selected_matches)

    if args.dry_run:
        print("Dry run: no files were written.")
        print(f"Would write configuration to {env_file}:")
        print(env_content, end="")
        print(f"Would write record map to {record_map_file}:")
        print(record_map_content, end="")
        print("Run the updater with: python3 cloudflare_ddns.py")
        return 0

    env_file.parent.mkdir(parents=True, exist_ok=True)
    record_map_file.parent.mkdir(parents=True, exist_ok=True)
    write_record_map_file(record_map_file, selected_matches)
    write_env_file(env_file, values)

    print(f"Wrote configuration to {env_file}")
    print(f"Wrote record map to {record_map_file}")
    print("Run the updater with: python3 cloudflare_ddns.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DDNSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
