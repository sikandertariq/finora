# AWS + Vercel portfolio deployment

This is a deliberately small, disposable public demo. The browser UI is Vercel;
one stopped-when-idle EC2 instance runs Django, Celery, Postgres, Redis, Nginx,
and Certbot. There is no SSH, RDS, ElastiCache, NAT gateway, load balancer, paid
domain, or durable user-data promise.

## Before provisioning

1. Create a **public** GitHub repository and push this branch to `main`.
   The Vercel and GitHub workflows expect `main`. After the first deployment,
   make the `ghcr.io/<owner>/finora-backend` package public so EC2 can pull it
   without a registry credential.
2. In AWS CloudFormation (region `us-east-1`), create a stack from
   [`infra/aws/finora.yaml`](../../infra/aws/finora.yaml). Supply your GitHub
   owner, repository name, `main`, and a budget-alert email. Confirm the
   Budget email subscription when AWS sends it.
3. Record the stack outputs: `InstanceId`, `ElasticIp`, and
   `GitHubDeployRoleArn`. The Elastic IP is the permanent backend origin.

The stack creates an encrypted 30 GB gp3 root disk and one `t3.micro` with
standard, not unlimited, CPU credits. It also creates a VPC/subnet and internet
gateway only because the instance must be publicly reachable for the free
IP-address TLS certificate. It never opens port 22.

## Private SSM parameters

In Systems Manager Parameter Store, create these **SecureString** parameters in
the same region. Do not commit their values or put them in GitHub/Vercel.

| Name | Value guidance |
|---|---|
| `/finora/production/DJANGO_SECRET_KEY` | `openssl rand -hex 32` |
| `/finora/production/POSTGRES_PASSWORD` | `openssl rand -hex 24`; keep it letters/numbers so it is URL-safe |
| `/finora/production/GEMINI_API_KEY` | Your Gemini server key |
| `/finora/production/DEMO_USER_PASSWORD` | Public demo login password; `demo-password` is acceptable for this disposable demo |

The EC2 instance role can read only this prefix. The GitHub role cannot read
these values; it can only issue SSM commands to this one instance.

## GitHub configuration

In repository **Variables → Actions**, add:

| Variable | Value |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `AWS_DEPLOY_ROLE_ARN` | `GitHubDeployRoleArn` stack output |
| `AWS_INSTANCE_ID` | `InstanceId` stack output |
| `BACKEND_PUBLIC_IP` | `ElasticIp` stack output |

The deploy workflow builds a Linux/amd64 image, publishes it to GHCR, fetches
the public source onto EC2 over SSM, creates the private runtime environment
from Parameter Store, configures Nginx plus a six-day Let’s Encrypt IP
certificate, runs migrations/demo reset, and verifies HTTPS `/api/health/`.
No AWS access key is stored in GitHub.

Run **Deploy backend** once after the repository and package are public. A
fresh host needs several minutes for cloud-init/SSM registration. If you stop
the instance for more than a few days, run **Demo power control → start**, wait
for it to be running, then run **Deploy backend** again; this renews the short
IP certificate and resets the public data.

## Vercel configuration

Import the same GitHub repository into Vercel with **Root Directory** set to
`frontend`. Add these Production environment variables:

| Variable | Value |
|---|---|
| `BACKEND_ORIGIN` | `https://<ElasticIp>` |
| `NEXT_PUBLIC_DEMO_USERNAME` | `demo` |
| `NEXT_PUBLIC_DEMO_PASSWORD` | The public demo password |

Do **not** set `NEXT_PUBLIC_API_BASE_URL` in Vercel production. The frontend
uses `/api`, and the Vercel rewrite forwards it server-side to the HTTPS EC2
origin. This keeps the browser on the Vercel origin and avoids exposing server
credentials. Add `https://<your-project>.vercel.app` to Django CORS only if you
later intentionally make a browser-to-backend request; the standard proxy does
not need it.

## Smoke test and normal operation

1. Visit the Vercel URL and select **Try the demo**.
2. Confirm the sample invoices, expense, and reviewable invoice reminder load.
3. Upload only a harmless test receipt (JPEG, PNG, WEBP, or PDF, max 5 MB).
   Never put personal or real client financial data into this public demo.
4. Confirm/reject the workflow and verify the audit log behavior.
5. Run **Demo power control → stop** when you are done. The Vercel shell stays
   online and explains that the backend is intentionally offline.

The host’s `/srv/finora/data` directory holds Postgres, Redis AOF, media,
Celery Beat state, and pre-deploy SQL dumps. Demo resets remove only the
`finora-demo` tenant and its uploaded files. The reset happens every day while
the host runs and at each deployment.

## Cost guardrails and cleanup

AWS Budget alerts correspond to $25, $50, and $80 monthly spend. Stopping EC2
stops compute charges, but the 30 GB EBS volume and Elastic IP remain allocated.
Review Cost Explorer after the first deploy. On **2027-01-15**, before the
Free Plan expiry noted in the account, delete the CloudFormation stack, release
the Elastic IP, delete any retained EBS volume/snapshots and SSM parameters,
remove the Vercel project, and revoke the Gemini key if it is no longer used.
