#!/usr/bin/env bash
# Show the state of a Vikri Kavach deployment: URL, health, service, tasks, database, image.
source "$(dirname "$0")/lib.sh"
account_setup

step "Vikri Kavach in $REGION (account $ACCOUNT)"
SVC=$(service_arn)
if [ -z "$SVC" ]; then warn "no service deployed. Run ./cloudshell/deploy.sh"; else
  D=$(aws ecs describe-express-gateway-service --service-arn "$SVC")
  URL=$(https_url "$(jq -r '.service.activeConfigurations[0].ingressPaths[0].endpoint // empty' <<<"$D")")
  echo "  URL:       ${URL:-pending}"
  echo "  Service:   $(jq -r '.service.status.statusCode + " " + (.service.status.statusReason // "")' <<<"$D")"
  echo "  Image:     $(jq -r '.service.activeConfigurations[0].primaryContainer.image // "?"' <<<"$D")"
  S=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" --query 'services[0]')
  echo "  Tasks:     $(jq -r '"\(.runningCount) running / \(.desiredCount) desired, \(.pendingCount) pending"' <<<"$S")"
  echo "  Rollout:   $(jq -r '.deployments[0] | "\(.rolloutState // .status) \(.rolloutStateReason // "")"' <<<"$S")"
  if [ -n "$URL" ]; then
    H=$(curl -fsS -m 8 "$URL/api/health" 2>/dev/null) && ok "health: $H" || warn "health check did not answer"
  fi
  jq -r '.events[:5][] | "  event: \(.createdAt | tostring | .[0:19]) \(.message)"' <<<"$S" 2>/dev/null || true
fi
DB=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
  --query 'DBInstances[0].[DBInstanceStatus,DBInstanceClass,Engine,EngineVersion]' --output text 2>/dev/null || true)
echo "  Database:  ${DB:-not an RDS instance created by these scripts}"
echo "  Evidence:  s3://$BUCKET"
