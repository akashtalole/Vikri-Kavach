#!/usr/bin/env bash
# Admin tasks for a deployed Vikri Kavach. The database is private inside the VPC, so each command runs as a
# one-off ECS task using the same image, network and secrets as the live service, and prints its output here.
#
#   ./cloudshell/admin.sh apmc-codes [search]                     find an APMC's code (runs locally)
#   ./cloudshell/admin.sh create-staff --username NAME --apmc-code CODE [--name "Full name"] [--role officer|admin]
#                                                                 create an officer, or reset their password
#   ./cloudshell/admin.sh import-traders --apmc-code CODE FILE.csv load the APMC licence register
#                                                                 (CSV columns: licence_no,name,firm,status)
#   ./cloudshell/admin.sh seed-demo --apmc-code CODE              demo officer + sample register (needs a
#                                                                 deployment made with --demo-apmc)
#   ./cloudshell/admin.sh daily                                   run the daily price and overdue jobs now
source "$(dirname "$0")/lib.sh"

CMD=${1:-}; [ -n "$CMD" ] && shift || true

if [ "$CMD" = apmc-codes ]; then
  python3 - "$ROOT/bhavsetu/src/bhavsetu/data/apmc_master.json" "${1:-}" <<'PY'
import json, sys
q = sys.argv[2].lower()
rows = [a for a in json.load(open(sys.argv[1], encoding="utf-8"))["apmcs"]
        if not q or q in (a["name_en"] + " " + a["district_en"] + " " + a["name_mr"]).lower()]
for a in sorted(rows, key=lambda a: (a["district_en"], a["name_en"])):
    print(f'{a["full_code"]}  {a["name_en"]:<34} {a["district_en"]:<16} {a["name_mr"]}')
print(f"{len(rows)} APMC(s)", file=sys.stderr)
PY
  exit 0
fi

account_setup
SVC=$(service_arn); [ -n "$SVC" ] || die "no deployed service named $APP in $REGION. Run ./cloudshell/deploy.sh first."

run_task() {  # args: the vikrikavach CLI command line
  local desc td net container overrides task group prefix code
  desc=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SVC" --query 'services[0]')
  td=$(jq -r .taskDefinition <<<"$desc")
  net=$(jq -c '.networkConfiguration' <<<"$desc")
  container=$(aws ecs describe-task-definition --task-definition "$td" --query 'taskDefinition.containerDefinitions[0]')
  overrides=$(printf '%s\0' vikrikavach "$@" | jq -Rs --arg n "$(jq -r .name <<<"$container")" \
    '{containerOverrides:[{name:$n,command:(split("\u0000")[:-1])}]}')
  step "Running: vikrikavach $(printf '%q ' "$@" | sed -E 's/scrypt[^ ]+/scrypt…(hidden)/')"
  task=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$td" --launch-type FARGATE \
    --network-configuration "$net" --overrides "$overrides" --started-by "$APP-admin" --query 'tasks[0].taskArn' --output text)
  [ "$task" != None ] || die "could not start the task"
  printf '  task %s' "${task##*/}"
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task"; echo
  code=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" --query 'tasks[0].containers[0].exitCode' --output text)
  group=$(jq -r '.logConfiguration.options["awslogs-group"] // empty' <<<"$container")
  prefix=$(jq -r '.logConfiguration.options["awslogs-stream-prefix"] // empty' <<<"$container")
  if [ -n "$group" ]; then
    sleep 3
    aws logs get-log-events --log-group-name "$group" --start-from-head \
      --log-stream-name "$prefix/$(jq -r .name <<<"$container")/${task##*/}" --query 'events[].message' --output text \
      2>/dev/null | tr '\t' '\n' || warn "no log output found"
  fi
  [ "$code" = 0 ] && ok "done" || die "task exited with code $code ($(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" --query 'tasks[0].stoppedReason' --output text))"
}

case "$CMD" in
  create-staff)
    ARGS=("$@")
    printf '%s\n' "${ARGS[@]}" | grep -qx -- --username || die "usage: create-staff --username NAME --apmc-code CODE [--name N] [--role officer|admin]"
    read -rsp "New password for this staff account (10+ characters, input hidden): " PW; echo
    read -rsp "Repeat password: " PW2; echo
    [ "$PW" = "$PW2" ] || die "passwords do not match"
    # Hash here in CloudShell so the plain password never leaves this terminal (same scrypt format as the app).
    HASH=$(PW="$PW" python3 -c '
import hashlib, os, sys
pw = os.environ["PW"]
if len(pw) < 10: sys.exit("password must be at least 10 characters")
salt = os.urandom(16)
print(f"scrypt${salt.hex()}${hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()}")') || exit 1
    run_task create-staff "${ARGS[@]}" --password-hash "$HASH"
    ;;
  import-traders)
    FILE=${*: -1}; [ -f "$FILE" ] || die "usage: import-traders --apmc-code CODE FILE.csv"
    head -1 "$FILE" | grep -q licence_no || die "the CSV header must include licence_no,name,firm,status"
    KEY="admin/import-$(date +%s)-$RANDOM.csv"
    aws s3 cp "$FILE" "s3://$BUCKET/$KEY" --only-show-errors
    trap 'aws s3 rm "s3://$BUCKET/$KEY" --only-show-errors' EXIT
    run_task import-traders "${@:1:$#-1}" "s3://$BUCKET/$KEY"
    ;;
  seed-demo|daily) run_task "$CMD" "$@" ;;
  ""|-h|--help) sed -n '2,14p' "$0" ;;
  *) die "unknown command $CMD (see --help)" ;;
esac
