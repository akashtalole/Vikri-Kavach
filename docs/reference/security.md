# Security and privacy

## Accounts and sessions

- **Farmer login:**
    - The one-time code goes to the farmer's mobile number.
    - Codes are stored only as an HMAC hash.
    - Each code expires after 10 minutes and allows 5 attempts.
    - A number can request at most 5 codes an hour.
- **Staff login:** username and password. Passwords are hashed with scrypt and must be at least 10 characters. Passwords set from CloudShell are hashed there before they reach AWS.
- **Sessions:** a signed JWT in an HttpOnly, SameSite=Lax cookie. In production the cookie is also Secure and the signing key comes from Secrets Manager.
- **CSRF:** every write must carry a custom header, which a cross-site form cannot send.
- **Access:** farmers see only their own sales. Officers see only their own APMC. Responses use 404 rather than 403, so they don't reveal that a record exists.

## Data

- **Evidence files:**
    - Kept in a private S3 bucket with server-side encryption and versioning.
    - Served only through the API after an access check.
    - The upload type is checked by its content (magic bytes), not by the file name.
    - Each file's SHA-256 is recorded for the evidence pack.
- **Database:** RDS is encrypted, private (no public IP), and reachable only from inside the VPC, with 7-day backups and deletion protection.
- **Secrets:**
    - All secrets live in Secrets Manager.
    - The execution role can read only `vikrikavach/*` secrets.
    - The task role can reach only the evidence bucket and SNS SMS.
- **Audit:** every write action (logins, sales, payments, complaints, register changes, evidence-pack views) is recorded with the actor.
- **Logs:** phone numbers are masked in SMS logs, and the AI slip reader's errors are logged by type only.
- **Headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: same-origin` are set.

## Fairness

- A trader's status shown to farmers comes **only** from the APMC's official register, entered by APMC officers.
- Complaint counts and patterns appear only on the officer dashboard. They are labelled as leads to verify, not findings.
- Every check message explains its numbers, so the farmer, the trader and the officer can all reproduce it.
