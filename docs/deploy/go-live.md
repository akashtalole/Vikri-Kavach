# Going live checklist

Use this list before real farmers rely on the service.

## Access and messaging

- [ ] **Move SNS SMS out of the sandbox.** In the SNS console, go to **Text messaging (SMS) → Exit SMS sandbox**, and set a monthly SMS spending limit.
- [ ] **India:** register the sender ID and the OTP message template on the **DLT** platform, as TRAI requires. Then configure them for SNS.
- [ ] Deploy with `--otp sns`, and check that a code arrives on a real phone.
- [ ] Deploy **without** `--demo-apmc`. The demo officer can't be removed from the app yet, so a production deployment should start without it. If you add it later, change its password by running `create-staff` again with the username `demo-officer`.

## Data

- [ ] Create one officer account per participating APMC with `admin.sh create-staff`.
- [ ] Import each APMC's **official** licence register with `admin.sh import-traders`. Use only the APMC's own records.
- [ ] Check that `./cloudshell/admin.sh daily` imports prices for your crops.
- [ ] Review `bhavsetu/src/bhavsetu/data/charge_rules.json` with the APMC: which deductions are allowed, and at what rates.

## Operations

- [ ] Add a custom domain if you want one: put CloudFront or a Route 53 alias in front of the Express load balancer.
- [ ] Set CloudWatch alarms on the service's 5xx count and on RDS CPU and storage.
- [ ] Decide how long to keep evidence, and add an S3 lifecycle rule if needed.
- [ ] Optional: turn on AI slip reading with `./cloudshell/deploy.sh --ai-key`.

## People

- [ ] Train APMC staff on the complaint queue, and agree how quickly a complaint gets a first response.
- [ ] Explain to farmers that checks are leads for the APMC, and that the complaint pack is what they show the office.
