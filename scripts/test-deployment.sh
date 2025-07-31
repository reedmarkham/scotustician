#!/bin/bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Testing Scotustician Deployment${NC}"
echo "========================================="

# Set region from environment or default
REGION="${AWS_REGION:-us-east-1}"
echo -e "Region: ${YELLOW}$REGION${NC}"

# Function to check if a stack exists
check_stack() {
    local stack_name=$1
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --region "$REGION" &>/dev/null
}

# Function to get stack output
get_stack_output() {
    local stack_name=$1
    local output_key=$2
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --query "Stacks[0].Outputs[?OutputKey=='$output_key'].OutputValue" \
        --output text \
        --region "$REGION" 2>/dev/null || echo "None"
}

# Check if stacks exist
echo -e "\n${YELLOW}Checking CloudFormation stacks...${NC}"
for stack in ScotusticianSharedStack ScotusticianIngestStack ScotusticianTransformersStack; do
    if check_stack "$stack"; then
        echo -e "[OK] $stack: ${GREEN}EXISTS${NC}"
    else
        echo -e "[ERROR] $stack: ${RED}NOT FOUND${NC}"
    fi
done

# Get cluster information
echo -e "\n${YELLOW}Retrieving cluster information...${NC}"
CLUSTER=$(get_stack_output ScotusticianSharedStack ClusterName)
if [[ "$CLUSTER" != "None" ]]; then
    echo -e "[OK] Cluster: ${GREEN}$CLUSTER${NC}"
    
    # Check cluster status
    CLUSTER_INFO=$(aws ecs describe-clusters \
        --clusters "$CLUSTER" \
        --region "$REGION" \
        --query 'clusters[0].[status,runningTasksCount,pendingTasksCount]' \
        --output text 2>/dev/null || echo "None None None")
    
    IFS=$'\t' read -r STATUS RUNNING PENDING <<< "$CLUSTER_INFO"
    echo "   Status: $STATUS"
    echo "   Running tasks: $RUNNING"
    echo "   Pending tasks: $PENDING"
else
    echo -e "[ERROR] ${RED}Cluster not found${NC}"
fi

# Check VPC and networking
echo -e "\n${YELLOW}Checking VPC and networking...${NC}"
PUBLIC_SUBNET=$(get_stack_output ScotusticianSharedStack PublicSubnetId1)
PRIVATE_SUBNET=$(get_stack_output ScotusticianSharedStack PrivateSubnetId1)

if [[ "$PUBLIC_SUBNET" != "None" ]]; then
    echo -e "[OK] Public Subnet: ${GREEN}$PUBLIC_SUBNET${NC}"
fi
if [[ "$PRIVATE_SUBNET" != "None" ]]; then
    echo -e "[OK] Private Subnet: ${GREEN}$PRIVATE_SUBNET${NC}"
    
    # Check VPC endpoints
    VPC_ID=$(aws ec2 describe-subnets \
        --subnet-ids "$PRIVATE_SUBNET" \
        --region "$REGION" \
        --query "Subnets[0].VpcId" \
        --output text 2>/dev/null || echo "None")
    
    if [[ "$VPC_ID" != "None" ]]; then
        echo -e "\n   VPC Endpoints in $VPC_ID:"
        aws ec2 describe-vpc-endpoints \
            --filters "Name=vpc-id,Values=$VPC_ID" \
            --region "$REGION" \
            --query 'VpcEndpoints[*].[ServiceName,State]' \
            --output text | while IFS=$'\t' read -r service state; do
            echo "   - ${service##*.}: $state"
        done
    fi
fi

# Check task definitions
echo -e "\n${YELLOW}Checking task definitions...${NC}"
INGEST_TASK=$(get_stack_output ScotusticianIngestStack IngestTaskDefinitionArn)
TRANSFORM_TASK=$(get_stack_output ScotusticianTransformersStack TransformersCpuTaskDefinitionArn)

if [[ "$INGEST_TASK" != "None" ]]; then
    echo -e "[OK] Ingest Task: ${GREEN}Found${NC}"
    echo "   ARN: $INGEST_TASK"
fi
if [[ "$TRANSFORM_TASK" != "None" ]]; then
    echo -e "[OK] Transform Task: ${GREEN}Found${NC}"
    echo "   ARN: $TRANSFORM_TASK"
fi

