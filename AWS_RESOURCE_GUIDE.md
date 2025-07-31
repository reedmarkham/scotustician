# AWS Resource Management Guide for Scotustician

## Overview
This guide provides comprehensive documentation for managing and testing the Scotustician infrastructure deployed via AWS CDK and GitHub Actions.

## CDK Stack Outputs

### ScotusticianSharedStack Outputs
- **ClusterName**: ECS cluster name for running tasks
- **PublicSubnetId1**: First public subnet ID
- **PublicSubnetId2**: Second public subnet ID  
- **PrivateSubnetId1**: First private subnet ID (for RDS access)
- **PrivateSubnetId2**: Second private subnet ID (for RDS access)
- **GpuInstanceId**: EC2 GPU instance ID (if GPU enabled)
- **SecurityGroupId**: Security group ID for GPU instance (if GPU enabled)

### ScotusticianIngestStack Outputs
- **IngestTaskDefinitionArn**: ARN of the ingest task definition
- **IngestContainerName**: Name of the ingest container

### ScotusticianTransformersStack Outputs
- **TransformersCpuTaskDefinitionArn**: ARN of CPU transformer task definition (or TransformersGpuTaskDefinitionArn if GPU)
- **TransformersCpuContainerName**: Name of CPU transformer container (or TransformersGpuContainerName if GPU)
- **FargateSecurityGroupId**: Security group ID for Fargate tasks accessing RDS

## Retrieving Stack Outputs

After deployment, retrieve the actual values using AWS CLI:

```bash
# Get all outputs from a specific stack
aws cloudformation describe-stacks \
  --stack-name ScotusticianSharedStack \
  --query 'Stacks[0].Outputs' \
  --output table

aws cloudformation describe-stacks \
  --stack-name ScotusticianIngestStack \
  --query 'Stacks[0].Outputs' \
  --output table

aws cloudformation describe-stacks \
  --stack-name ScotusticianTransformersStack \
  --query 'Stacks[0].Outputs' \
  --output table

# Get specific output values
CLUSTER_NAME=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianSharedStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ClusterName`].OutputValue' \
  --output text)

INGEST_TASK_ARN=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianIngestStack \
  --query 'Stacks[0].Outputs[?OutputKey==`IngestTaskDefinitionArn`].OutputValue' \
  --output text)

TRANSFORM_TASK_ARN=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianTransformersStack \
  --query 'Stacks[0].Outputs[?OutputKey==`TransformersCpuTaskDefinitionArn`].OutputValue' \
  --output text)
```

## Running ECS Tasks Ad-Hoc

### Prerequisites
Ensure you have the following information:
- ECS Cluster name from CloudFormation outputs
- Task definition ARN from CloudFormation outputs
- Subnet IDs (use private subnets for RDS access)
- Security group IDs

### Running the Ingest Task

```bash
# Set variables from CloudFormation outputs
CLUSTER_NAME="<from-cloudformation-outputs>"
TASK_DEFINITION_ARN="<from-cloudformation-outputs>"
SUBNET_ID="<private-subnet-id-from-outputs>"
SECURITY_GROUP_ID="<default-or-fargate-security-group>"

# Run the ingest task
aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --task-definition "$TASK_DEFINITION_ARN" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SECURITY_GROUP_ID],assignPublicIp=DISABLED}" \
  --overrides '{
    "containerOverrides": [
      {
        "name": "IngestContainer",
        "environment": [
          {"name": "START_TERM", "value": "2024"},
          {"name": "END_TERM", "value": "2025"},
          {"name": "MAX_WORKERS", "value": "8"},
          {"name": "DRY_RUN", "value": "false"}
        ]
      }
    ]
  }'

# Check task status
aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks <task-id-from-run-task-output>
```

### Running the Transformers Task

```bash
# Set variables
CLUSTER_NAME="<from-cloudformation-outputs>"
TASK_DEFINITION_ARN="<transformers-task-arn>"
PRIVATE_SUBNET_ID="<private-subnet-id>"
FARGATE_SECURITY_GROUP="<fargate-security-group-id>"

# Run the transformers task
aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --task-definition "$TASK_DEFINITION_ARN" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_ID],securityGroups=[$FARGATE_SECURITY_GROUP],assignPublicIp=DISABLED}" \
  --overrides '{
    "containerOverrides": [
      {
        "name": "TransformersCpuContainer",
        "environment": [
          {"name": "BATCH_SIZE", "value": "16"},
          {"name": "MAX_WORKERS", "value": "2"},
          {"name": "RAW_PREFIX", "value": "raw/oa"}
        ]
      }
    ]
  }'
```

## Monitoring and Logs

### View CloudWatch Logs

```bash
# List log streams for ingest tasks
aws logs describe-log-streams \
  --log-group-name /ecs/ingest \
  --order-by LastEventTime \
  --descending

# View logs from a specific stream
aws logs get-log-events \
  --log-group-name /ecs/ingest \
  --log-stream-name <stream-name> \
  --start-from-head

# Tail logs in real-time
aws logs tail /ecs/ingest --follow

# Search for errors
aws logs filter-log-events \
  --log-group-name /ecs/transformers \
  --filter-pattern "ERROR"
