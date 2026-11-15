#!/usr/bin/env bash
# Remove a Vikri Kavach deployment.
#   ./cloudshell/destroy.sh                     keeps a final database snapshot and the evidence bucket
#   ./cloudshell/destroy.sh --delete-evidence   also empties and deletes the evidence bucket (cannot be undone)
#   ./cloudshell/destroy.sh --no-snapshot       deletes the database without a final snapshot (cannot be undone)
# Shared roles (ecsTaskExecutionRole, ecsInfrastructureRoleForExpressServices) are kept; only this app's
# permissions are removed from them.
source "$(dirname "$0")/lib.sh"
DELETE_EVIDENCE=0 SNAPSHOT=1 YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --delete-evidence) DELETE_EVIDENCE=1; shift ;; --no-snapshot) SNAPSHOT=0; shift ;; --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;; *) die "unknown option $1" ;;
  esac
done
account_setup

step "This removes Vikri Kavach from account $ACCOUNT in $REGION:"
echo "  ECS Express service, image repository, build project, secrets, app IAM role,"
echo "  RDS $DB_ID $([ $SNAPSHOT = 1 ] && echo "(a final snapshot is kept)" || echo "(NO snapshot)")"
echo "  evidence bucket s3://$BUCKET: $([ $DELETE_EVIDENCE = 1 ] && echo DELETED || echo kept)"
if [ "$YES" = 0 ]; then
  read -rp "Type the app name ($APP) to confirm: " A; [ "$A" = "$APP" ] || die "cancelled"
fi

SVC=$(service_arn)
if [ -n "$SVC" ]; then
  step "Deleting the ECS Express service (also removes its load balancer and scaling)"
  aws ecs delete-express-gateway-service --service-arn "$SVC" >/dev/null
  until [ -z "$(service_arn)" ] || [ "$(aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" \
         --query 'services[0].status' --output text)" = INACTIVE ]; do printf '.'; sleep 15; done; echo
  ok "service deleted"
fi

if aws rds describe-db-instances --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
  step "Deleting RDS $DB_ID"
  aws rds modify-db-instance --db-instance-identifier "$DB_ID" --no-deletion-protection --apply-immediately >/dev/null
  sleep 10
  if [ $SNAPSHOT = 1 ]; then
    SNAP=$DB_ID-final-$(date +%Y%m%d%H%M)
    aws rds delete-db-instance --db-instance-identifier "$DB_ID" --final-db-snapshot-identifier "$SNAP" >/dev/null
    ok "final snapshot: $SNAP"
  else
    aws rds delete-db-instance --db-instance-identifier "$DB_ID" --skip-final-snapshot --delete-automated-backups >/dev/null
  fi
  printf '  waiting for the database to be deleted'
  aws rds wait db-instance-deleted --db-instance-identifier "$DB_ID"; echo
  ok "database deleted"
fi
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$DB_SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)
[ "$SG_ID" != None ] && aws ec2 delete-security-group --group-id "$SG_ID" && ok "database security group deleted"

step "Deleting image repository, build project and secrets"
aws ecr delete-repository --repository-name "$APP" --force >/dev/null 2>&1 && ok "ECR $APP" || true
aws codebuild delete-project --name "$BUILD_PROJECT" >/dev/null 2>&1 && ok "CodeBuild $BUILD_PROJECT" || true
if aws s3api head-bucket --bucket "$BUILD_BUCKET" 2>/dev/null; then
  aws s3 rb "s3://$BUILD_BUCKET" --force >/dev/null && ok "build bucket"
fi
for s in JWT_SECRET DATABASE_URL DB_MASTER_PASSWORD ANTHROPIC_API_KEY STAFF_PASSWORD; do
  aws secretsmanager delete-secret --secret-id "$APP/$s" --force-delete-without-recovery >/dev/null 2>&1 && ok "secret $APP/$s" || true
done

step "Removing this app's IAM permissions"
aws iam delete-role-policy --role-name "$EXEC_ROLE" --policy-name "$APP-read-secrets" 2>/dev/null || true
for r in "$TASK_ROLE" "$BUILD_ROLE"; do
  if aws iam get-role --role-name "$r" >/dev/null 2>&1; then
    for p in $(aws iam list-role-policies --role-name "$r" --query PolicyNames --output text); do
      aws iam delete-role-policy --role-name "$r" --policy-name "$p"; done
    aws iam delete-role --role-name "$r" && ok "role $r"
  fi
done

if [ $DELETE_EVIDENCE = 1 ] && aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  step "Deleting evidence bucket s3://$BUCKET (all versions)"
  while :; do
    BATCH=$(aws s3api list-object-versions --bucket "$BUCKET" --max-items 500 --output json \
      --query '{Objects: [Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId}, Quiet: `true`}')
    [ "$(jq '.Objects // [] | length' <<<"$BATCH")" = 0 ] && break
    aws s3api delete-objects --bucket "$BUCKET" --delete "$BATCH" >/dev/null
  done
  aws s3 rb "s3://$BUCKET" && ok "evidence bucket deleted"
fi
step "Done."
