#!/bin/bash

# AWS Batch job submission script for embedding generation
# Replaces the previous ECS-based embeddings.sh script

set -e

# Configuration with defaults
STACK_NAME=${STACK_NAME:-"ScotusticianTransformersStack"}
AWS_REGION=${AWS_REGION:-"us-east-1"}
FILES_PER_JOB=${FILES_PER_JOB:-10}
MODEL_NAME=${MODEL_NAME:-"baai/bge-m3"}
MODEL_DIMENSION=${MODEL_DIMENSION:-1024}
BATCH_SIZE=${BATCH_SIZE:-4}
MAX_WORKERS=${MAX_WORKERS:-1}
INCREMENTAL=${INCREMENTAL:-true}
S3_BUCKET=${S3_BUCKET:-scotustician}
RAW_PREFIX=${RAW_PREFIX:-raw/oa}

echo "Starting AWS Batch embedding generation"
echo "Configuration:"
echo "  - Stack: $STACK_NAME"
echo "  - Region: $AWS_REGION"
echo "  - Files per job: $FILES_PER_JOB"
echo "  - Model: $MODEL_NAME (${MODEL_DIMENSION}d)"
echo "  - Batch size: $BATCH_SIZE"
echo "  - Incremental: $INCREMENTAL"
echo

# Get CloudFormation outputs
echo "Retrieving AWS Batch configuration..."
JOB_QUEUE_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BatchJobQueueArn'].OutputValue" \
  --output text)

JOB_DEFINITION_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BatchJobDefinitionArn'].OutputValue" \
  --output text)

PROCESSING_QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ProcessingQueueUrl'].OutputValue" \
  --output text)

CHECKPOINT_QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='CheckpointQueueUrl'].OutputValue" \
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

# Count total files to determine array size
echo "Counting files to process..."
TOTAL_FILES=$(aws s3api list-objects-v2 \
  --bucket "$S3_BUCKET" \
  --prefix "$RAW_PREFIX" \
  --query "length(Contents[])" \
  --output text)

if [[ "$TOTAL_FILES" == "None" || "$TOTAL_FILES" -eq 0 ]]; then
  echo "WARNING: No files found in s3://$S3_BUCKET/$RAW_PREFIX"
  exit 0
fi

# Calculate array size (number of jobs needed)
ARRAY_SIZE=$(( (TOTAL_FILES + FILES_PER_JOB - 1) / FILES_PER_JOB ))

echo "Found $TOTAL_FILES files"
echo "  - Jobs needed: $ARRAY_SIZE (processing $FILES_PER_JOB files per job)"
echo

# Submit array job
JOB_NAME="embedding-generation-$(date +%Y%m%d-%H%M%S)"

echo "Submitting Batch array job..."
echo "Job configuration:"
echo "  - Name: $JOB_NAME"
echo "  - Array size: 0-$((ARRAY_SIZE-1))"
echo "  - Queue: $(basename "$JOB_QUEUE_ARN")"
echo

JOB_ID=$(aws batch submit-job \
  --job-name "$JOB_NAME" \
  --job-queue "$JOB_QUEUE_ARN" \
  --job-definition "$JOB_DEFINITION_ARN" \
  --array-properties size=$ARRAY_SIZE \
  --parameters \
    FILES_PER_JOB="$FILES_PER_JOB",\
    MODEL_NAME="$MODEL_NAME",\
    MODEL_DIMENSION="$MODEL_DIMENSION",\
    BATCH_SIZE="$BATCH_SIZE",\
    MAX_WORKERS="$MAX_WORKERS",\
    INCREMENTAL="$INCREMENTAL",\
    S3_BUCKET="$S3_BUCKET",\
    RAW_PREFIX="$RAW_PREFIX",\
    PROCESSING_QUEUE_URL="$PROCESSING_QUEUE_URL",\
    CHECKPOINT_QUEUE_URL="$CHECKPOINT_QUEUE_URL" \
  --region "$AWS_REGION" \
  --query "jobId" \
  --output text)

if [[ -z "$JOB_ID" ]]; then
  echo "ERROR: Failed to submit Batch job"
  exit 1
fi

echo "Job submitted successfully!"
echo "  - Job ID: $JOB_ID"
echo "  - Array size: $ARRAY_SIZE jobs"
echo

# Monitor job status
echo "Monitoring job status..."
echo "Press Ctrl+C to stop monitoring (job will continue running)"
echo

LAST_STATUS=""
while true; do
  # Get job status
  STATUS=$(aws batch describe-jobs \
    --jobs "$JOB_ID" \
    --region "$AWS_REGION" \
    --query "jobs[0].status" \
    --output text 2>/dev/null || echo "UNKNOWN")
  
  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    case "$STATUS" in
      "SUBMITTED")
        echo "Job submitted, waiting for resources..."
        ;;
      "PENDING")
        echo "Job pending, waiting for compute environment..."
        ;;
      "RUNNABLE")
        echo "Job runnable, starting execution..."
        ;;
      "RUNNING")
        echo "Job running!"
        # Show running array children
        RUNNING_COUNT=$(aws batch list-jobs \
          --job-queue "$JOB_QUEUE_ARN" \
          --job-status RUNNING \
          --region "$AWS_REGION" \
          --query "length(jobList[?starts_with(jobName, \`$JOB_NAME\`)])" \
          --output text)
        echo "  - Running children: $RUNNING_COUNT/$ARRAY_SIZE"
        ;;
      "SUCCEEDED")
        echo "Job completed successfully!"
        break
        ;;
      "FAILED")
        echo "Job failed"
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
echo
echo "View logs with:"
echo "  aws logs tail /aws/batch/job --follow --region $AWS_REGION"
echo
echo "Monitor job details:"
echo "  aws batch describe-jobs --jobs $JOB_ID --region $AWS_REGION"
echo
echo "Check SQS queues for progress:"
if [[ -n "$PROCESSING_QUEUE_URL" ]]; then
  echo "  aws sqs get-queue-attributes --queue-url $PROCESSING_QUEUE_URL --attribute-names All --region $AWS_REGION"
fi
if [[ -n "$CHECKPOINT_QUEUE_URL" ]]; then
  echo "  aws sqs get-queue-attributes --queue-url $CHECKPOINT_QUEUE_URL --attribute-names All --region $AWS_REGION"
fi

if [[ "$STATUS" == "SUCCEEDED" ]]; then
  echo "Embedding generation completed successfully!"
  exit 0
else
  echo "Check job status and logs for details"
  exit 1
fi