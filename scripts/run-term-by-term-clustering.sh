#!/bin/bash

# Term-by-term case clustering analysis using AWS Batch
# Runs clustering for each individual term within a range and stores results by term
# Uses spot instances for maximum cost savings

set -e

# Configuration with defaults
STACK_NAME=${STACK_NAME:-"ScotusticianClusteringStack"}
AWS_REGION=${AWS_REGION:-"us-east-1"}
S3_BUCKET=${S3_BUCKET:-"scotustician"}
BASE_OUTPUT_PREFIX=${BASE_OUTPUT_PREFIX:-"analysis/case-clustering-by-term"}

# Analysis parameters
TSNE_PERPLEXITY=${TSNE_PERPLEXITY:-30}
MIN_CLUSTER_SIZE=${MIN_CLUSTER_SIZE:-5}
RANDOM_STATE=${RANDOM_STATE:-42}

# Term range parameters (default to 1980-2025 range)
START_TERM=${START_TERM:-"1980"}
END_TERM=${END_TERM:-"2025"}

# Parallel processing settings
MAX_CONCURRENT_JOBS=${MAX_CONCURRENT_JOBS:-3}
POLL_INTERVAL=${POLL_INTERVAL:-30}

echo "Starting term-by-term case cluster generation"
echo "Configuration:"
echo "  - Stack: $STACK_NAME"
echo "  - Region: $AWS_REGION"
echo "  - Base Output: s3://$S3_BUCKET/$BASE_OUTPUT_PREFIX/"
echo "  - t-SNE perplexity: $TSNE_PERPLEXITY"
echo "  - HDBSCAN min cluster size: $MIN_CLUSTER_SIZE"
echo "  - Term range: $START_TERM to $END_TERM"
echo "  - Max concurrent jobs: $MAX_CONCURRENT_JOBS"
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

# Generate list of terms to process
TERMS=()
for ((year=$START_TERM; year<=$END_TERM; year++)); do
  TERMS+=("$year")
done

echo "Will process ${#TERMS[@]} terms: ${TERMS[@]}"
echo

# Track job submissions
declare -A SUBMITTED_JOBS
declare -A JOB_TERMS
COMPLETED_COUNT=0
FAILED_COUNT=0
TOTAL_JOBS=${#TERMS[@]}

# Function to submit a job for a single term
submit_term_job() {
  local term=$1
  local job_name="case-clustering-term-${term}-$(date +%Y%m%d-%H%M%S)"
  local output_prefix="${BASE_OUTPUT_PREFIX}/term-${term}"
  
  echo "Submitting job for term $term..."
  
  local job_id=$(aws batch submit-job \
    --job-name "$job_name" \
    --job-queue "$JOB_QUEUE_ARN" \
    --job-definition "$JOB_DEFINITION_ARN" \
    --parameters \
      S3_BUCKET="$S3_BUCKET",\
      OUTPUT_PREFIX="$output_prefix",\
      TSNE_PERPLEXITY="$TSNE_PERPLEXITY",\
      MIN_CLUSTER_SIZE="$MIN_CLUSTER_SIZE",\
      RANDOM_STATE="$RANDOM_STATE",\
      START_TERM="$term",\
      END_TERM="$term" \
    --region "$AWS_REGION" \
    --query "jobId" \
    --output text)
  
  if [[ -z "$job_id" ]]; then
    echo "ERROR: Failed to submit job for term $term"
    return 1
  fi
  
  SUBMITTED_JOBS["$job_id"]="SUBMITTED"
  JOB_TERMS["$job_id"]="$term"
  echo "  - Job ID: $job_id for term $term"
  
  return 0
}

# Function to check job statuses
check_job_statuses() {
  local job_ids=(${!SUBMITTED_JOBS[@]})
  
  if [[ ${#job_ids[@]} -eq 0 ]]; then
    return 0
  fi
  
  # Get status of all jobs in one call
  local job_statuses=$(aws batch describe-jobs \
    --jobs "${job_ids[@]}" \
    --region "$AWS_REGION" \
    --query "jobs[].[jobId,status]" \
    --output text 2>/dev/null || echo "")
  
  if [[ -z "$job_statuses" ]]; then
    echo "WARNING: Unable to retrieve job statuses"
    return 0
  fi
  
  # Process each job status
  while IFS=$'\t' read -r job_id status; do
    if [[ -z "$job_id" || -z "$status" ]]; then
      continue
    fi
    
    local old_status="${SUBMITTED_JOBS[$job_id]}"
    local term="${JOB_TERMS[$job_id]}"
    
    # Update status if changed
    if [[ "$status" != "$old_status" ]]; then
      SUBMITTED_JOBS["$job_id"]="$status"
      
      case "$status" in
        "SUCCEEDED")
          echo "✓ Term $term completed successfully (Job: $job_id)"
          ((COMPLETED_COUNT++))
          unset SUBMITTED_JOBS["$job_id"]
          unset JOB_TERMS["$job_id"]
          ;;
        "FAILED")
          echo "✗ Term $term failed (Job: $job_id)"
          ((FAILED_COUNT++))
          unset SUBMITTED_JOBS["$job_id"]
          unset JOB_TERMS["$job_id"]
          ;;
        "RUNNING")
          echo "⚡ Term $term is now running (Job: $job_id)"
          ;;
        "RUNNABLE")
          echo "🔄 Term $term is runnable (Job: $job_id)"
          ;;
      esac
    fi
  done <<< "$job_statuses"
}

