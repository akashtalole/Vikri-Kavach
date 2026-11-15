#!/usr/bin/env bash
# Follow the app's logs (CloudWatch). Usage: ./cloudshell/logs.sh [--since 1h] [--no-follow]
source "$(dirname "$0")/lib.sh"
account_setup
SINCE=30m FOLLOW=--follow
while [ $# -gt 0 ]; do
  case "$1" in --since) SINCE=$2; shift 2 ;; --no-follow) FOLLOW=""; shift ;; *) die "unknown option $1" ;; esac
done
SVC=$(service_arn); [ -n "$SVC" ] || die "no deployed service named $APP in $REGION"
TD=$(service_task_def "$SVC")
GROUP=$(aws ecs describe-task-definition --task-definition "$TD" \
  --query 'taskDefinition.containerDefinitions[0].logConfiguration.options."awslogs-group"' --output text)
[ "$GROUP" != None ] || die "the service has no CloudWatch log group configured"
step "Logs from $GROUP (since $SINCE)"
aws logs tail "$GROUP" --since "$SINCE" $FOLLOW --format short
