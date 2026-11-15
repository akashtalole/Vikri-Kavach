# Operating the service

Run all of these from the repository folder in CloudShell. The database is private inside the VPC, so admin commands run as **one-off ECS tasks**. Each task uses the same image, network and secrets as the live service, and its output is printed in CloudShell.

## Find an APMC code

```bash
./cloudshell/admin.sh apmc-codes nashik
```

```text
02190400  Lasalgaon                          Nashik           लासलगांव
02191300  Pimpalgaon basawant                Nashik           पिंपिळगाव बसवंत
...
```

## Create an APMC officer

```bash
./cloudshell/admin.sh create-staff --username lasalgaon-secretary --apmc-code 02190400 --name "APMC Secretary, Lasalgaon"
```

You are asked for the password twice. It is **hashed in CloudShell**, so only the scrypt hash reaches AWS. Running the same command again resets that officer's password. Use `--role admin` for a state-level account that sees every APMC.

Officers log in on the app's login page under **APMC staff**.

## Load an APMC's licence register

Prepare a CSV file from the APMC's official licence records:

```text
licence_no,name,firm,status
L-1001,Ramesh Patil,Patil Traders,active
L-1002,Sunil Shinde,Shinde & Sons,suspended
```

`status` must be `active`, `suspended` or `cancelled`. Upload the file to CloudShell (**Actions → Upload file**), then:

```bash
./cloudshell/admin.sh import-traders --apmc-code 02190400 register.csv
```

The file is staged in the evidence bucket, imported, and then deleted. Re-importing updates existing licences. Officers can also edit single entries under **Traders** in the app.

## Check health and status

```bash
./cloudshell/status.sh
```

This shows the URL, service state, image, running and desired tasks, the rollout state, the health response, recent service events, and the database state.

## Logs

```bash
./cloudshell/logs.sh
```

```bash
./cloudshell/logs.sh --since 2h --no-follow
```

The daily jobs log a line like `daily jobs: {'overdue_marked': 3, 'prices': {...}}` once a day.

## Run the daily jobs now

```bash
./cloudshell/admin.sh daily
```

This imports today's MSAMB prices and marks overdue payments. It normally runs by itself once a day; with several tasks running, only one of them does the work.

## Database backups

RDS keeps automated backups for 7 days. Snapshots and point-in-time restore are in the RDS console under **Databases → vikrikavach-db**. `destroy.sh` takes a final snapshot before it deletes anything.
