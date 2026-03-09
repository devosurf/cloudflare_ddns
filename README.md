# Cloudflare DDNS Python Script

This repository contains a standalone Python script that checks the current public IP address and updates one or more Cloudflare DNS records when the IP changes.

Scripts:

- `cloudflare_ddns.py` - updater
- `configure_cloudflare_ddns.py` - interactive generator for `.env` and `cloudflare_records.json`

## Features

- Updates multiple Cloudflare DNS records in one run
- Supports `A` and `AAAA` records
- Uses a Cloudflare API token
- Supports a JSON record map with zone objects and record lists
- Still accepts zone IDs, zone names, or record-name inference as fallbacks
- Caches the last detected public IP in a local state file to avoid unnecessary Cloudflare API calls
- Uses only the Python standard library
- Can generate a JSON record map by scanning Cloudflare for existing `A` records that match a known IPv4 address

## Requirements

- Python 3.10+
- A Cloudflare API token with permissions for the target zone

Recommended token permissions:

- `Zone:Read`
- `DNS:Read` for the setup helper scan
- `DNS:Edit` for the updater

## Configuration

The updater reads configuration from environment variables and also loads a local `.env` file automatically when one exists next to `cloudflare_ddns.py`.

The default setup now uses:

- `.env` for `CF_API_TOKEN`
- `cloudflare_records.json` for zone-to-record mappings

### Required variables

| Variable | Description |
| --- | --- |
| `CF_API_TOKEN` | Cloudflare API token |
| `CF_RECORDS` | Comma-separated record names to update when not using a JSON record map |
| `CF_ZONE_ID` or `CF_ZONE_NAME` | Optional fallback when not using a JSON record map |

### Optional variables

| Variable | Description | Default |
| --- | --- | --- |
| `CF_ACCOUNT_ID` | Optional Cloudflare account ID used when scanning or inferring zones | Unset |
| `CF_RECORD_MAP_FILE` | Optional path to a JSON file containing zone objects and record lists | `cloudflare_records.json` next to the script when present |
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
5. write or create `.env` with your API token
6. write or update `cloudflare_records.json` with zone objects and record lists

Run it with:

```bash
python3 configure_cloudflare_ddns.py
```

You can also pass values on the command line:

```bash
python3 configure_cloudflare_ddns.py --api-token "your_token" --account-id "your_account_id" --ip "203.0.113.10"
```

Use a custom env file path:

```bash
python3 configure_cloudflare_ddns.py --env-file "/path/to/cloudflare_ddns.env"
```

Use a custom record map path:

```bash
python3 configure_cloudflare_ddns.py --record-map-file "/path/to/cloudflare_records.json"
```

Preview the generated files without writing them:

```bash
python3 configure_cloudflare_ddns.py --dry-run
```

If the target `.env` already exists, the helper reads it first and reuses existing values as prompt defaults. The API token prompt is hidden input.

The helper writes `.env` and `cloudflare_records.json` in the project directory by default.

The helper writes or updates these keys:

- `CF_API_TOKEN`
- `CF_RECORD_MAP_FILE` only when you choose a non-default JSON path

It removes the older record-selection env keys (`CF_RECORDS`, `CF_ZONE_ID`, `CF_ZONE_NAME`, `CF_RECORD_TYPE`, `CF_ACCOUNT_ID`) and preserves unrelated existing `.env` keys.

The generated JSON is grouped by zone and written in a deterministic order: zones are sorted by `zone_name` and `zone_id`, and each zone's `records` list is sorted alphabetically.

The generated JSON file looks like this:

```json
{
  "zones": [
    {
      "zone_id": "your_zone_id_here",
      "zone_name": "example.com",
      "records": [
        "home.example.com",
        "vpn.example.com"
      ]
    }
  ]
}
```

## Usage

### Example using a `.env` file

```bash
python3 cloudflare_ddns.py
```

With the default JSON workflow, `.env` only needs `CF_API_TOKEN` and the updater automatically reads `cloudflare_records.json` when it exists next to the script.

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
2. Loads `cloudflare_records.json` if present
3. Detects the current public IP address
4. Determines the record type automatically unless `CF_RECORD_TYPE` is set
5. Resolves zones from the JSON map, explicit zone env vars, or record names
6. Checks each configured DNS record in Cloudflare
7. Updates only records whose IP differs from the current public IP
8. Stores the detected IP in a local state file

If the public IP is unchanged from the previous run and the DDNS configuration is unchanged, the script exits early and skips Cloudflare API calls.

## Cron example

Run every 5 minutes:

```bash
*/5 * * * * CF_API_TOKEN="your_token_here" /usr/bin/python3 /Users/morganjonasson/dev/cloudflare_ddns/cloudflare_ddns.py
```

This default cron example assumes `cloudflare_records.json` exists next to the script. Adjust the Python path and script path to match your system.

## Notes

- The DNS records should already exist in Cloudflare
- JSON record maps should contain fully qualified record names
- The state file is a local optimization so repeated runs do less work when the IP has not changed
- Updating the JSON record map or zone settings invalidates the cached skip behavior automatically
- The script preserves the existing record `ttl` and `proxied` values when updating
- `.env.example` shows the expected file shape
- `cloudflare_records.example.json` shows the JSON mapping shape
- The setup helper searches only for `A` records because it is designed to bootstrap IPv4-based DDNS migration

## Files

- `cloudflare_ddns.py` - the updater script
- `configure_cloudflare_ddns.py` - interactive setup helper
- `.env.example` - example configuration template
- `cloudflare_records.example.json` - example JSON record map
- `README.md` - usage and setup instructions