# Main execution loop
echo "Starting term-by-term clustering jobs..."
echo "Press Ctrl+C to stop monitoring (jobs will continue running)"
echo

START_TIME=$(date +%s)
term_index=0

# Submit initial batch of jobs
while [[ $term_index -lt $TOTAL_JOBS && ${#SUBMITTED_JOBS[@]} -lt $MAX_CONCURRENT_JOBS ]]; do
  term="${TERMS[$term_index]}"
  if submit_term_job "$term"; then
    ((term_index++))
    sleep 2  # Brief pause between submissions
  else
    echo "Failed to submit job for term $term, skipping..."
    ((term_index++))
    ((FAILED_COUNT++))
  fi
done

# Monitor jobs and submit new ones as slots become available
while [[ $term_index -lt $TOTAL_JOBS || ${#SUBMITTED_JOBS[@]} -gt 0 ]]; do
  check_job_statuses
  
  # Submit new jobs if we have capacity and remaining terms
  while [[ $term_index -lt $TOTAL_JOBS && ${#SUBMITTED_JOBS[@]} -lt $MAX_CONCURRENT_JOBS ]]; do
    term="${TERMS[$term_index]}"
    if submit_term_job "$term"; then
      ((term_index++))
      sleep 2  # Brief pause between submissions
    else
      echo "Failed to submit job for term $term, skipping..."
      ((term_index++))
      ((FAILED_COUNT++))
    fi
  done
  
  # Show progress
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))
  REMAINING=$((TOTAL_JOBS - COMPLETED_COUNT - FAILED_COUNT))
  
  if [[ $((ELAPSED % 60)) -eq 0 ]] || [[ ${#SUBMITTED_JOBS[@]} -eq 0 ]]; then
    echo
    echo "Progress Summary (${ELAPSED}s elapsed):"
    echo "  ✓ Completed: $COMPLETED_COUNT"
    echo "  ✗ Failed: $FAILED_COUNT"
    echo "  🔄 Running: ${#SUBMITTED_JOBS[@]}"
    echo "  ⏳ Remaining: $REMAINING"
    echo "  📊 Progress: $((100 * (COMPLETED_COUNT + FAILED_COUNT) / TOTAL_JOBS))%"
  fi
  
  sleep $POLL_INTERVAL
done

FINAL_TIME=$(date +%s)
TOTAL_ELAPSED=$((FINAL_TIME - START_TIME))

echo
echo "=================================="
echo "Term-by-term clustering completed!"
echo "=================================="
echo "Final Summary:"
echo "  - Total terms processed: $TOTAL_JOBS"
echo "  - Successfully completed: $COMPLETED_COUNT"
echo "  - Failed: $FAILED_COUNT"
echo "  - Total runtime: ${TOTAL_ELAPSED} seconds"
echo "  - Average time per term: $((TOTAL_ELAPSED / TOTAL_JOBS)) seconds"
echo

if [[ $COMPLETED_COUNT -gt 0 ]]; then
  echo "Results available at:"
  echo "  - Base S3 Location: s3://$S3_BUCKET/$BASE_OUTPUT_PREFIX/"
  echo "  - Individual term results: s3://$S3_BUCKET/$BASE_OUTPUT_PREFIX/term-YYYY/"
  echo
  echo "Each term directory contains:"
  echo "  - case_clustering_results_*.csv"
  echo "  - case_clustering_metadata_*.json"
  echo "  - visualizations/*.html"
  echo
  echo "Next steps:"
  echo "  1. Download results: aws s3 sync s3://$S3_BUCKET/$BASE_OUTPUT_PREFIX/ ./results/"
  echo "  2. Analyze temporal trends across terms"
  echo "  3. Create visualizations showing cluster evolution over time"
fi

if [[ $FAILED_COUNT -gt 0 ]]; then
  echo
  echo "⚠️  $FAILED_COUNT terms failed. Check logs:"
  echo "  aws logs tail /aws/batch/job --follow --region $AWS_REGION"
fi

exit $([[ $FAILED_COUNT -eq 0 ]] && echo 0 || echo 1)