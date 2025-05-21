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
- AWS CDK (TypeScript) provisions clusters, networking, and ECS tasks using Docker images.
- ECS Fargate task for `ingest` (parallelized ingestion of JSON data from Oyez.org API to S3 using Python).
- ECS EC2 task with GPU support for `transformers`—conditionally deployed if GPU resources are available in the AWS account.
- Shared infrastructure (e.g., EC2 instance, security groups) for GPU tasks is also conditionally deployed.
- GitHub Actions CI/CD.

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
		},
		{
			"Sid": "ServiceQuotasAccess",
			"Effect": "Allow",
			"Action": [
				"servicequotas:GetServiceQuota",
				"servicequotas:ListServiceQuotas",
				"servicequotas:ListRequestedServiceQuotaChangeHistoryByQuota",
				"servicequotas:RequestServiceQuotaIncrease"
			],
			"Resource": "*"
		},
			{
		"Sid": "AllowPassRoleForScotusticianTasks",
		"Effect": "Allow",
		"Action": "iam:PassRole",
		"Resource": [
			"arn:aws:iam::<ACCOUNT_ID>:role/ScotusticianIngestStack-IngestTaskDef*",
			"arn:aws:iam::<ACCOUNT_ID>:role/ScotusticianTransformersS-TransformersCpuTaskDef*"
		]
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

**Request vCPU quota increase for GPU-type instances on your AWS account**

When deploying via GitHub Actions, the presence of GPU compute capacity (e.g., vCPU quota for `p2`, `p3`, `p4`, or `g4dn` instance families) is checked. If no GPU capacity is available, the EC2 instance and GPU-based `transformers` task definition are **skipped**, and only CPU-based fallback infrastructure is provisioned.

To enable GPU support:
- Submit a vCPU quota increase request (see below).
- The CI/CD pipeline will include GPU resources only if quotas are available.

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

You can manually trigger ECS tasks using the AWS CLI.

First, **review the CDK stack outputs** for the following values:
- `ClusterName`
- `PublicSubnetId1` or `PrivateSubnetId`
- `SecurityGroupId`
- Task Definition ARNs for each service

---

### 🔹 1. Fargate Ingest Task (CPU)

```bash
#!/bin/bash

CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianIngestStack-IngestTaskDefXXXXXXXX"  # Replace with actual ARN
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                      # Public or NAT-enabled private subnet
SG_ID="sg-xxxxxxxxxxxxxxxxx"                              # Must allow HTTPS egress
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```

---

### 🔹 2. EC2 Transformers Task (GPU-accelerated)

```bash
#!/bin/bash

CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianTransformersStack-TransformersGpuTaskDefXXXXXXXX"  # Replace with actual ARN
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                                     # Private subnet for EC2
SG_ID="sg-xxxxxxxxxxxxxxxxx"
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type EC2 \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```

#### ⚠️ GPU Instance Note

The GPU instance used to run this task is provisioned as a **Spot EC2 instance** and is tagged with `AutoStop=true`.

- It will be **automatically stopped at 7 PM ET** each day by a scheduled Lambda rule.
- To run a GPU task after that time, **manually start the instance**:

```bash
aws ec2 start-instances --instance-ids i-xxxxxxxxxxxxxxxxx --region us-east-1
```

---

### 🔹 3. Fargate Transformers Task (CPU fallback)

Use this option if:
- The GPU instance is unavailable or stopped
- You want to run the model on CPU using 4 vCPU and 8 GB memory

```bash
#!/bin/bash

CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianTransformersStack-TransformersCpuTaskDefXXXXXXXX"  # Replace with actual ARN
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                                     # Public or private subnet with NAT
SG_ID="sg-xxxxxxxxxxxxxxxxx"
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```

## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects pertinent diffs, builds respective Docker images, and deploys via `cdk deploy`.

---

## Appendix

This project owes inspiration and many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.