```

### Check Task Status

```bash
# List recent tasks
aws ecs list-tasks \
  --cluster "$CLUSTER_NAME" \
  --desired-status STOPPED \
  --max-results 10

# Get detailed task information
aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks <task-arn> \
  --include TAGS
```

## Database Validation

### Connect to RDS PostgreSQL

```bash
# Get the RDS endpoint from your infrastructure
POSTGRES_HOST="<your-rds-endpoint>"
POSTGRES_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id scotustician-db-credentials \
  --query SecretString \
  --output text | jq -r .password)

# Connect using psql
PGPASSWORD=$POSTGRES_PASSWORD psql \
  -h $POSTGRES_HOST \
  -U dbuser \
  -d scotustician
```

### Validate Data in PostgreSQL

```sql
-- Check if tables exist
\dt scotustician.*;

-- Count records in each table
SELECT COUNT(*) FROM scotustician.transcript_embeddings;
SELECT COUNT(*) FROM scotustician.raw_transcripts;
SELECT COUNT(*) FROM scotustician.case_decisions;
SELECT COUNT(*) FROM scotustician.justice_votes;

-- View sample embedding data
SELECT 
  case_id,
  docket_number,
  term,
  speaker_list,
  created_at
FROM scotustician.transcript_embeddings
ORDER BY created_at DESC
LIMIT 5;

-- Check embedding dimensions
SELECT 
  case_id,
  array_length(embedding, 1) as embedding_dimension
FROM scotustician.transcript_embeddings
LIMIT 1;

-- Search for specific cases
SELECT * FROM scotustician.transcript_embeddings
WHERE docket_number LIKE '%21-869%';
```

## S3 Data Validation

### Check Ingested Data

```bash
# List recent ingestions
aws s3 ls s3://scotustician/raw/oa/ --recursive | tail -20

# Count total files
aws s3 ls s3://scotustician/raw/oa/ --recursive | wc -l

# Check file sizes
aws s3 ls s3://scotustician/raw/oa/ --recursive --human-readable --summarize

# Download and inspect a sample file
aws s3 cp s3://scotustician/raw/oa/<sample-file>.json - | jq '.'

# Check ingestion logs
aws s3 ls s3://scotustician/logs/daily/ --recursive
```

## Troubleshooting Commands

### ECS Task Failures

```bash
# Get task failure reason
aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks <failed-task-arn> \
  --query 'tasks[0].stoppedReason'

# Check container exit code
aws ecs describe-tasks \
  --cluster "$CLUSTER_NAME" \
  --tasks <failed-task-arn> \
  --query 'tasks[0].containers[0].exitCode'
```

### Network Connectivity

```bash
# Test VPC endpoints
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=<vpc-id>" \
  --query 'VpcEndpoints[*].[ServiceName,State]' \
  --output table

# Check security group rules
aws ec2 describe-security-groups \
  --group-ids <security-group-id> \
  --query 'SecurityGroups[0].IpPermissions'
```

### Resource Limits

```bash
# Check ECS service quotas
aws service-quotas list-service-quotas \
  --service-code ecs \
  --query 'Quotas[?contains(QuotaName, `Fargate`)]'

# Check current usage
aws ecs describe-clusters \
  --clusters "$CLUSTER_NAME" \
  --query 'clusters[0].[runningTasksCount,pendingTasksCount]'
```

## Automated Testing Script

Create a test script `test-deployment.sh`:

```bash
#!/bin/bash
set -euo pipefail

echo "🔍 Testing Scotustician Deployment"

# Get stack outputs
CLUSTER=$(aws cloudformation describe-stacks \
  --stack-name ScotusticianSharedStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ClusterName`].OutputValue' \
  --output text)

echo "✅ Found cluster: $CLUSTER"

# Test ingest task
echo "📥 Running test ingest task..."
TASK_ID=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "ScotusticianIngestStack-IngestTaskDef" \
  --launch-type FARGATE \
  --network-configuration "..." \
  --overrides '{"containerOverrides":[{"name":"IngestContainer","environment":[{"name":"DRY_RUN","value":"true"}]}]}' \
  --query 'tasks[0].taskArn' \
  --output text)

echo "⏳ Waiting for task completion..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ID"

# Check logs
echo "📋 Checking logs..."
aws logs tail /ecs/ingest --since 5m

echo "✅ Deployment test complete"
```

## Performance Metrics

### Monitor Task Performance

```bash
# Get task CPU and memory utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ClusterName,Value=$CLUSTER_NAME \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average

# Check for errors
aws cloudwatch get-metric-statistics \
  --namespace Scotustician \
  --metric-name IngestErrors \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

## Best Practices

1. **Always use private subnets** when tasks need to access RDS
2. **Monitor CloudWatch logs** for errors during task execution
3. **Use DRY_RUN mode** for testing new configurations
4. **Check task definitions** are using the latest revision
5. **Validate security groups** allow necessary traffic
6. **Set appropriate resource limits** based on workload
7. **Use environment variable overrides** for testing different configurations
8. **Monitor costs** through AWS Cost Explorer for Fargate and RDS usage