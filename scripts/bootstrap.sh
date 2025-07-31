#!/bin/bash
set -euo pipefail

# Get account ID and region from AWS CLI
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-east-1}

echo "Bootstrapping CDK for account: $AWS_ACCOUNT_ID in region: $AWS_REGION"

npx cdk bootstrap \
  --toolkit-stack-name CDKToolkit-scotustician \
  --qualifier sctstcn \
  aws://$AWS_ACCOUNT_ID/$AWS_REGION