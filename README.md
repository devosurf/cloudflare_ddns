# Cloudflare DDNS Python Script

This repository contains a standalone Python script that checks the current public IP address and updates one or more Cloudflare DNS records when the IP changes.

Scripts:

- `cloudflare_ddns.py` - updater
- `configure_cloudflare_ddns.py` - interactive `.env` generator based on existing Cloudflare `A` records

## Features

- Updates multiple Cloudflare DNS records in one run
- Supports `A` and `AAAA` records
- Uses a Cloudflare API token
- Accepts either a zone ID, a zone name, or infers zones per record
- Caches the last detected public IP in a local state file to avoid unnecessary Cloudflare API calls
- Uses only the Python standard library
- Can generate a `.env` file by scanning Cloudflare for existing `A` records that match a known IPv4 address

## Requirements

- Python 3.10+
- A Cloudflare API token with permissions for the target zone

Recommended token permissions:

- `Zone:Read`
- `DNS:Edit`

## Configuration

The updater reads configuration from environment variables and also loads a local `.env` file automatically when one exists next to `cloudflare_ddns.py`.

### Required variables

| Variable | Description |
| --- | --- |
| `CF_API_TOKEN` | Cloudflare API token |
| `CF_RECORDS` | Comma-separated record names to update |
| `CF_ZONE_ID` or `CF_ZONE_NAME` | Optional when records can be inferred across accessible zones |

### Optional variables

| Variable | Description | Default |
| --- | --- | --- |
| `CF_ACCOUNT_ID` | Optional Cloudflare account ID used when scanning or inferring zones | Unset |
| `CF_RECORD_TYPE` | Force record type: `A` or `AAAA` | Auto-detect from public IP |
| `CF_IP_URLS` | Comma-separated public IP endpoints | Built-in fallback list |
| `CF_STATE_FILE` | Path to the local state file | `.cloudflare_ddns_state.json` next to the script |

## Interactive setup

If you already know the current IPv4 address that your DNS records point to, you can generate a `.env` file automatically.

The setup helper will:

1. prompt for your Cloudflare API token
2. optionally prompt for your Cloudflare account ID
3. prompt for the IPv4 address to search for
4. scan all accessible zones for `A` records with that IP
5. write or create `.env` with the matching records prefilled

Run it with:

```bash
python3 configure_cloudflare_ddns.py
```

You can also pass values on the command line:

```bash
python3 configure_cloudflare_ddns.py --api-token "your_token" --account-id "your_account_id" --ip "203.0.113.10"
```

The helper writes `.env` in the project directory by default. If records are found in a single zone, it writes both `CF_ZONE_ID` and `CF_ZONE_NAME`. If records span multiple zones, it leaves those unset and the updater infers the correct zone for each record at runtime.

## Usage

### Example using a `.env` file

```bash
python3 cloudflare_ddns.py
```

### Example using a zone name

```bash
export CF_API_TOKEN="your_token_here"
export CF_ZONE_NAME="example.com"
export CF_RECORDS="home.example.com,vpn.example.com"

python3 cloudflare_ddns.py
```

### Example using a zone ID

```bash
export CF_API_TOKEN="your_token_here"
export CF_ZONE_ID="your_zone_id_here"
export CF_RECORDS="home.example.com"

python3 cloudflare_ddns.py
```

### Force IPv6 or IPv4

```bash
export CF_RECORD_TYPE="AAAA"
python3 cloudflare_ddns.py
```

Use `A` instead if you want to force IPv4.

## What the script does

1. Loads `.env` if present
2. Detects the current public IP address
3. Determines the record type automatically unless `CF_RECORD_TYPE` is set
4. Resolves zones from `CF_ZONE_ID`, `CF_ZONE_NAME`, or record names
5. Checks each configured DNS record in Cloudflare
6. Updates only records whose IP differs from the current public IP
7. Stores the detected IP in a local state file

If the public IP is unchanged from the previous run and the DDNS configuration is unchanged, the script exits early and skips Cloudflare API calls.

## Cron example

Run every 5 minutes:

```bash
*/5 * * * * CF_API_TOKEN="your_token_here" CF_ZONE_NAME="example.com" CF_RECORDS="home.example.com,vpn.example.com" /usr/bin/python3 /Users/morganjonasson/dev/cloudflare_ddns/cloudflare_ddns.py
```

Adjust the Python path and script path to match your system.

## Notes

- The DNS records should already exist in Cloudflare
- `CF_RECORDS` should contain fully qualified record names
- The state file is a local optimization so repeated runs do less work when the IP has not changed
- Updating the record list, zone settings, or account filter invalidates the cached skip behavior automatically
- The script preserves the existing record `ttl` and `proxied` values when updating
- `.env.example` shows the expected file shape
- The setup helper searches only for `A` records because it is designed to bootstrap IPv4-based DDNS migration

## Files

- `cloudflare_ddns.py` - the updater script
- `configure_cloudflare_ddns.py` - interactive `.env` setup helper
- `.env.example` - example configuration template
- `README.md` - usage and setup instructions
