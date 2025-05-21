# 🏛️ scotustician

**scotustician** is a data ingestion pipeline and embedding generation service for Supreme Court of the United States (SCOTUS) oral argument (OA) transcripts, deployed on AWS using Docker, CDK, and GitHub Actions.

This project supports downstream search, clustering, and visualization tasks by processing SCOTUS OA transcripts into structured embeddings using Hugging Face transformer models.

The [Hugging Face model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) used produces 384-dimension embeddings and performs well for clustering and semantic search but future work can experiment with different models.

---

## Folder Structure

This project is divided into the following components:

```
scotustician/
├── ingest/            # Task to ingest raw data from Oyez.org API
├── transformers/      # Task for generating and storing text embeddings
├── infra/             # AWS CDK code defining ECS services, clusters, and infrastructure
└── .github/workflows/ # CI/CD pipelines for automatic deployment via GitHub Actions
```

---

## Design

**Infrastructure:**
- AWS CDK (TypeScript) to provision clusters, networking, and ECS tasks below using Docker images
- ECS Fargate task for `ingest` (parallelized ingestion of JSON data from Oyez.org API to S3 using Python)
- ECS EC2 task w/ GPU for `transformers`
- GitHub Actions CI/CD

**Data Flow:**
1. `ingest` collects and loads SCOTUS metadata and case text from Oyez.org API to S3.
2. Processed text from `ingest` on S3 is read by `transformers`, which uses [Hugging Face models](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) to generate embeddings.
3. Embeddings are stored in an [OpenSearch vector database](https://www.github.com/reedmarkham/scotustician-db), which was deployed separately.

---

## Prerequisites

The ARN, access key, and secret key ID for a previously-created (i.e. via console or other stack) AWS IAM user, with a minimal policy like:
```
{
	"Version": "2012-10-17",
	"Statement": [
		{
			"Sid": "CloudFormationAccess",
			"Effect": "Allow",
			"Action": [
				"cloudformation:DescribeStacks",
				"cloudformation:CreateChangeSet",
				"cloudformation:ExecuteChangeSet",
				"cloudformation:DescribeChangeSet",
				"cloudformation:GetTemplateSummary",
				"cloudformation:DescribeStackEvents",
				"cloudformation:DeleteStack",
				"cloudformation:UpdateStack"
			],
			"Resource": "*"
		},
		{
			"Sid": "CDKBootstrapAssets",
			"Effect": "Allow",
			"Action": [
				"s3:PutObject",
				"s3:GetObject",
				"s3:ListBucket"
			],
			"Resource": [
				"arn:aws:s3:::cdk-sctstcn-assets-<ACCOUNT_ID>-<REGION>",
				"arn:aws:s3:::cdk-sctstcn-assets-<ACCOUNT_ID>-<REGION>/*"
			]
		},
		{
			"Sid": "PassExecutionRole",
			"Effect": "Allow",
			"Action": [
				"iam:PassRole",
				"sts:AssumeRole"
			],
			"Resource": "arn:aws:iam::<ACCOUNT_ID>:role/cdk-sctstcn-cfn-exec-role-*"
		},
		{
			"Sid": "ECSAndEC2Management",
			"Effect": "Allow",
			"Action": [
				"ecs:*",
				"ec2:Describe*",
				"ec2:CreateTags",
				"ec2:RunInstances",
				"ec2:CreateSecurityGroup",
				"ec2:DeleteSecurityGroup",
				"ec2:AuthorizeSecurityGroupIngress",
				"ec2:AuthorizeSecurityGroupEgress"
			],
			"Resource": "*"
		},
		{
			"Sid": "ECRAccess",
			"Effect": "Allow",
			"Action": [
				"ecr:GetAuthorizationToken",
				"ecr:BatchCheckLayerAvailability",
				"ecr:GetDownloadUrlForLayer",
				"ecr:BatchGetImage",
				"ecr:DescribeRepositories"
			],
			"Resource": "*"
		},
		{
			"Sid": "LogGroupManagement",
			"Effect": "Allow",
			"Action": [
				"logs:CreateLogGroup",
				"logs:PutRetentionPolicy",
				"logs:DescribeLogGroups",
				"logs:CreateLogStream",
				"logs:PutLogEvents"
			],
			"Resource": "*"
		},
		{
			"Sid": "SSMParameterAccess",
			"Effect": "Allow",
			"Action": [
				"ssm:GetParameter",
				"ssm:GetParameters",
				"ssm:PutParameter",
				"ssm:DescribeParameters"
			],
			"Resource": "*"
		},
		{
			"Sid": "SecretsManagerAccess",
			"Effect": "Allow",
			"Action": [
				"secretsmanager:GetSecretValue",
				"secretsmanager:DescribeSecret"
			],
			"Resource": "*"
		},
		{
			"Sid": "ELBAccessForFargate",
			"Effect": "Allow",
			"Action": [
				"elasticloadbalancing:*"
			],
			"Resource": "*"
		},
		{
			"Sid": "CloudMapAccess",
			"Effect": "Allow",
			"Action": [
				"servicediscovery:*"
			],
			"Resource": "*"
		}
	]
}
```

Ensure the following secrets are configured in your GitHub repo at **Settings > Secrets and variables > Actions > repository secrets**:
| Secret Name         | Description                       | Example Value         |
|---------------------|-----------------------------------|----------------------|
| `AWS_ACCOUNT_ID`    | AWS account ID                    | `123456789012`       |
| `AWS_REGION`        | AWS region | `us-east-1`          |
| `AWS_IAM_ARN`        | AWS IAM user's ARN | `arn:aws:iam%`          |
| `AWS_ACCESS_KEY`        | AWS IAM user's access key | `%`          |
| `AWS_SECRET_KEY_ID`        | AWS IAM user's secret key| `%`          |

**Bootstrap the environment outside of CI/CD**

Make sure to use a <=10 chracter `--qualifier`:
```
npx cdk bootstrap \
  --toolkit-stack-name CDKToolkit-scotustician \
  --qualifier sctstcn \
  aws://<AWS_ACCOUNT_ID>/<AWS_REGION>
```
Then update the `infra/cdk.json` accordingly:

```
{
  "app": "npx ts-node --prefer-ts-exts bin/scotustician.ts",
  "context": {
    "aws:cdk:bootstrap-qualifier": "sctstcn"
  }
}
```

**Request vCPU quota increase for your AWS account**

AWS requires explicit quota requests especially for things like GPU or large EC2 instances:
```
Go to the EC2 vCPU Limits page:
* https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas

Look for the quota named:
* Running On-Demand G and VT instances
* OR Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances if you’re using a different instance type

Click on the relevant quota
* Request quota increase

Submit
* AWS typically approves within a few hours to a day, especially for small (1 instance) increases.
```

**Run the tasks in an ad-hoc script**

Review the stack output for subnet and cluster names, and then:
```
#!/bin/bash

# === Fargate Ingest Task ===
CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianIngestStack-IngestTaskDefXXXXXXXX"  # Replace with actual ARN or family name
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                      # Private subnet with NAT access
SG_ID="sg-xxxxxxxxxxxxxxxxx"                              # SG allowing outbound HTTPS
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```

```
#!/bin/bash

# === EC2 Transformers Task (GPU) ===
CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianTransformersStack-TransformersTaskDefXXXXXXXX"  # Replace with actual ARN or family
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                                  # Private subnet for EC2 instance
SG_ID="sg-xxxxxxxxxxxxxxxxx"                                          # SG allowing outbound traffic
REGION="us-east-1"
CAPACITY_PROVIDER="GpuCapacityProvider"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type EC2 \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --capacity-provider-strategy "capacityProvider=$CAPACITY_PROVIDER,weight=1" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```

## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects changes in `ingest/` or `transformers/`, builds respective Docker images, and deploys via `cdk deploy`.

---

## Appendix

This project owes inspiration and many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.