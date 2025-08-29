
# scotustician-db

This directory contains the database layer for the [scotustician](https://www.github.com/reedmarkham/scotustician) project. It is referenced and deployed by the `scotustician-db-stack` in the `infrastructure/` directory of this repository, which manages the AWS CDK infrastructure for the database and related resources.

## What’s in this directory?

- **Database schema and migrations**: SQL and Lambda code for initializing and updating the PostgreSQL schema.
- **dbt models**: Transformation logic for analytics, organized in a medallion architecture.
- **CI/CD workflow**: GitHub Actions workflow for automated deployment.
- **Configuration**: All code and configuration for the database stack, including secrets and IAM policies.

## Repository Structure

```
database/
├── lambda/                  # Lambda for DB initialization and schema
│   ├── index.py
│   ├── schema.sql
│   └── requirements.txt
├── dbt/                     # dbt transformation models and config
│   ├── models/
│   ├── Dockerfile
│   └── dbt_project.yml
├── .github/
│   └── workflows/
│       └── deploy.yml
├── README.md                # This file
└── ...                      # Other supporting files
infrastructure/
└── lib/
  └── scotustician-db-stack.ts  # CDK stack referencing this directory
```

## How this directory is used

- The `scotustician-db-stack` in `infrastructure/` references files in `database/` to deploy and manage the RDS PostgreSQL instance, Lambda for schema management, and dbt resources.
- All schema, migration, and transformation logic should be placed here.
- Any changes to the database schema or dbt models will be picked up by the CDK stack and deployed via CI/CD.

## Stack summary

- **RDS PostgreSQL**: Managed by CDK, private VPC, pgvector enabled, secure by default.
- **Schema Management**: Automated via Lambda, schema and migration SQL in `lambda/`.
- **dbt on ECS Fargate**: Analytics and transformation jobs, models in `dbt/`.
- **Secrets**: Managed via AWS Secrets Manager, referenced by the stack.

## Pre-requisites

- AWS IAM user and credentials (see `infrastructure/` README for setup).
- PostgreSQL client (`psql`), `jq` for CLI access.
- Required secrets configured in GitHub repository settings.

## Deployment

All deployment is managed by the CDK app in `infrastructure/`. You do not need to deploy this directory directly; instead, run or update the CDK stack in `infrastructure/` to apply changes.

The database stack uses deterministic resource naming to ensure reliable deployments without requiring downstream stack deletions. Changes to database schema or dbt models trigger automatic redeployment via CI/CD.

## Database Access

- The RDS instance is private and only accessible from within the VPC.
- Credentials are managed in AWS Secrets Manager and referenced by the stack outputs.
- See the `infrastructure/` README for details on connecting to the database and managing secrets.

- **RDS PostgreSQL**
  - Version: PostgreSQL 16.4 with pgvector extension
  - `t3.micro` instance (cost-optimized)
  - Private VPC with isolated subnets (no public access)
  - Encrypted storage and automated backups
  - Supports up to 4096-dimensional embeddings with cosine similarity

- **Database Schema Management**
  - Automated schema creation via Lambda on stack deployment
  - Tables for transcripts, embeddings, case decisions, and processing metadata
  - Proper indexes for performance optimization
  - Schema isolated in `scotustician` namespace

- **dbt on ECS Fargate**
  - Weekly transformations (Sundays at 12 PM ET)
  - Bronze/Silver/Gold medallion architecture
  - Analytics models for oral arguments and speaker metrics
  - Manual triggers via Lambda function

## Pre-requisites

- The ARN, access key, and secret key ID for an AWS IAM user (i.e. `scotustician`), with a minimal policy like [`iam-policy.json`](iam-policy.json)
- PostgreSQL client (`psql`) for database connections
- `jq` for JSON parsing in CLI examples

Ensure the following secrets are configured in your GitHub repo at **Settings > Secrets and variables > Actions > repository secrets**:
| Secret Name         | Description             | Example Value                          |
|---------------------|-------------------------|----------------------------------------|
| `AWS_ACCOUNT_ID`    | AWS account ID          | `YOUR_ACCOUNT_ID`                      |
| `AWS_REGION`        | AWS region              | `us-east-1`                            |
| `AWS_IAM_ARN`       | IAM user ARN            | `arn:aws:iam::YOUR_ACCOUNT_ID:user/scotustician` |
| `AWS_ACCESS_KEY`    | IAM user's access key   | `AKIA...`                              |
| `AWS_SECRET_KEY_ID` | IAM user's secret key   | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKEY` |

**Bootstrap the environment outside of CI/CD**

Make sure to use a <=10 chracter `--qualifier`:
```
ID=<YOUR_IAM_USER_NAME>
AWS_REGION=<YOUR_REGION>
AWS_ACCOUNT_ID=<YOUR_ACCOUNT_ID>
AWS_IAM_ARN=arn:aws:iam::${AWS_ACCOUNT_ID}:user/${ID}

npx cdk bootstrap \
  --toolkit-stack-name CDKToolkit-${ID} \
  --qualifier sctstcn \
  aws://${AWS_ACCOUNT_ID}/${AWS_REGION}
```
Then, allow the roles created by CDK to trust the aforementioned IAM user:
```
# Define variables
ID=<YOUR_IAM_USER_NAME>
AWS_ACCOUNT_ID=<YOUR_ACCOUNT_ID>
AWS_REGION=<YOUR_REGION>
DEPLOY_USER_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:user/<ID>"

# Trust policy JSON (inline heredoc)
read -r -d '' TRUST_POLICY <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowScotusticianUserToAssumeRole",
      "Effect": "Allow",
      "Principal": {
        "AWS": "${DEPLOY_USER_ARN}"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Roles to update
ROLE_NAMES=(
  "cdk-sctstcn-deploy-role-${AWS_ACCOUNT_ID}-${AWS_REGION}"
  "cdk-sctstcn-file-publishing-role-${AWS_ACCOUNT_ID}-${AWS_REGION}"
  "cdk-sctstcn-image-publishing-role-${AWS_ACCOUNT_ID}-${AWS_REGION}"  # Only needed if using Docker assets
  "cdk-sctstcn-lookup-role-${AWS_ACCOUNT_ID}-${AWS_REGION}"           # Only needed if CDK uses lookups
)

# Apply the trust policy to each role
for ROLE in "${ROLE_NAMES[@]}"; do
  echo "🔧 Updating trust policy for role: $ROLE"
  aws iam update-assume-role-policy \
    --role-name "$ROLE" \
    --policy-document "$TRUST_POLICY"
done
```

## CI/CD

This app is deployed automatically using a GitHub Actions workflow triggered on push or pull request to `main`. The database stack deploys as part of the overall infrastructure orchestration with deterministic resource naming to ensure consistent deployments.

## Database Access

The RDS PostgreSQL instance is deployed with multiple layers of security to ensure only authorized access:

### Security Model
1. **Network Isolation**: Database is in a private VPC with no public internet access
2. **IAM-Based Access Control**: Only the specified IAM user can access database credentials
3. **Secrets Manager Resource Policy**: Database secret has a resource-based policy restricting access to the specific IAM user from repository secrets
4. **VPC Security Groups**: Network-level access restricted to VPC CIDR block only

### Access Requirements
1. **IAM User**: Must use the specific IAM user configured in repository secrets  
2. **VPC Connection**: Applications must be deployed within the same VPC or use VPC peering/transit gateway
3. **Database Credentials**: Retrieved from AWS Secrets Manager using the output `SecretArn` (access restricted by resource policy)
4. **Network Access**: Security group allows connections from within the VPC CIDR block only

### Connection Details (from CDK outputs):
- **Endpoint**: `DatabaseEndpoint` 
- **Port**: `DatabasePort` (default: 5432)
- **Database**: `scotustician`
- **Credentials**: Stored in AWS Secrets Manager at `SecretArn`

The database is automatically initialized with the required `scotustician` schema during CI/CD deployment.

### CLI Connection Example

To connect to the database using the AWS CLI while assuming the `scotustician` IAM user:

```bash
# Get database credentials from Secrets Manager
SECRET=$(aws secretsmanager get-secret-value \
  --secret-id <SecretArn> \
  --query SecretString --output text)

# Parse credentials
DB_HOST=$(echo $SECRET | jq -r '.host')
DB_PORT=$(echo $SECRET | jq -r '.port')
DB_NAME=$(echo $SECRET | jq -r '.dbname')
DB_USER=$(echo $SECRET | jq -r '.username')
DB_PASS=$(echo $SECRET | jq -r '.password')

# Connect using psql
PGPASSWORD=$DB_PASS psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME
```