# Configuration

All settings come from environment variables. On AWS, `cloudshell/deploy.sh` sets them, and the secrets arrive from Secrets Manager.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///var/vikrikavach.db` | PostgreSQL URL in production (`postgresql://…`; `?sslmode=require` on RDS) |
| `JWT_SECRET` | development value | Signs session cookies. **Required, 32+ characters**, when `APP_ENV=production`. |
| `APP_ENV` | `development` | `production` turns on secure cookies, defaults to SMS login codes, and hides the API docs |
| `OTP_MODE` | `dev`; `sns` in production | `sns` sends login codes by Amazon SNS; `dev` returns them to the screen |
| `S3_BUCKET` | empty (local disk) | Evidence bucket |
| `UPLOAD_DIR` | `var/uploads` | Local evidence folder when there is no bucket |
| `AWS_REGION` | `ap-south-1` | Region for S3 and SNS |
| `STATIC_DIR` | empty | Folder with the built React app (`/srv/static` in the image) |
| `ENABLE_SCHEDULER` | `false` | Daily price import and overdue marking |
| `WEIGHT_TOLERANCE_PCT` | `0.5` | Weight gap allowed before flagging |
| `PAYMENT_DAYS_DEFAULT` | `1` | Days until payment is due when the slip gives no date |
| `ANTHROPIC_API_KEY` | empty | Turns on AI slip reading |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Model used for slip reading |
| `DEMO_APMC_CODE` + `STAFF_PASSWORD` | empty | On startup, creates `demo-officer` and three sample register entries for that APMC |
| `WEB_CONCURRENCY` | `2` | gunicorn workers per container |
| `PORT` | `8080` | Listening port |
| `LOG_LEVEL` | `INFO` | Log level |
