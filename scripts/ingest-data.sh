#!/bin/bash
set -euo pipefail

# Set region from environment or default
REGION="${AWS_REGION:-us-east-1}"

# Set term range from environment or defaults
START_TERM="${START_TERM:-1980}"
END_TERM="${END_TERM:-2025}"

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

# Get subnet ID (prefer private subnet for better security)
SUBNET_ID=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianSharedStack \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicSubnetId1`].OutputValue' \
  --output text \
  --region "$REGION")

if [[ -z "$SUBNET_ID" || "$SUBNET_ID" == "None" ]]; then
  echo "ERROR: Failed to retrieve subnet ID from CloudFormation"
  exit 1
fi

# Get task definition ARN
TASK_DEF_ARN=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianIngestStack \
  --query 'Stacks[0].Outputs[?OutputKey==`IngestTaskDefinitionArn`].OutputValue' \
  --output text \
  --region "$REGION")

if [[ -z "$TASK_DEF_ARN" || "$TASK_DEF_ARN" == "None" ]]; then
  echo "ERROR: Failed to retrieve task definition ARN from CloudFormation"
  exit 1
fi

echo "Retrieved configuration:"
echo "   - Cluster: $CLUSTER"
echo "   - Subnet: $SUBNET_ID"
echo "   - Task Definition: $TASK_DEF_ARN"
echo "   - Start Term: $START_TERM"
echo "   - End Term: $END_TERM"

# Use the task definition ARN from CloudFormation
TASK_DEF="$TASK_DEF_ARN"

# Discover VPC and SG
VPC_ID=$(aws ec2 describe-subnets \
  --subnet-ids "$SUBNET_ID" \
  --region "$REGION" \
  --query "Subnets[0].VpcId" \
  --output text)

SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
  --region "$REGION" \
  --query "SecurityGroups[0].GroupId" \
  --output text)

if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
  echo "ERROR: Failed to discover default SG for VPC: $VPC_ID"
  exit 1
fi

echo "Launching INGEST task: $TASK_DEF in cluster: $CLUSTER"

aws ecs run-task \
  --cluster "$CLUSTER" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
  --task-definition "$TASK_DEF" \
  --region "$REGION" \
  --overrides '{
    "containerOverrides": [
      {
        "name": "IngestContainer",
        "environment": [
          { "name": "S3_BUCKET", "value": "scotustician" },
          { "name": "RAW_PREFIX", "value": "raw/" },
          { "name": "START_TERM", "value": "'"$START_TERM"'" },
          { "name": "END_TERM", "value": "'"$END_TERM"'" }
        ]
      }
    ]
  }'