# Check S3 bucket
echo -e "\n${YELLOW}Checking S3 bucket...${NC}"
if aws s3 ls s3://scotustician &>/dev/null; then
    echo -e "[OK] S3 Bucket: ${GREEN}Accessible${NC}"
    
    # Count objects
    INGEST_COUNT=$(aws s3 ls s3://scotustician/raw/oa/ --recursive | wc -l)
    LOG_COUNT=$(aws s3 ls s3://scotustician/logs/ --recursive | wc -l)
    echo "   Ingested files: $INGEST_COUNT"
    echo "   Log files: $LOG_COUNT"
else
    echo -e "[ERROR] S3 Bucket: ${RED}Not accessible${NC}"
fi

# Check PostgreSQL secret
echo -e "\n${YELLOW}Checking database configuration...${NC}"
SECRET_NAME="scotustician-db-credentials"
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" &>/dev/null; then
    echo -e "[OK] Database Secret: ${GREEN}Found${NC}"
    
    # Get PostgreSQL host from context or environment
    POSTGRES_HOST=$(aws cloudformation describe-stacks \
        --stack-name ScotusticianTransformersStack \
        --region "$REGION" \
        --query 'Stacks[0].Parameters[?ParameterKey==`postgresHost`].ParameterValue' \
        --output text 2>/dev/null || echo "None")
    
    if [[ "$POSTGRES_HOST" != "None" ]]; then
        echo "   Host: $POSTGRES_HOST"
    fi
else
    echo -e "[WARNING] Database Secret: ${YELLOW}Not found${NC} (might be in different region)"
fi

# Test dry run of ingest task
if [[ "$CLUSTER" != "None" && "$INGEST_TASK" != "None" && "$PUBLIC_SUBNET" != "None" ]]; then
    echo -e "\n${YELLOW}Running test ingest task (DRY_RUN mode)...${NC}"
    
    # Get default security group
    VPC_ID=$(aws ec2 describe-subnets \
        --subnet-ids "$PUBLIC_SUBNET" \
        --region "$REGION" \
        --query "Subnets[0].VpcId" \
        --output text)
    
    SG_ID=$(aws ec2 describe-security-groups \
        --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
        --region "$REGION" \
        --query "SecurityGroups[0].GroupId" \
        --output text)
    
    if [[ -n "$SG_ID" && "$SG_ID" != "None" ]]; then
        TASK_ARN=$(aws ecs run-task \
            --cluster "$CLUSTER" \
            --task-definition "$INGEST_TASK" \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[$PUBLIC_SUBNET],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
            --overrides '{
                "containerOverrides": [{
                    "name": "IngestContainer",
                    "environment": [
                        {"name": "DRY_RUN", "value": "true"},
                        {"name": "START_TERM", "value": "2024"},
                        {"name": "END_TERM", "value": "2025"}
                    ]
                }]
            }' \
            --region "$REGION" \
            --query 'tasks[0].taskArn' \
            --output text 2>/dev/null)
        
        if [[ -n "$TASK_ARN" && "$TASK_ARN" != "None" ]]; then
            echo -e "[OK] Test task launched: ${GREEN}$TASK_ARN${NC}"
            echo "   Waiting for task to complete..."
            
            # Wait for task to stop
            aws ecs wait tasks-stopped \
                --cluster "$CLUSTER" \
                --tasks "$TASK_ARN" \
                --region "$REGION" 2>/dev/null || true
            
            # Get task status
            TASK_STATUS=$(aws ecs describe-tasks \
                --cluster "$CLUSTER" \
                --tasks "$TASK_ARN" \
                --region "$REGION" \
                --query 'tasks[0].[lastStatus,stoppedReason]' \
                --output text 2>/dev/null || echo "Unknown Unknown")
            
            IFS=$'\t' read -r STATUS REASON <<< "$TASK_STATUS"
            echo "   Final status: $STATUS"
            [[ -n "$REASON" && "$REASON" != "None" ]] && echo "   Stop reason: $REASON"
            
            # Check logs
            echo -e "\n   ${YELLOW}Recent logs:${NC}"
            aws logs tail /ecs/ingest --since 5m --region "$REGION" 2>/dev/null | tail -10 || echo "   No recent logs found"
        else
            echo -e "[ERROR] ${RED}Failed to launch test task${NC}"
        fi
    fi
fi

# Summary
echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Deployment Test Summary${NC}"
echo -e "${GREEN}=========================================${NC}"

# Create summary
ISSUES=0
[[ "$CLUSTER" == "None" ]] && ((ISSUES++)) && echo -e "[ERROR] ${RED}ECS Cluster not found${NC}"
[[ "$INGEST_TASK" == "None" ]] && ((ISSUES++)) && echo -e "[ERROR] ${RED}Ingest task definition not found${NC}"
[[ "$TRANSFORM_TASK" == "None" ]] && ((ISSUES++)) && echo -e "[ERROR] ${RED}Transform task definition not found${NC}"

if [[ $ISSUES -eq 0 ]]; then
    echo -e "[OK] ${GREEN}All core components are deployed and accessible${NC}"
else
    echo -e "[WARNING] ${YELLOW}Found $ISSUES issue(s) that need attention${NC}"
fi

echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Review the AWS_RESOURCE_GUIDE.md for detailed instructions"
echo "2. Run './scripts/ingest-data.sh' to start data ingestion"
echo "3. Run './scripts/transform-data.sh' to generate embeddings"
echo "4. Monitor progress in CloudWatch Logs"