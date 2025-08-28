#!/bin/bash

# Scotustician Historical Data Backfill Script
# Processes all SCOTUS oral argument data from 1980-2025
# This is a ONE-TIME operation for historical data

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration for historical backfill
START_DATE=$(date +%Y-%m-%d)
AWS_REGION=${AWS_REGION:-us-east-1}
STACK_NAME=${STACK_NAME:-"ScotusticianOrchestrationStack"}
START_TERM="1980"
END_TERM="2025"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Scotustician Historical Data Backfill${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Processing Terms: $START_TERM - $END_TERM"
echo "Start Date: $START_DATE"
echo "AWS Region: $AWS_REGION"
echo ""
echo -e "${YELLOW}WARNING: This will process 45+ years of SCOTUS data${NC}"
echo -e "${YELLOW}Expected runtime: 2-4 hours${NC}"
echo -e "${YELLOW}Expected cost: $50-100 depending on instance types${NC}"
echo ""

# Confirm before proceeding
read -p "Continue with historical backfill? (y/N): " confirm
if [[ $confirm != "y" && $confirm != "Y" ]]; then
    echo "Backfill cancelled."
    exit 0
fi

echo "Starting Step Functions orchestrated backfill..."
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

# Start execution with historical date range
EXECUTION_NAME="scotustician-backfill-$(date +%Y%m%d-%H%M%S)"

echo "Starting backfill execution: $EXECUTION_NAME"
EXECUTION_ARN=$(aws stepfunctions start-execution \
    --state-machine-arn "$STATE_MACHINE_ARN" \
    --name "$EXECUTION_NAME" \
    --input "{
        \"startTerm\": \"$START_TERM\",
        \"endTerm\": \"$END_TERM\",
        \"mode\": \"backfill\"
    }" \
    --region "$AWS_REGION" \
    --query "executionArn" \
    --output text)

if [[ -z "$EXECUTION_ARN" ]]; then
    echo -e "${RED}ERROR: Failed to start Step Functions execution${NC}"
    exit 1
fi

echo -e "${GREEN}Historical backfill started successfully!${NC}"
echo ""

echo -e "${BLUE}Execution Details:${NC}"
echo "  Name: $EXECUTION_NAME"
echo "  ARN: $EXECUTION_ARN"
echo "  Processing: $START_TERM - $END_TERM terms"
echo ""

echo -e "${BLUE}Monitor your backfill:${NC}"
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

echo -e "${BLUE}Data Processing Overview:${NC}"
echo "  1. Ingest: All SCOTUS oral arguments from $START_TERM-$END_TERM"
echo "  2. Transform: Generate embeddings for ~15,000+ cases"
echo "  3. Cluster: Basic clustering across all years"
echo "  4. Cluster: Term-by-term analysis for temporal patterns"
echo ""

echo -e "${YELLOW}Performance Notes:${NC}"
echo "  • Ingest: ~30-45 minutes (rate-limited by Oyez API)"
echo "  • Transform: ~1-2 hours (GPU acceleration recommended)"
echo "  • Clustering: ~30-60 minutes (parallel processing)"
echo ""

echo -e "${YELLOW}After backfill completion:${NC}"
echo "  • Use ./run.sh for current year updates"
echo "  • Step Functions will be scheduled for automatic current-year processing"
echo "  • Historical data analysis will be available in visualization app"
echo ""

# Optional: Wait and monitor
read -p "Monitor execution progress? (y/n): " monitor
if [[ $monitor == "y" || $monitor == "Y" ]]; then
    monitor_execution
else
    echo -e "${YELLOW}Backfill is running in the background.${NC}"
    echo "You can close your laptop - the backfill will continue running on AWS!"
    echo ""
    echo -e "${GREEN}Next steps after backfill completes:${NC}"
    echo "  1. Verify data in S3 bucket and PostgreSQL"
    echo "  2. Deploy visualization stack to explore historical patterns"
    echo "  3. Use ./run.sh for ongoing current-year data processing"
fi

# Function to monitor Step Functions execution
monitor_execution() {
    echo ""
    echo -e "${YELLOW}Monitoring Step Functions backfill...${NC}"
    echo "Press Ctrl+C to stop monitoring (backfill will continue running)"
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
        local elapsed_hours=$((elapsed / 3600))
        local elapsed_minutes=$(((elapsed % 3600) / 60))
        
        if [[ "$status" != "$last_status" ]]; then
            case "$status" in
                "RUNNING")
                    echo "Backfill is running... (${elapsed_hours}h ${elapsed_minutes}m)"
                    ;;
                "SUCCEEDED")
                    echo -e "${GREEN}Backfill completed successfully! (${elapsed_hours}h ${elapsed_minutes}m)${NC}"
                    break
                    ;;
                "FAILED"|"TIMED_OUT"|"ABORTED")
                    echo -e "${RED}Backfill failed with status: $status (${elapsed_hours}h ${elapsed_minutes}m)${NC}"
                    
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
        
        sleep 30  # Check every 30 seconds for long-running backfill
    done
    
    echo ""
    echo "Final execution status: $status"
    echo "Total runtime: ${elapsed_hours} hours ${elapsed_minutes} minutes"
    
    if [[ "$status" == "SUCCEEDED" ]]; then
        echo ""
        echo -e "${GREEN}Historical Backfill Complete!${NC}"
        echo ""
        echo -e "${GREEN}Data Processing Summary:${NC}"
        echo "  1. ✓ Historical Data Ingestion ($START_TERM-$END_TERM)"
        echo "  2. ✓ Embedding Generation (~15,000+ cases)"
        echo "  3. ✓ Basic Case Clustering (cross-temporal analysis)"
        echo "  4. ✓ Term-by-Term Clustering (temporal patterns)"
        echo ""
        echo "Results available in:"
        echo "  S3: s3://scotustician/analysis/ (clustering results)"
        echo "  S3: s3://scotustician/raw/oa/ (raw data)"
        echo "  PostgreSQL: embeddings table (~15,000+ vectors)"
        echo ""
        echo -e "${BLUE}Next Steps:${NC}"
        echo "  1. Deploy visualization: cd infrastructure && cdk deploy ScotusticianVisualizationStack"
        echo "  2. For current year updates: ./run.sh"
        echo "  3. View historical analysis in web app"
        echo ""
        echo "Cost tracking notifications sent to SNS topic."
    fi
}