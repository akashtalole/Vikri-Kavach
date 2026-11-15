#!/usr/bin/env bash
# One-command deployment of Vikri Kavach to AWS from AWS CloudShell.
#
#   git clone https://github.com/akashtalole/Vikri-Kavach.git && cd Vikri-Kavach
#   ./cloudshell/deploy.sh --demo-apmc 02190400
#
# Creates (or updates, when re-run):
#   RDS PostgreSQL (private, encrypted) · S3 evidence bucket · ECR image · Secrets Manager secrets
#   IAM roles · ECS Express Mode service (Fargate + HTTPS load balancer + auto scaling + logs)
# Re-running after a code change rebuilds the image and rolls the service; the database and secrets are kept.
#
# Options:
#   --region REGION        AWS region (default: CloudShell's region)
#   --demo-apmc CODE       create the demo officer "demo-officer" and sample register for this APMC
#                          (find codes with: ./cloudshell/admin.sh apmc-codes lasalgaon)
#   --otp sns|dev          sns = OTP by SMS (Amazon SNS); dev = OTP shown on screen (demos only)
#   --ai-key               prompt for an Anthropic API key to enable AI slip reading
#   --build auto|docker|codebuild   where to build the image (default auto: Docker if available)
#   --db-class CLASS       RDS instance class (default db.t4g.micro)
#   --database-url URL     use an existing PostgreSQL instead of creating RDS
#   --yes                  do not ask questions; use defaults
source "$(dirname "$0")/lib.sh"

DEMO_APMC="" OTP="" ASK_AI=0 BUILD=auto DB_CLASS=db.t4g.micro EXT_DB="" YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --region) REGION=$2; export AWS_REGION=$2 AWS_DEFAULT_REGION=$2; shift 2 ;;
    --demo-apmc) DEMO_APMC=$2; shift 2 ;;
    --otp) OTP=$2; shift 2 ;;
    --ai-key) ASK_AI=1; shift ;;
    --build) BUILD=$2; shift 2 ;;
    --db-class) DB_CLASS=$2; shift 2 ;;
    --database-url) EXT_DB=$2; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done
interactive() { [ "$YES" = 0 ] && [ -t 0 ]; }
case "$OTP" in ""|sns|dev) ;; *) die "--otp must be sns or dev" ;; esac
case "$BUILD" in auto|docker|codebuild) ;; *) die "--build must be auto, docker or codebuild" ;; esac

account_setup
step "Deploying $APP to account $ACCOUNT in $REGION"

# ---------------------------------------------------------------------------------------------
step "1/9 Network: default VPC"
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
[ "$VPC_ID" != "None" ] || die "This region has no default VPC. Create one with: aws ec2 create-default-vpc"
VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --query 'Vpcs[0].CidrBlock' --output text)
ok "$VPC_ID ($VPC_CIDR)"
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------------------------
step "2/9 Database: PostgreSQL"
if [ -n "$EXT_DB" ]; then
  DB_ARN=$(put_secret DATABASE_URL "$EXT_DB"); ok "using the database URL you gave"
elif [ -n "$(secret_arn DATABASE_URL)" ] && aws rds describe-db-instances --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
  DB_ARN=$(secret_arn DATABASE_URL); ok "RDS $DB_ID already set up"
elif [ -n "$(secret_arn DATABASE_URL)" ] && [ -z "$(secret_arn DB_MASTER_PASSWORD)" ]; then
  DB_ARN=$(secret_arn DATABASE_URL); ok "using the external database URL saved earlier"
