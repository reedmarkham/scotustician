#!/bin/bash

# Cost-effective ad-hoc case clustering analysis using AWS Batch
# Uses spot instances for maximum cost savings

set -e

# Configuration with defaults
STACK_NAME=${STACK_NAME:-"ScotusticianClusteringStack"}
AWS_REGION=${AWS_REGION:-"us-east-1"}
S3_BUCKET=${S3_BUCKET:-"scotustician"}
OUTPUT_PREFIX=${OUTPUT_PREFIX:-"analysis/case-clustering"}

# Analysis parameters
TSNE_PERPLEXITY=${TSNE_PERPLEXITY:-30}
MIN_CLUSTER_SIZE=${MIN_CLUSTER_SIZE:-5}
RANDOM_STATE=${RANDOM_STATE:-42}

# Term filtering parameters (default to 1980-2025 range)
START_TERM=${START_TERM:-"1980"}
END_TERM=${END_TERM:-"2025"}

echo "Starting case cluster generation"
echo "Configuration:"
echo "  - Stack: $STACK_NAME"
echo "  - Region: $AWS_REGION"
echo "  - Output: s3://$S3_BUCKET/$OUTPUT_PREFIX/"
echo "  - t-SNE perplexity: $TSNE_PERPLEXITY"
echo "  - HDBSCAN min cluster size: $MIN_CLUSTER_SIZE"
echo "  - Term range: $START_TERM to $END_TERM"
echo

# Get AWS Batch configuration from clustering stack
echo "Retrieving AWS Batch configuration..."
JOB_QUEUE_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ClusteringJobQueueArn'].OutputValue" \
  --output text)

JOB_DEFINITION_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ClusteringJobDefinitionArn'].OutputValue" \
  --output text)

if [[ -z "$JOB_QUEUE_ARN" || -z "$JOB_DEFINITION_ARN" ]]; then
  echo "ERROR: Failed to retrieve Batch configuration from CloudFormation"
  echo "   Make sure the stack '$STACK_NAME' is deployed with Batch resources"
  exit 1
fi

echo "Retrieved Batch configuration"
echo "  - Job Queue: $(basename "$JOB_QUEUE_ARN")"
echo "  - Job Definition: $(basename "$JOB_DEFINITION_ARN")"
echo

# Submit the clustering job
JOB_NAME="case-clustering-$(date +%Y%m%d-%H%M%S)"
echo "Submitting case clustering job..."
echo "Job configuration:"
echo "  - Name: $JOB_NAME"
echo "  - Queue: $(basename "$JOB_QUEUE_ARN")"
echo "  - Expected runtime: 5-15 minutes"
echo "  - Estimated cost: $0.02-$0.10 (spot pricing)"
echo

JOB_ID=$(aws batch submit-job \
  --job-name "$JOB_NAME" \
  --job-queue "$JOB_QUEUE_ARN" \
  --job-definition "$JOB_DEFINITION_ARN" \
  --parameters \
    S3_BUCKET="$S3_BUCKET",\
    OUTPUT_PREFIX="$OUTPUT_PREFIX",\
    TSNE_PERPLEXITY="$TSNE_PERPLEXITY",\
    MIN_CLUSTER_SIZE="$MIN_CLUSTER_SIZE",\
    RANDOM_STATE="$RANDOM_STATE",\
    START_TERM="$START_TERM",\
    END_TERM="$END_TERM" \
  --region "$AWS_REGION" \
  --query "jobId" \
  --output text)

if [[ -z "$JOB_ID" ]]; then
  echo "ERROR: Failed to submit Batch job"
  exit 1
fi

echo "Job submitted successfully!"
echo "  - Job ID: $JOB_ID"
echo

# Monitor job status
echo "Monitoring job status..."
echo "Press Ctrl+C to stop monitoring (job will continue running)"
echo

LAST_STATUS=""
START_TIME=$(date +%s)

while true; do
  # Get job status
  STATUS=$(aws batch describe-jobs \
    --jobs "$JOB_ID" \
    --region "$AWS_REGION" \
    --query "jobs[0].status" \
    --output text 2>/dev/null || echo "UNKNOWN")
  
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))
  
  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    case "$STATUS" in
      "SUBMITTED")
        echo "Job submitted, waiting for resources... (${ELAPSED}s)"
        ;;
      "PENDING")
        echo "Job pending, waiting for compute environment... (${ELAPSED}s)"
        ;;
      "RUNNABLE")
        echo "Job runnable, starting execution... (${ELAPSED}s)"
        ;;
      "RUNNING")
        echo "Job running! (${ELAPSED}s)"
        ;;
      "SUCCEEDED")
        echo "Job completed successfully! (${ELAPSED}s)"
        break
        ;;
      "FAILED")
        echo "Job failed (${ELAPSED}s)"
        # Get failure reason
        REASON=$(aws batch describe-jobs \
          --jobs "$JOB_ID" \
          --region "$AWS_REGION" \
          --query "jobs[0].statusReason" \
          --output text)
        echo "  - Reason: $REASON"
        break
        ;;
      "UNKNOWN")
        echo "ERROR: Unable to retrieve job status"
        break
        ;;
    esac
    LAST_STATUS="$STATUS"
  fi
  
  sleep 10
done

echo
echo "Final job summary:"
echo "  - Job ID: $JOB_ID"
echo "  - Final status: $STATUS"
echo "  - Runtime: ${ELAPSED} seconds"

if [[ "$STATUS" == "SUCCEEDED" ]]; then
  echo
  echo "Case clustering analysis completed successfully!"
  echo
  echo "Results available at:"
  echo "  - S3 Location: s3://$S3_BUCKET/$OUTPUT_PREFIX/"
  echo "  - CSV Results: case_clustering_results_*.csv"
  echo "  - Visualizations: visualizations/*.html"
  echo "  - SQL Template: join_with_labels_*.sql"
  echo
  echo "Next steps:"
  echo "  1. Download results: aws s3 sync s3://$S3_BUCKET/$OUTPUT_PREFIX/ ./results/"
  echo "  2. Open visualizations in browser"
  echo "  3. When you have labeled data, use the generated SQL template to join results"
  echo
  exit 0
else
  echo
  echo "Job failed. Check logs:"
  echo "  aws logs tail /aws/batch/job --follow --region $AWS_REGION"
  exit 1
fi