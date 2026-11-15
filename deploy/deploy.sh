#!/usr/bin/env bash
# Deploy Vikri Kavach to Amazon ECS Express Mode.
#
# Express Mode creates the cluster, Fargate service, HTTPS load balancer, security groups, logs and auto scaling
# from one command, and returns a public https URL. This script adds what the app itself needs:
#   ECR repository + image, S3 evidence bucket, Secrets Manager secrets, the IAM roles, then the Express service.
#
# Before running: an RDS PostgreSQL database reachable from the default VPC, and its URL in DATABASE_URL, e.g.
#   export DATABASE_URL='postgresql://user:password@mydb.xxxx.ap-south-1.rds.amazonaws.com:5432/vikrikavach'
# Optional: ANTHROPIC_API_KEY (AI slip reading), DEMO_APMC_CODE + STAFF_PASSWORD (demo officer account).
#
# Usage (from the repository root):  vikrikavach/deploy/deploy.sh
set -euo pipefail

APP=${APP:-vikrikavach}
REGION=${AWS_REGION:-ap-south-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
TAG=${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%s)}
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$APP"
BUCKET=${S3_BUCKET:-$APP-evidence-$ACCOUNT-$REGION}
EXEC_ROLE=ecsTaskExecutionRole
INFRA_ROLE=ecsInfrastructureRoleForExpressServices
TASK_ROLE=$APP-task-role
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
aws() { command aws --region "$REGION" "$@"; }
say() { printf '\n== %s\n' "$*"; }

: "${DATABASE_URL:?Set DATABASE_URL to your RDS PostgreSQL URL}"

say "Image: build and push $REPO:$TAG"
aws ecr describe-repositories --repository-names "$APP" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$APP" --image-scanning-configuration scanOnPush=true >/dev/null
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%/*}"
docker build --platform linux/amd64 -f "$ROOT/vikrikavach/Dockerfile" -t "$REPO:$TAG" "$ROOT"
docker push "$REPO:$TAG"

say "Evidence bucket: s3://$BUCKET (private, encrypted)"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

say "Secrets in AWS Secrets Manager"
put_secret() {  # name value -> prints ARN
  local name="$APP/$1" value="$2"
  if aws secretsmanager describe-secret --secret-id "$name" >/dev/null 2>&1; then
    aws secretsmanager put-secret-value --secret-id "$name" --secret-string "$value" >/dev/null
  else
    aws secretsmanager create-secret --name "$name" --secret-string "$value" >/dev/null
  fi
  aws secretsmanager describe-secret --secret-id "$name" --query ARN --output text
}
if ! aws secretsmanager describe-secret --secret-id "$APP/JWT_SECRET" >/dev/null 2>&1; then
  JWT_ARN=$(put_secret JWT_SECRET "$(openssl rand -hex 32)")
else
  JWT_ARN=$(aws secretsmanager describe-secret --secret-id "$APP/JWT_SECRET" --query ARN --output text)
fi
DB_ARN=$(put_secret DATABASE_URL "$DATABASE_URL")
SECRETS="{\"name\":\"JWT_SECRET\",\"valueFrom\":\"$JWT_ARN\"},{\"name\":\"DATABASE_URL\",\"valueFrom\":\"$DB_ARN\"}"
SECRET_ARNS="\"$JWT_ARN\",\"$DB_ARN\""
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  AI_ARN=$(put_secret ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY")
  SECRETS="$SECRETS,{\"name\":\"ANTHROPIC_API_KEY\",\"valueFrom\":\"$AI_ARN\"}"; SECRET_ARNS="$SECRET_ARNS,\"$AI_ARN\""
fi
if [ -n "${STAFF_PASSWORD:-}" ]; then
  PW_ARN=$(put_secret STAFF_PASSWORD "$STAFF_PASSWORD")
  SECRETS="$SECRETS,{\"name\":\"STAFF_PASSWORD\",\"valueFrom\":\"$PW_ARN\"}"; SECRET_ARNS="$SECRET_ARNS,\"$PW_ARN\""
fi

say "IAM roles"
ensure_role() {  # role-name service managed-policy-arn
  if ! aws iam get-role --role-name "$1" >/dev/null 2>&1; then
    aws iam create-role --role-name "$1" --assume-role-policy-document \
      "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"$2\"},\"Action\":\"sts:AssumeRole\"}]}" >/dev/null
  fi
  [ -n "${3:-}" ] && aws iam attach-role-policy --role-name "$1" --policy-arn "$3"
  aws iam get-role --role-name "$1" --query Role.Arn --output text
}
EXEC_ARN=$(ensure_role $EXEC_ROLE ecs-tasks.amazonaws.com arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy)
aws iam put-role-policy --role-name $EXEC_ROLE --policy-name "$APP-read-secrets" --policy-document \
  "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":[$SECRET_ARNS]}]}"
INFRA_ARN=$(ensure_role $INFRA_ROLE ecs.amazonaws.com arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices)
TASK_ARN=$(ensure_role "$TASK_ROLE" ecs-tasks.amazonaws.com)
sed "s/BUCKET_NAME/$BUCKET/" "$ROOT/vikrikavach/deploy/task-role-policy.json" > /tmp/$APP-task-policy.json
aws iam put-role-policy --role-name "$TASK_ROLE" --policy-name "$APP-app" --policy-document file:///tmp/$APP-task-policy.json
sleep 10  # new IAM roles take a few seconds to be usable

ENV="{\"name\":\"APP_ENV\",\"value\":\"production\"},{\"name\":\"OTP_MODE\",\"value\":\"${OTP_MODE:-sns}\"},\
{\"name\":\"S3_BUCKET\",\"value\":\"$BUCKET\"},{\"name\":\"AWS_REGION\",\"value\":\"$REGION\"},\
{\"name\":\"ENABLE_SCHEDULER\",\"value\":\"true\"},{\"name\":\"WEB_CONCURRENCY\",\"value\":\"2\"}"
[ -n "${DEMO_APMC_CODE:-}" ] && ENV="$ENV,{\"name\":\"DEMO_APMC_CODE\",\"value\":\"$DEMO_APMC_CODE\"}"
CONTAINER="{\"image\":\"$REPO:$TAG\",\"containerPort\":8080,\"environment\":[$ENV],\"secrets\":[$SECRETS]}"

service_arn() { aws ecs list-services --cluster default --query "serviceArns[?ends_with(@, '/$APP')] | [0]" --output text 2>/dev/null | grep -v None || true; }
SERVICE_ARN=$(service_arn)
if [ -n "$SERVICE_ARN" ]; then
  say "Updating Express service $APP"
  aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" \
    --primary-container "$CONTAINER" >/dev/null
else
  say "Creating Express service $APP"
  aws ecs create-express-gateway-service --service-name "$APP" \
    --execution-role-arn "$EXEC_ARN" --infrastructure-role-arn "$INFRA_ARN" --task-role-arn "$TASK_ARN" \
    --primary-container "$CONTAINER" --health-check-path /api/health --cpu 1024 --memory 2048 \
    --scaling-target '{"minTaskCount":1,"maxTaskCount":4,"autoScalingMetric":"AVERAGE_CPU","autoScalingTargetValue":60}' >/dev/null
  SERVICE_ARN=$(service_arn)
fi

say "Done. Service URL (ready in a few minutes):"
aws ecs describe-express-gateway-service --service-arn "$SERVICE_ARN" \
  --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text 2>/dev/null \
  || echo "See the ECS console: Clusters > default > $APP"
