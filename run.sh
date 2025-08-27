#!/bin/bash

# Scotustician Step Functions Pipeline Runner
# Automated serverless execution - no laptop required

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
START_DATE=$(date +%Y-%m-%d)
AWS_REGION=${AWS_REGION:-us-east-1}
STACK_NAME=${STACK_NAME:-"ScotusticianOrchestrationStack"}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Scotustician Step Functions Pipeline${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Start Date: $START_DATE"
echo "AWS Region: $AWS_REGION"
echo ""

echo "Starting Step Functions orchestrated pipeline..."
echo ""

# Get Step Functions ARN
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
    --output text 2>/dev/null)

if [[ -z "$STATE_MACHINE_ARN" ]]; then
    echo -e "${RED}ERROR: Step Functions state machine not found${NC}"
    echo "Make sure the orchestration stack is deployed:"
    echo "  cd infrastructure && cdk deploy ScotusticianOrchestrationStack"
    exit 1
fi

echo "Found Step Functions state machine:"
echo "  ARN: $STATE_MACHINE_ARN"
echo ""

# Start execution
EXECUTION_NAME="scotustician-pipeline-$(date +%Y%m%d-%H%M%S)"

echo "Starting execution: $EXECUTION_NAME"
EXECUTION_ARN=$(aws stepfunctions start-execution \
    --state-machine-arn "$STATE_MACHINE_ARN" \
    --name "$EXECUTION_NAME" \
    --input '{}' \
    --region "$AWS_REGION" \
    --query "executionArn" \
    --output text)

if [[ -z "$EXECUTION_ARN" ]]; then
    echo -e "${RED}ERROR: Failed to start Step Functions execution${NC}"
    exit 1
fi

echo -e "${GREEN}Pipeline started successfully!${NC}"
echo ""

echo -e "${BLUE}Execution Details:${NC}"
echo "  Name: $EXECUTION_NAME"
echo "  ARN: $EXECUTION_ARN"
echo ""

echo -e "${BLUE}Monitor your pipeline:${NC}"
echo "  AWS Console: https://console.aws.amazon.com/states/home?region=$AWS_REGION#/executions/details/$EXECUTION_ARN"
echo "  Visual workflow: Shows real-time progress"
echo "  Cost notifications: Will be sent to SNS topic"
echo ""

echo -e "${BLUE}Command line monitoring:${NC}"
echo "  # Check execution status"
echo "  aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN --region $AWS_REGION"
echo ""
echo "  # Get execution history"
echo "  aws stepfunctions get-execution-history --execution-arn $EXECUTION_ARN --region $AWS_REGION"
echo ""
echo "  # View Step Functions logs"
echo "  aws logs tail /aws/stepfunctions/scotustician-pipeline --follow --region $AWS_REGION"
echo ""

# Optional: Wait and monitor
read -p "Monitor execution progress? (y/n): " monitor
if [[ $monitor == "y" || $monitor == "Y" ]]; then
    monitor_execution
else
    echo -e "${YELLOW}Pipeline is running in the background.${NC}"
    echo "You can close your laptop - the pipeline will continue running on AWS!"
fi

# Function to monitor Step Functions execution
monitor_execution() {
    echo ""
    echo -e "${YELLOW}Monitoring Step Functions execution...${NC}"
    echo "Press Ctrl+C to stop monitoring (pipeline will continue running)"
    echo ""
    
    local last_status=""
    local start_time=$(date +%s)
    
    while true; do
        local status=$(aws stepfunctions describe-execution \
            --execution-arn "$EXECUTION_ARN" \
            --region "$AWS_REGION" \
            --query "status" \
            --output text 2>/dev/null || echo "UNKNOWN")
        
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [[ "$status" != "$last_status" ]]; then
            case "$status" in
                "RUNNING")
                    echo "Pipeline is running... (${elapsed}s)"
                    ;;
                "SUCCEEDED")
                    echo -e "${GREEN}Pipeline completed successfully! (${elapsed}s)${NC}"
                    break
                    ;;
                "FAILED"|"TIMED_OUT"|"ABORTED")
                    echo -e "${RED}Pipeline failed with status: $status (${elapsed}s)${NC}"
                    
                    # Get failure details
                    local error=$(aws stepfunctions describe-execution \
                        --execution-arn "$EXECUTION_ARN" \
                        --region "$AWS_REGION" \
                        --query "cause" \
                        --output text 2>/dev/null)
                    
                    if [[ -n "$error" && "$error" != "None" ]]; then
                        echo "  Error: $error"
                    fi
                    break
                    ;;
                "UNKNOWN")
                    echo "Unable to retrieve execution status"
                    break
                    ;;
            esac
            last_status="$status"
        fi
        
        sleep 10
    done
    
    echo ""
    echo "Final execution status: $status"
    echo "Total runtime: ${elapsed} seconds"
    
    if [[ "$status" == "SUCCEEDED" ]]; then
        echo ""
        echo -e "${GREEN}Pipeline Components Completed:${NC}"
        echo "  1. Data Ingestion (ECS Fargate)"
        echo "  2. Embedding Generation (AWS Batch)"
        echo "  3. Basic Case Clustering (AWS Batch)"
        echo "  4. Term-by-Term Clustering (AWS Batch)"
        echo ""
        echo "Results available in:"
        echo "  S3: s3://scotustician/analysis/"
        echo "  PostgreSQL: embeddings table"
        echo ""
        echo "Cost tracking notifications sent to SNS topic."
    fi
}