else
  SG_ID=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$DB_SG_NAME" \
    --query 'SecurityGroups[0].GroupId' --output text)
  if [ "$SG_ID" = "None" ]; then
    SG_ID=$(aws ec2 create-security-group --group-name "$DB_SG_NAME" --vpc-id "$VPC_ID" \
      --description "Vikri Kavach database: PostgreSQL from inside the VPC only" --query GroupId --output text)
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 5432 --cidr "$VPC_CIDR" >/dev/null
  fi
  if ! aws rds describe-db-instances --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
    DB_PASS=$(get_secret DB_MASTER_PASSWORD)
    if [ -z "$DB_PASS" ]; then DB_PASS=$(openssl rand -hex 24); put_secret DB_MASTER_PASSWORD "$DB_PASS" >/dev/null; fi
    aws rds create-db-instance --db-instance-identifier "$DB_ID" --engine postgres \
      --db-instance-class "$DB_CLASS" --allocated-storage 20 --storage-type gp3 --storage-encrypted \
      --master-username "$DB_USER" --master-user-password "$DB_PASS" --db-name "$DB_NAME" \
      --vpc-security-group-ids "$SG_ID" --no-publicly-accessible --backup-retention-period 7 \
      --copy-tags-to-snapshot --deletion-protection --tags Key=app,Value="$APP" >/dev/null
    ok "creating RDS $DB_ID ($DB_CLASS); this takes 5-15 minutes"
  fi
  DB_PASS=$(get_secret DB_MASTER_PASSWORD)
  [ -n "$DB_PASS" ] || die "RDS $DB_ID exists but its password secret $APP/DB_MASTER_PASSWORD is missing"
  printf '  waiting for the database'
  until [ "$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
            --query 'DBInstances[0].DBInstanceStatus' --output text)" = available ]; do printf '.'; sleep 20; done; echo
  DB_HOST=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --query 'DBInstances[0].Endpoint.Address' --output text)
  DB_ARN=$(put_secret DATABASE_URL "postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/$DB_NAME?sslmode=require")
  ok "RDS ready at $DB_HOST (private; reachable only from inside the VPC)"
fi

# ---------------------------------------------------------------------------------------------
step "3/9 Evidence storage: s3://$BUCKET"
make_bucket() {
  if ! aws s3api head-bucket --bucket "$1" 2>/dev/null; then
    if [ "$REGION" = us-east-1 ]; then aws s3api create-bucket --bucket "$1" >/dev/null
    else aws s3api create-bucket --bucket "$1" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null; fi
  fi
  aws s3api put-public-access-block --bucket "$1" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$1" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
}
make_bucket "$BUCKET"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
ok "private, encrypted, versioned"

# ---------------------------------------------------------------------------------------------
step "4/9 Container image"
aws ecr describe-repositories --repository-names "$APP" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$APP" --image-scanning-configuration scanOnPush=true >/dev/null
aws ecr put-lifecycle-policy --repository-name "$APP" --lifecycle-policy-text \
  '{"rules":[{"rulePriority":1,"description":"keep 10 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' >/dev/null
TAG=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo build)-$(date +%Y%m%d%H%M%S)
IMAGE=$REPO_URI:$TAG
if [ "$BUILD" = auto ]; then
  if docker info >/dev/null 2>&1 && [ "$(df -Pk / | awk 'NR==2{print $4}')" -gt 3000000 ]; then
    BUILD=docker
  else
    BUILD=codebuild
  fi
