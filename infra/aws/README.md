# Finora AWS stack

Deploy `finora.yaml` in `us-east-1` with CloudFormation. It creates only the
networking required for one public EC2 host, an Elastic IP, SSM access, an OIDC
role for this repository, and monthly budget notifications. It intentionally
does not create SSH access, RDS, ElastiCache, a NAT gateway, a load balancer,
or a domain.

Use the deployment guide at `docs/deployment/aws-portfolio.md` for the required
Parameter Store values, GitHub variables, Vercel settings, and the one-time
IP-certificate setup.
