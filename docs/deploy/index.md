# Deploy

| Option | Best for | Guide |
|---|---|---|
| **AWS CloudShell → ECS Express Mode** | A real or pilot deployment with HTTPS, a managed database and auto scaling | [One-command deploy](cloudshell.md) |
| **Docker Compose** | A laptop demo or development | [Run locally](local.md) |

After deploying, see [Operating the service](operations.md) to add APMC officers, load licence registers and roll out updates. Before real farmers use it, work through the [go-live checklist](go-live.md).

```mermaid
flowchart LR
    U[Farmers and officers<br/>phone or browser] -->|HTTPS| ALB[Load balancer<br/>created by ECS Express]
    ALB --> T1[Fargate task<br/>app container :8080]
    ALB --> T2[Fargate task<br/>auto scaled 1-4]
    T1 & T2 --> RDS[(RDS PostgreSQL<br/>private)]
    T1 & T2 --> S3[(S3 evidence<br/>private, encrypted)]
    T1 & T2 --> SNS[SNS SMS<br/>login codes]
    T1 & T2 --> SM[Secrets Manager]
    T1 & T2 -.daily.-> MSAMB[msamb.com prices]
```
