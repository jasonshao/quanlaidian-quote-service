# Quanlaidian Quote Service — Deployment Runbook

## Prerequisites

- Ubuntu 22.04+
- Python 3.10+
- nginx
- certbot

## First-Time Deploy

1. Create service user:
   ```bash
   sudo useradd -r -s /bin/false quanlaidian
   ```

2. Clone repo:
   ```bash
   sudo mkdir -p /opt/quanlaidian-quote
   sudo chown quanlaidian:quanlaidian /opt/quanlaidian-quote
   cd /opt/quanlaidian-quote
   git clone <private-repo-url> .
   ```

3. Set up Python environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

4. Configure environment:
   ```bash
   cp .env.example .env
   # Required: PRICING_BASELINE_KEY (decrypts references/pricing_baseline_v5.obf at runtime)
   # Recommended for prod: PRICING_BASELINE_STRICT=1 (refuses plaintext fallback)
   # Optional overrides: QUOTE_API_BASE_URL, QUOTE_DATA_ROOT, etc.
   ```

   The obfuscated baseline is shipped committed at
   `references/pricing_baseline_v5.obf` — no migration step needed for normal
   deploys. If you prefer plaintext (not recommended), run
   `python ops/migrate_baseline.py --in references/pricing_baseline_v5.obf --out data/pricing_baseline.json --key "$PRICING_BASELINE_KEY"`
   and leave `PRICING_BASELINE_STRICT` unset.

5. Create initial API token:
   ```bash
   source .venv/bin/activate
   python -m app.cli add-token --org <org-name>
   # Default: 180-day expiry. Save the printed plaintext — it's shown only once.
   # For a permanent token: python -m app.cli add-token --org <name> --no-expire
   ```

   Tokens are stored hashed in `data/quote.db`'s `api_token` table. The CLI
   never prints the hash for existing tokens.

6. Install systemd service:
   ```bash
   sudo cp ops/systemd/quanlaidian-quote.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now quanlaidian-quote
   ```

7. Configure nginx:
   ```bash
   sudo cp ops/nginx.conf.example /etc/nginx/sites-available/quanlaidian-quote
   sudo ln -s /etc/nginx/sites-available/quanlaidian-quote /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

8. Set up TLS:
   ```bash
   sudo certbot --nginx -d <your-api-host>
   ```

9. Set up file cleanup cron:
   ```bash
   sudo crontab -e
   # Add: 0 3 * * * /opt/quanlaidian-quote/ops/cron/cleanup-files.sh
   ```

10. Verify:
    ```bash
    curl https://<your-api-host>/healthz
    ```

## Rotating the pricing baseline

When wholesale costs change:

```bash
# 1. Regenerate plaintext JSON from the source xlsx
python ops/extract_baseline_from_xlsx.py \
  --xlsx /path/to/全来店底价单V5.xlsx \
  --output /tmp/pricing_baseline.json

# 2. Re-obfuscate with the same key
python ops/obfuscate_baseline.py \
  --input /tmp/pricing_baseline.json \
  --output references/pricing_baseline_v5.obf \
  --key "$PRICING_BASELINE_KEY"

# 3. Commit the updated .obf and redeploy
rm /tmp/pricing_baseline.json
```

## Managing Tokens

```bash
cd /opt/quanlaidian-quote
source .venv/bin/activate

# Add a new token (default: 180-day expiry)
python -m app.cli add-token --org <org-name>
python -m app.cli add-token --org <org-name> --expires-in 30d
python -m app.cli add-token --org <org-name> --no-expire

# List tokens (shows token_id, org, created, expires, status, last_used_on)
python -m app.cli list-tokens

# Revoke a token
python -m app.cli revoke-token --id tok_xxxxxxxx
```

Tokens live in `data/quote.db`'s `api_token` table. Server stores only
`sha256(plaintext)`; the plaintext is shown once at creation and cannot
be retrieved again — lose it and you must issue a new one.

## Migrating legacy tokens.json (one-time)

Older deploys used `data/tokens.json` as a flat JSON file. To move those
tokens into the new `api_token` table:

```bash
cd /opt/quanlaidian-quote
source .venv/bin/activate
python -m app.cli migrate-tokens-json
# prints: migrated N token(s), skipped 0 duplicate(s)
# tokens.json is renamed to tokens.json.migrated-<UTC timestamp>
sudo systemctl restart quanlaidian-quote
```

Verify: old clients whose plaintext tokens were issued via the legacy
CLI should still authenticate (the hash is preserved). Migrated tokens
carry no expiry — rotate them on your own schedule.

## Viewing Logs

```bash
# Application logs
journalctl -u quanlaidian-quote -f

# Audit logs
tail -f /opt/quanlaidian-quote/data/audit/$(date +%Y-%m-%d).jsonl | python -m json.tool
```

## Rollback

```bash
cd /opt/quanlaidian-quote
git log --oneline -5  # find the target commit
git checkout <commit>
sudo systemctl restart quanlaidian-quote
```
