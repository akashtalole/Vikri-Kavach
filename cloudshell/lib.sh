# shellcheck shell=bash disable=SC2034
# Shared settings and helpers for the Vikri Kavach CloudShell scripts. Sourced, not run.
# Everything is looked up from AWS by name, so the scripts keep no local state and can be re-run safely.

set -euo pipefail

APP=${APP:-vikrikavach}
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}
REGION=${REGION:-ap-south-1}
export AWS_REGION=$REGION AWS_DEFAULT_REGION=$REGION AWS_PAGER=""

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CLUSTER=default                                  # Express Mode services live in the "default" cluster
DB_ID=$APP-db
DB_SG_NAME=$APP-db-sg
DB_NAME=vikrikavach
DB_USER=vkadmin
EXEC_ROLE=ecsTaskExecutionRole                   # shared, AWS-recommended names
INFRA_ROLE=ecsInfrastructureRoleForExpressServices
TASK_ROLE=$APP-task-role
BUILD_ROLE=$APP-codebuild-role
BUILD_PROJECT=$APP-image-build

if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B='' G='' Y='' R='' N=''; fi
step() { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '%s  ✓ %s%s\n' "$G" "$*" "$N"; }
warn() { printf '%s  ! %s%s\n' "$Y" "$*" "$N" >&2; }
die()  { printf '%s  ✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

need() { for c in "$@"; do command -v "$c" >/dev/null || die "'$c' is not installed (AWS CloudShell has it by default)"; done; }

account_setup() {
  need aws jq python3 curl
  ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
    || die "AWS credentials not found. Run this in AWS CloudShell, or configure the AWS CLI first."
  REPO_URI=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$APP
  BUCKET=${S3_BUCKET:-$APP-evidence-$ACCOUNT-$REGION}
  BUILD_BUCKET=$APP-build-$ACCOUNT-$REGION
}

# "none"-safe lookups ---------------------------------------------------------------
service_arn() {
  aws ecs list-services --cluster "$CLUSTER" --query "serviceArns[?ends_with(@, '/$APP')] | [0]" \
    --output text 2>/dev/null | grep -v '^None$' || true
}
service_url() {
  local arn=${1:-$(service_arn)}
  [ -n "$arn" ] || return 0
  aws ecs describe-express-gateway-service --service-arn "$arn" \
    --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text 2>/dev/null | grep -v '^None$' || true
}
secret_arn() {
  aws secretsmanager describe-secret --secret-id "$APP/$1" --query ARN --output text 2>/dev/null || true
}
put_secret() {  # name value -> prints ARN
  local name="$APP/$1" value="$2"
  if aws secretsmanager describe-secret --secret-id "$name" >/dev/null 2>&1; then
    aws secretsmanager put-secret-value --secret-id "$name" --secret-string "$value" >/dev/null
  else
    aws secretsmanager create-secret --name "$name" --secret-string "$value" \
      --description "Vikri Kavach: $1" >/dev/null
  fi
  secret_arn "$1"
}
get_secret() {
  aws secretsmanager get-secret-value --secret-id "$APP/$1" --query SecretString --output text 2>/dev/null || true
}
https_url() { case "$1" in http*) echo "$1" ;; "") ;; *) echo "https://$1" ;; esac; }

# Express Mode services keep their task definition and network on the active configuration / service revision,
# not on the classic top-level service fields. These helpers try each place in turn.
service_task_def() {  # SERVICE_ARN -> task definition ARN
  local arn=$1 td rev
  td=$(aws ecs describe-express-gateway-service --service-arn "$arn" \
        --query 'service.activeConfigurations[0].taskDefinitionArn' --output text 2>/dev/null || true)
  if [ -z "$td" ] || [ "$td" = None ]; then
    rev=$(service_revision "$arn")
    [ -n "$rev" ] && td=$(jq -r '.taskDefinition // empty' <<<"$rev")
  fi
  if [ -z "$td" ] || [ "$td" = None ]; then
    td=$(aws ecs describe-services --cluster "$CLUSTER" --services "$arn" \
          --query 'services[0].[taskDefinition, deployments[0].taskDefinition] | [?@ != null] | [0]' --output text 2>/dev/null || true)
  fi
  [ -n "$td" ] && [ "$td" != None ] || die "could not find the service's task definition (is the first deployment still in progress? see ./cloudshell/status.sh)"
  echo "$td"
}
service_revision() {  # SERVICE_ARN -> JSON of the active service revision, or nothing
  local rarn
  rarn=$(aws ecs describe-express-gateway-service --service-arn "$1" \
          --query 'service.activeConfigurations[0].serviceRevisionArn' --output text 2>/dev/null || true)
  [ -n "$rarn" ] && [ "$rarn" != None ] || return 0
  aws ecs describe-service-revisions --service-revision-arns "$rarn" --query 'serviceRevisions[0]' 2>/dev/null || true
}
service_network() {  # SERVICE_ARN -> run-task --network-configuration JSON
  local arn=$1 net rev
  rev=$(service_revision "$arn")
  [ -n "$rev" ] && net=$(jq -c '.networkConfiguration // empty' <<<"$rev")
  if [ -z "${net:-}" ] || [ "$net" = null ]; then
    net=$(aws ecs describe-services --cluster "$CLUSTER" --services "$arn" --query 'services[0].networkConfiguration' 2>/dev/null || true)
  fi
  if [ -z "${net:-}" ] || [ "$net" = null ]; then
    net=$(aws ecs describe-express-gateway-service --service-arn "$arn" \
          --query 'service.activeConfigurations[0].networkConfiguration' 2>/dev/null || true)
    [ -n "$net" ] && [ "$net" != null ] && net=$(jq -c '{awsvpcConfiguration: {subnets: .subnets, securityGroups: .securityGroups, assignPublicIp: "ENABLED"}}' <<<"$net")
  fi
  if [ -z "${net:-}" ] || [ "$net" = null ] || [ "$(jq '.awsvpcConfiguration.subnets // [] | length' <<<"$net")" = 0 ]; then
    # last resort: the default VPC's subnets with the default security group
    local vpc subnets sg
    vpc=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
    subnets=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$vpc" Name=default-for-az,Values=true --query 'Subnets[].SubnetId')
    sg=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="$vpc" Name=group-name,Values=default --query 'SecurityGroups[0].GroupId' --output text)
    net=$(jq -cn --argjson s "$subnets" --arg g "$sg" '{awsvpcConfiguration: {subnets: $s, securityGroups: [$g], assignPublicIp: "ENABLED"}}')
  fi
  echo "$net"
}
