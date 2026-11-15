# Deploy from AWS CloudShell

AWS CloudShell is a terminal in the AWS console that is already signed in, with the AWS CLI, git, jq and Python installed. You need nothing on your own computer.

## 1. Open CloudShell

1. Sign in to the [AWS console](https://console.aws.amazon.com/) with a user that can create IAM roles, RDS, S3, ECR, ECS and CodeBuild resources. An administrator account is simplest for a first deployment.
2. In the top-right region menu, choose the region for the app, for example **Asia Pacific (Mumbai) ap-south-1**.
3. Click the **CloudShell** icon (`>_`) in the top bar.

## 2. Deploy

```bash
git clone https://github.com/akashtalole/Vikri-Kavach.git && cd Vikri-Kavach
```

```bash
./cloudshell/deploy.sh --demo-apmc 02190400
```

`02190400` is Lasalgaon (Nashik). To find another APMC's code, use `./cloudshell/admin.sh apmc-codes <name or district>`. Leave out `--demo-apmc` for a deployment without demo data.

The deployment takes about **15–20 minutes**; most of that is waiting for the new database. The script shows each step:

| Step | What happens |
|---|---|
| 1. Network | Uses the region's default VPC. If there isn't one, it tells you to run `aws ec2 create-default-vpc`. |
| 2. Database | Creates **RDS PostgreSQL** (`db.t4g.micro`, 20 GB gp3, encrypted, private, 7-day backups, deletion protection). Its security group accepts PostgreSQL only from inside the VPC. The password is generated and kept in Secrets Manager. |
| 3. Evidence storage | A private, encrypted, versioned **S3** bucket. |
| 4. Image | Builds the container. It uses Docker in CloudShell when there is room, otherwise **AWS CodeBuild**, and pushes the image to **ECR**. |
| 5. Secrets | Stores `JWT_SECRET`, `DATABASE_URL`, and optionally `ANTHROPIC_API_KEY` and the demo `STAFF_PASSWORD`, in **Secrets Manager**. |
| 6. IAM | Creates or updates three roles. The execution role reads only this app's secrets. The task role reaches only this bucket and SNS SMS. The Express infrastructure role is the third. |
| 7. Login codes | Checks whether SNS SMS is in the sandbox and chooses the OTP mode (see below). |
| 8. Service | Creates the **ECS Express Mode** service: Fargate with 1 vCPU / 2 GB, HTTPS load balancer, health check `/api/health`, 1–4 tasks scaled on CPU. On later runs it updates the service instead. |
| 9. Wait | Polls the public URL until `/api/health` answers, then prints it. |

The end of the output looks like this:

```text
Vikri Kavach is deployed.
  App:             https://vi-xxxxxxxx.ecs.ap-south-1.on.aws
  Demo officer:    username demo-officer
                   password: aws secretsmanager get-secret-value --secret-id vikrikavach/STAFF_PASSWORD ...
```

Open the URL on a phone to try the farmer view, and log in as `demo-officer` on a laptop for the officer view.

## Options

| Option | Meaning |
|---|---|
| `--demo-apmc CODE` | Creates the demo officer and three sample register entries (clearly named "Demo") for that APMC |
| `--otp sns` | Sends login codes by SMS through Amazon SNS. Use this for real use. |
| `--otp dev` | Shows the login code on screen. **Demos only.** |
| `--ai-key` | Asks for an Anthropic API key (input hidden) and turns on AI slip reading. The key is stored only in Secrets Manager. |
| `--build docker` / `--build codebuild` | Forces where the image is built. The default chooses automatically. |
| `--database-url URL` | Uses an existing PostgreSQL database instead of creating RDS |
| `--db-class CLASS` | RDS size, for example `db.t4g.small` |
| `--region REGION` | Deploys to a region other than CloudShell's current one |
| `--yes` | Asks no questions and uses the defaults |

!!! warning "SMS sandbox"
    New AWS accounts can send SMS only to verified numbers until AWS moves the account out of the SNS SMS sandbox. If the script finds the sandbox, it warns you and offers on-screen codes for a demo. For real farmers, see the [go-live checklist](go-live.md).

## Updating

```bash
cd ~/Vikri-Kavach && git pull && ./cloudshell/deploy.sh
```

This builds a new image and rolls the service with no downtime. The database, secrets and evidence are kept. To add a capability later, re-run with its flag. For example, `./cloudshell/deploy.sh --ai-key` turns on AI slip reading.

## Removing

```bash
./cloudshell/destroy.sh
```

This deletes the service, image repository, build project, secrets and the app's IAM role and permissions. The database is deleted after a **final snapshot**. The **evidence bucket is kept** unless you add `--delete-evidence`. Shared roles stay, with this app's permissions removed. The script asks you to type the app name to confirm.

## Costs

The ongoing costs are the RDS instance, one always-on Fargate task (1 vCPU / 2 GB), the load balancer, and small amounts of S3, Secrets Manager, CloudWatch Logs and SMS. Check current prices for your region on the AWS pricing pages. For a demo, run `destroy.sh` when you are done.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `This region has no default VPC` | Run `aws ec2 create-default-vpc`, then deploy again. |
| The image build failed | Open the CodeBuild link the script prints, or try `--build docker`. |
| `not answering yet` at the end | New load balancers can take a few more minutes. Run `./cloudshell/status.sh`, and `./cloudshell/logs.sh` to see the app. |
| Tasks keep restarting | Run `./cloudshell/logs.sh --since 1h`. A database connection error usually means the database was still starting. Wait and run `deploy.sh` again. |
| An interrupted run | Run `deploy.sh` again. Every step looks up what already exists and continues. |
