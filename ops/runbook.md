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

4. Migrate pricing baseline:
   ```bash
   python ops/migrate_baseline.py \
     --in /path/to/pricing_baseline_v5.obf \
     --out data/pricing_baseline.json \
     --key "$PRICING_BASELINE_KEY"
   ```

5. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with production values
   ```

6. Create initial API token:
   ```bash
   source .venv/bin/activate
   python -m app.cli add-token --org <org-name>
   # Save the printed token — it's shown only once
   ```

7. Install systemd service:
   ```bash
   sudo cp ops/systemd/quanlaidian-quote.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now quanlaidian-quote
   ```

8. Configure nginx:
   ```bash
   sudo cp ops/nginx.conf.example /etc/nginx/sites-available/quanlaidian-quote
   sudo ln -s /etc/nginx/sites-available/quanlaidian-quote /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

9. Set up TLS:
   ```bash
   sudo certbot --nginx -d api.quanlaidian.com
   ```

10. Set up file cleanup cron:
    ```bash
    sudo crontab -e
    # Add: 0 3 * * * /opt/quanlaidian-quote/ops/cron/cleanup-files.sh
    ```

11. Verify:
    ```bash
    curl https://api.quanlaidian.com/healthz
    ```

## Adding New Tokens

```bash
cd /opt/quanlaidian-quote
source .venv/bin/activate
python -m app.cli add-token --org <org-name>
```

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