fi
if [ "$BUILD" = docker ]; then
  ok "building with Docker in CloudShell"
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%/*}" >/dev/null
  docker build --platform linux/amd64 -t "$IMAGE" "$ROOT"
  docker push "$IMAGE" >/dev/null
  docker image rm "$IMAGE" >/dev/null 2>&1 || true   # CloudShell disk is small
else
  ok "building with AWS CodeBuild (no local Docker needed)"
  need zip
  make_bucket "$BUILD_BUCKET"
  if ! aws iam get-role --role-name "$BUILD_ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$BUILD_ROLE" --assume-role-policy-document \
      '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    sleep 10
  fi
  aws iam put-role-policy --role-name "$BUILD_ROLE" --policy-name build --policy-document "$(jq -n \
    --arg repo "arn:aws:ecr:$REGION:$ACCOUNT:repository/$APP" --arg src "arn:aws:s3:::$BUILD_BUCKET/*" '
    {Version:"2012-10-17",Statement:[
      {Effect:"Allow",Action:["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],Resource:"*"},
      {Effect:"Allow",Action:"ecr:GetAuthorizationToken",Resource:"*"},
      {Effect:"Allow",Action:["ecr:BatchCheckLayerAvailability","ecr:InitiateLayerUpload","ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload","ecr:PutImage","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],Resource:$repo},
      {Effect:"Allow",Action:["s3:GetObject","s3:GetObjectVersion"],Resource:$src}]}')"
  SRC_ZIP=$(mktemp -u /tmp/$APP-src-XXXX).zip
  (cd "$ROOT" && zip -qr "$SRC_ZIP" . -x '.git/*' '*/node_modules/*' '*/dist/*' '*/var/*' 'docs/*' '*/__pycache__/*')
  aws s3 cp "$SRC_ZIP" "s3://$BUILD_BUCKET/source.zip" --only-show-errors && rm -f "$SRC_ZIP"
  BUILDSPEC=$(cat <<'YAML'
version: 0.2
phases:
  pre_build:
    commands:
      - aws ecr get-login-password | docker login --username AWS --password-stdin "${IMAGE%%/*}"
  build:
    commands:
      - docker build -t "$IMAGE" .
      - docker push "$IMAGE"
YAML
)
  PROJECT_ARGS=(--source "$(jq -n --arg loc "$BUILD_BUCKET/source.zip" --arg spec "$BUILDSPEC" '{type:"S3",location:$loc,buildspec:$spec}')"
    --artifacts type=NO_ARTIFACTS
    --environment '{"type":"LINUX_CONTAINER","image":"aws/codebuild/amazonlinux-x86_64-standard:5.0","computeType":"BUILD_GENERAL1_MEDIUM","privilegedMode":true}'
    --service-role "arn:aws:iam::$ACCOUNT:role/$BUILD_ROLE")
  if aws codebuild batch-get-projects --names "$BUILD_PROJECT" --query 'projects[0].name' --output text | grep -q "$BUILD_PROJECT"; then
    aws codebuild update-project --name "$BUILD_PROJECT" "${PROJECT_ARGS[@]}" >/dev/null
  else
    for i in 1 2 3 4; do  # a new IAM role can take a few seconds before CodeBuild accepts it
      aws codebuild create-project --name "$BUILD_PROJECT" "${PROJECT_ARGS[@]}" >/dev/null 2>&1 && break
      [ $i = 4 ] && aws codebuild create-project --name "$BUILD_PROJECT" "${PROJECT_ARGS[@]}" >/dev/null; sleep 10
    done
  fi
  BUILD_ID=$(aws codebuild start-build --project-name "$BUILD_PROJECT" \
    --environment-variables-override name=IMAGE,value="$IMAGE" --query build.id --output text)
  printf '  building %s' "$BUILD_ID"
  while :; do
    ST=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --query 'builds[0].buildStatus' --output text)
    [ "$ST" = IN_PROGRESS ] || break; printf '.'; sleep 15
  done; echo
  [ "$ST" = SUCCEEDED ] || die "image build $ST. Logs: https://$REGION.console.aws.amazon.com/codesuite/codebuild/projects/$BUILD_PROJECT/history"
fi
ok "$IMAGE"

# ---------------------------------------------------------------------------------------------
step "5/9 Secrets (AWS Secrets Manager)"
JWT_ARN=$(secret_arn JWT_SECRET); [ -n "$JWT_ARN" ] || JWT_ARN=$(put_secret JWT_SECRET "$(openssl rand -hex 32)")
SECRETS=$(jq -n --arg j "$JWT_ARN" --arg d "$DB_ARN" '[{name:"JWT_SECRET",valueFrom:$j},{name:"DATABASE_URL",valueFrom:$d}]')
if [ "$ASK_AI" = 1 ] && interactive; then
  read -rsp "  Anthropic API key (input hidden, empty to skip): " KEY; echo
  [ -n "$KEY" ] && put_secret ANTHROPIC_API_KEY "$KEY" >/dev/null
fi
[ -n "${ANTHROPIC_API_KEY:-}" ] && put_secret ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY" >/dev/null
AI_ARN=$(secret_arn ANTHROPIC_API_KEY)
[ -n "$AI_ARN" ] && SECRETS=$(jq --arg a "$AI_ARN" '. + [{name:"ANTHROPIC_API_KEY",valueFrom:$a}]' <<<"$SECRETS") \
  && ok "AI slip reading on" || ok "AI slip reading off (re-run with --ai-key to turn it on)"
if [ -n "$DEMO_APMC" ]; then
  [ -n "$(secret_arn STAFF_PASSWORD)" ] || put_secret STAFF_PASSWORD "$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)" >/dev/null
  SECRETS=$(jq --arg p "$(secret_arn STAFF_PASSWORD)" '. + [{name:"STAFF_PASSWORD",valueFrom:$p}]' <<<"$SECRETS")
fi
ok "$(jq -r 'map(.name) | join(", ")' <<<"$SECRETS")"

# ---------------------------------------------------------------------------------------------
step "6/9 IAM roles"
ensure_role() {  # name service [managed-policy] -> ARN
  if ! aws iam get-role --role-name "$1" >/dev/null 2>&1; then
    aws iam create-role --role-name "$1" --assume-role-policy-document "$(jq -n --arg s "$2" \
      '{Version:"2012-10-17",Statement:[{Effect:"Allow",Principal:{Service:$s},Action:"sts:AssumeRole"}]}')" >/dev/null
  fi
  [ -n "${3:-}" ] && aws iam attach-role-policy --role-name "$1" --policy-arn "$3"
  aws iam get-role --role-name "$1" --query Role.Arn --output text
}
EXEC_ARN=$(ensure_role "$EXEC_ROLE" ecs-tasks.amazonaws.com arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy)
aws iam put-role-policy --role-name "$EXEC_ROLE" --policy-name "$APP-read-secrets" --policy-document "$(jq -n \
  --arg r "arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:$APP/*" \
  '{Version:"2012-10-17",Statement:[{Effect:"Allow",Action:"secretsmanager:GetSecretValue",Resource:$r}]}')"
INFRA_ARN=$(ensure_role "$INFRA_ROLE" ecs.amazonaws.com \
  arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices)
TASK_ARN=$(ensure_role "$TASK_ROLE" ecs-tasks.amazonaws.com)
aws iam put-role-policy --role-name "$TASK_ROLE" --policy-name "$APP-app" --policy-document "$(jq -n \
  --arg b "arn:aws:s3:::$BUCKET/*" '{Version:"2012-10-17",Statement:[
    {Sid:"Evidence",Effect:"Allow",Action:["s3:PutObject","s3:GetObject","s3:DeleteObject"],Resource:$b},
    {Sid:"OtpSms",Effect:"Allow",Action:"sns:Publish",Resource:"*"}]}')"
ok "execution, infrastructure and task roles"

# ---------------------------------------------------------------------------------------------
step "7/9 Login codes (OTP)"
SANDBOX=$(aws sns get-sms-sandbox-account-status --query IsInSandbox --output text 2>/dev/null || echo unknown)
if [ -z "$OTP" ]; then
  OTP=sns
  if [ "$SANDBOX" = True ]; then
    warn "This account's SNS SMS is in the sandbox: real farmers will not receive codes until AWS moves it out"
    warn "(SNS console > Text messaging > Exit SMS sandbox; India also needs DLT sender registration)."
    if interactive; then
      read -rp "  Show codes on screen for a demo instead? [Y/n] " A; [ "${A:-Y}" = n ] || [ "${A:-Y}" = N ] || OTP=dev
    else OTP=dev; fi
  fi
fi
[ "$OTP" = dev ] && warn "OTP_MODE=dev: login codes are shown on screen. Use only for demos." || ok "codes sent by SMS"

# ---------------------------------------------------------------------------------------------
step "8/9 ECS Express Mode service"
ENV=$(jq -n --arg otp "$OTP" --arg b "$BUCKET" --arg r "$REGION" --arg demo "$DEMO_APMC" '
  [{name:"APP_ENV",value:"production"},{name:"OTP_MODE",value:$otp},{name:"S3_BUCKET",value:$b},
   {name:"AWS_REGION",value:$r},{name:"ENABLE_SCHEDULER",value:"true"},{name:"WEB_CONCURRENCY",value:"2"}]
  + (if $demo != "" then [{name:"DEMO_APMC_CODE",value:$demo}] else [] end)')
CONTAINER=$(jq -n --arg img "$IMAGE" --argjson env "$ENV" --argjson sec "$SECRETS" \
  '{image:$img,containerPort:8080,environment:$env,secrets:$sec}')
SCALING='{"minTaskCount":1,"maxTaskCount":4,"autoScalingMetric":"AVERAGE_CPU","autoScalingTargetValue":60}'
SVC=$(service_arn)
if [ -n "$SVC" ]; then
  aws ecs update-express-gateway-service --service-arn "$SVC" --execution-role-arn "$EXEC_ARN" \
    --task-role-arn "$TASK_ARN" --primary-container "$CONTAINER" --health-check-path /api/health \
    --scaling-target "$SCALING" >/dev/null
  ok "rolling out the new version"
else
  for i in 1 2 3 4 5; do  # new IAM roles can take a little while to be usable by ECS
    if OUT=$(aws ecs create-express-gateway-service --service-name "$APP" --execution-role-arn "$EXEC_ARN" \
        --infrastructure-role-arn "$INFRA_ARN" --task-role-arn "$TASK_ARN" --primary-container "$CONTAINER" \
        --health-check-path /api/health --cpu 1024 --memory 2048 --scaling-target "$SCALING" \
        --tags key=app,value="$APP" 2>&1); then break; fi
    [ $i = 5 ] && die "could not create the service: $OUT"
    warn "retrying in 15s ($(head -c 160 <<<"$OUT"))"; sleep 15
  done
  SVC=$(jq -r .service.serviceArn <<<"$OUT")
  ok "created $SVC"
fi

# ---------------------------------------------------------------------------------------------
step "9/9 Waiting for the app to answer"
URL=""
for _ in $(seq 1 90); do
  URL=$(https_url "$(service_url "$SVC")")
  if [ -n "$URL" ] && curl -fsS -m 5 "$URL/api/health" >/dev/null 2>&1; then
    if [ "$(curl -fsS -m 5 "$URL/api/health" | jq -r .ok)" = true ]; then break; fi
  fi
  printf '.'; sleep 20
done; echo
if [ -n "$URL" ] && curl -fsS -m 5 "$URL/api/health" >/dev/null 2>&1; then
  ok "healthy: $(curl -fsS -m 5 "$URL/api/health")"
else
  warn "not answering yet. New load balancers can take a few more minutes; check with ./cloudshell/status.sh"
fi

cat <<EOF

${B}Vikri Kavach is deployed.${N}
  App:             ${URL:-"(URL appears in ./cloudshell/status.sh once ready)"}
  Farmers log in with a mobile number$( [ "$OTP" = dev ] && echo " (demo mode: the code is shown on screen)").
EOF
if [ -n "$DEMO_APMC" ]; then
cat <<EOF
  Demo officer:    username demo-officer
                   password: aws secretsmanager get-secret-value --secret-id $APP/STAFF_PASSWORD --query SecretString --output text
EOF
fi
cat <<EOF

  Next steps
    ./cloudshell/status.sh                          service, database and health
    ./cloudshell/logs.sh                            follow the app logs
    ./cloudshell/admin.sh create-staff --username lasalgaon-secretary --apmc-code 02190400
    ./cloudshell/admin.sh import-traders --apmc-code 02190400 register.csv
    ./cloudshell/deploy.sh                          re-run after a code change (git pull first)
    ./cloudshell/destroy.sh                         remove everything
EOF
