# Finora Portfolio AWS Deployment Design

## Goal

Publish Finora as a public portfolio project without committing secrets or
requiring always-on AWS compute. The Next.js application is hosted on Vercel;
the Django, Celery, Redis, and PostgreSQL stack runs together on one manually
startable EC2 instance until the account's AWS Free Plan ends on 2027-01-21.

## Constraints

- Keep the locked application architecture: Django/DRF, PostgreSQL, Redis,
  Celery, Gemini, Next.js, React Query, and Zustand.
- Use one `t3.micro` EC2 instance with a 30 GB gp3 EBS volume. Disable T3
  Unlimited and do not create RDS, ElastiCache, NAT Gateway, an ALB, Route 53,
  or a paid domain.
- Use Vercel's free `*.vercel.app` URL as the public browser origin. Vercel
  proxies `/api/*` to the EC2 API so the browser uses same-origin requests.
- The backend must be HTTPS even without a domain. Certbot obtains and renews
  short-lived Let's Encrypt IP-address certificates for the stable Elastic IP.
- The repository is public. `GEMINI_API_KEY`, Django's secret key, database
  credentials, and deployment credentials never enter Git, a container image,
  or a browser bundle.
- A stopped backend is expected. The frontend reports that state clearly;
  scheduled work resumes through a recovery command when the instance starts.

## Runtime

An Elastic IP is associated with the EC2 instance so Vercel's backend origin
does not change after stop/start. The host runs Nginx and Certbot. Docker
Compose runs Django/Gunicorn, one Celery worker, Celery Beat, PostgreSQL, and
Redis. Persistent bind mounts under `/srv/finora/data` hold database, Redis,
media, and deployment state. A 2 GB swap file and conservative process limits
make the single-GB instance usable.

Nginx accepts only HTTP for the ACME challenge and HTTPS for `/api/`; it does
not expose Django admin or raw receipt media. Django receives the proxy scheme
through `SECURE_PROXY_SSL_HEADER`, runs with `DEBUG=False`, and has explicit
host, CORS, CSRF, upload-size, and API-throttle settings.

## Public demo

The login UI presents a shared demo account, demo-data reset notice, and a
warning not to upload sensitive financial documents. A `DemoDataService`
creates only the dedicated demo tenant, user, membership, invoices, expenses,
and reviewable workflows. Its reset command runs on EC2 start and every day
while the instance remains up. Resetting never touches another tenant.

Receipt uploads are limited to image types and a small configured maximum.
Gemini-triggering endpoints have conservative throttles. Email reminder sends
remain simulated as required by the existing Invoice Chaser design.

## Authentication

The frontend persists the access and refresh tokens independently. The API
client refreshes one time after an unauthorized response and retries that
request; a failed refresh clears both values. The browser-facing production API
base is `/api`, while local development retains the existing explicit API URL.

## Delivery

GitHub Actions run backend tests, Django checks, the frontend lint/build,
production Compose validation, and a tracked-file secret check. A successful
push to `main` builds a Linux/amd64 backend image and publishes it to GHCR.
AWS OIDC gives the workflow a narrowly scoped role that invokes SSM commands;
it has no stored AWS access key and no inbound SSH is opened.

The instance role reads only `/finora/production/*` SecureString parameters
from Parameter Store and is managed with SSM. Deploy commands pull the image,
take a local database dump, migrate, restart services, run demo recovery, and
check `/api/health/`. Manual GitHub workflows start, stop, restart, and report
the demo instance. Vercel's Git integration deploys `frontend/` from `main`.

## Cost and lifecycle

AWS budget alerts are configured at $25, $50, and $80. Instance compute stops
when EC2 is stopped; EBS and Elastic IP remain allocated. The deployment
documentation includes a cleanup checklist for 2027-01-15, ahead of the AWS
Free Plan end date. This is a portfolio demo, not a durable production service:
there are no managed backups, HA, or always-on availability guarantees.

## Verification

Before launch, run the complete backend suite, frontend lint/build, Django
production deployment checks, Compose configuration validation, a local
container smoke test, and a tracked/history secret scan. After provisioning,
exercise login, receipt extraction, invoice reminder drafting, approve/reject
audit logs, Vercel API proxying, EC2 stop/start recovery, and the frontend's
offline message.
