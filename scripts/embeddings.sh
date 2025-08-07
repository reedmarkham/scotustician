#!/bin/bash
set -euo pipefail

# Redirect to new AWS Batch implementation
echo "NOTE: ECS-based embedding processing has been migrated to AWS Batch"
echo "Redirecting to batch-embeddings.sh for improved spot instance resilience"
echo "================================"

# Pass through environment variables
export AWS_REGION="${AWS_REGION:-us-east-1}"
export S3_BUCKET="${S3_BUCKET:-scotustician}"
export RAW_PREFIX="${RAW_PREFIX:-raw/oa}"
export MODEL_NAME="${MODEL_NAME:-Qwen/Qwen3-Embedding-0.6B}"
export MODEL_DIMENSION="${MODEL_DIMENSION:-1024}"
export BATCH_SIZE="${BATCH_SIZE:-4}"
export MAX_WORKERS="${MAX_WORKERS:-1}"
export INCREMENTAL="${INCREMENTAL:-true}"
export FILES_PER_JOB="${FILES_PER_JOB:-10}"

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Execute the new batch script
exec "$SCRIPT_DIR/batch-embeddings.sh"

# Dynamically retrieve values from CloudFormation
echo "Retrieving CloudFormation outputs..."

CLUSTER=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianSharedStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ClusterName`].OutputValue' \
  --output text \
  --region "$REGION")

if [[ -z "$CLUSTER" || "$CLUSTER" == "None" ]]; then
  echo "ERROR: Failed to retrieve cluster name from CloudFormation"
  exit 1
fi

# Get private subnet ID for RDS access
SUBNET_ID=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianSharedStack \
  --query 'Stacks[0].Outputs[?OutputKey==`PrivateSubnetId1`].OutputValue' \
  --output text \
  --region "$REGION")

if [[ -z "$SUBNET_ID" || "$SUBNET_ID" == "None" ]]; then
  echo "WARNING: No private subnet found, falling back to public subnet"
  SUBNET_ID=$(aws cloudformation describe-stacks \
    --stack-name ScotusticianSharedStack \
    --query 'Stacks[0].Outputs[?OutputKey==`PublicSubnetId1`].OutputValue' \
    --output text \
    --region "$REGION")
fi

if [[ -z "$SUBNET_ID" || "$SUBNET_ID" == "None" ]]; then
  echo "ERROR: Failed to retrieve subnet ID from CloudFormation"
  exit 1
fi

# PostgreSQL credentials are now handled via Secrets Manager in the ECS task definition

# Get task definition ARN (try GPU first, then CPU)
TASK_DEF_ARN=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianTransformersStack \
  --query 'Stacks[0].Outputs[?OutputKey==`TransformersGpuTaskDefinitionArn`].OutputValue' \
  --output text \
  --region "$REGION" 2>/dev/null || echo "None")

CONTAINER_NAME="TransformersGpuContainer"

if [[ -z "$TASK_DEF_ARN" || "$TASK_DEF_ARN" == "None" ]]; then
  echo "No GPU task found, using CPU task definition"
  TASK_DEF_ARN=$(aws cloudformation describe-stacks \
    --stack-name ScotusticianTransformersStack \
    --query 'Stacks[0].Outputs[?OutputKey==`TransformersCpuTaskDefinitionArn`].OutputValue' \
    --output text \
    --region "$REGION")
  CONTAINER_NAME="TransformersCpuContainer"
fi

if [[ -z "$TASK_DEF_ARN" || "$TASK_DEF_ARN" == "None" ]]; then
  echo "ERROR: Failed to retrieve task definition ARN from CloudFormation"
  exit 1
fi

# Get Fargate security group
FARGATE_SG=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianTransformersStack \
  --query 'Stacks[0].Outputs[?OutputKey==`FargateSecurityGroupId`].OutputValue' \
  --output text \
  --region "$REGION")

echo "Retrieved configuration:"
echo "   - Cluster: $CLUSTER"
echo "   - Subnet: $SUBNET_ID"
echo "   - Task Definition: $TASK_DEF_ARN"
echo "   - Container Name: $CONTAINER_NAME"
echo "   - Security Group: ${FARGATE_SG:-default}"

# Use the task definition ARN from CloudFormation
TASK_DEF="$TASK_DEF_ARN"

# Discover VPC and SG
VPC_ID=$(aws ec2 describe-subnets \
  --subnet-ids "$SUBNET_ID" \
  --region "$REGION" \
  --query "Subnets[0].VpcId" \
  --output text)

# Use Fargate security group if available, otherwise default
if [[ -n "$FARGATE_SG" && "$FARGATE_SG" != "None" ]]; then
  SG_ID="$FARGATE_SG"
else
  SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
    --region "$REGION" \
    --query "SecurityGroups[0].GroupId" \
    --output text)
fi

if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
  echo "ERROR: Failed to discover security group for VPC: $VPC_ID"
  exit 1
fi

echo "Launching text embeddings task: $TASK_DEF in cluster: $CLUSTER"
echo "Mode: $([ "$INCREMENTAL" == "true" ] && echo "INCREMENTAL" || echo "FULL REGENERATION")"

aws ecs run-task \
  --cluster "$CLUSTER" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --task-definition "$TASK_DEF" \
  --region "$REGION" \
  --overrides "{
    \"containerOverrides\": [
      {
        \"name\": \"${CONTAINER_NAME}\",
        \"environment\": [
          { \"name\": \"S3_BUCKET\", \"value\": \"$S3_BUCKET\" },
          { \"name\": \"RAW_PREFIX\", \"value\": \"$RAW_PREFIX\" },
          { \"name\": \"MODEL_NAME\", \"value\": \"$MODEL_NAME\" },
          { \"name\": \"MODEL_DIMENSION\", \"value\": \"$MODEL_DIMENSION\" },
          { \"name\": \"BATCH_SIZE\", \"value\": \"$BATCH_SIZE\" },
          { \"name\": \"MAX_WORKERS\", \"value\": \"$MAX_WORKERS\" },
          { \"name\": \"INCREMENTAL\", \"value\": \"$INCREMENTAL\" }
        ],
        \"command\": [\"python\", \"main.py\"]
      }
    ]
  }"