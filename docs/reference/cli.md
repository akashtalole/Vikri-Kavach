# Command line

The image installs a `vikrikavach` command. On AWS, run it through `./cloudshell/admin.sh`, which starts a one-off task in the VPC. Locally, run it directly; it uses the same environment variables as the app.

| Command | Purpose |
|---|---|
| `vikrikavach create-staff --username U --apmc-code CODE [--name N] [--role officer\|admin] [--password-hash H]` | Create a staff account, or reset an existing one's password and APMC. Without `--password-hash`, the password comes from `STAFF_PASSWORD` or a prompt. |
| `vikrikavach hash-password [--stdin]` | Print a scrypt hash for `--password-hash` |
| `vikrikavach import-traders --apmc-code CODE FILE` | Load a register CSV (`licence_no,name,firm,status`). `FILE` can be a local path or `s3://bucket/key`. |
| `vikrikavach seed-demo --apmc-code CODE` | Demo officer and three sample register entries. Needs `STAFF_PASSWORD`; safe to run more than once. |
| `vikrikavach daily` | Run the price import and overdue marking now |

## CloudShell scripts

| Script | Purpose |
|---|---|
| `cloudshell/deploy.sh` | Create or update the whole deployment ([guide](../deploy/cloudshell.md)) |
| `cloudshell/admin.sh` | `apmc-codes`, `create-staff`, `import-traders`, `seed-demo`, `daily` ([guide](../deploy/operations.md)) |
| `cloudshell/status.sh` | URL, health, tasks, database |
| `cloudshell/logs.sh [--since 1h] [--no-follow]` | CloudWatch logs |
| `cloudshell/destroy.sh [--delete-evidence] [--no-snapshot] [--yes]` | Remove the deployment |

Every script reads `APP` (default `vikrikavach`) and `AWS_REGION`. Setting a different `APP` gives a second, separate deployment in the same account, for example `APP=vk-staging ./cloudshell/deploy.sh`.
