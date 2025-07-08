# Fargate to RDS Connectivity Setup Guide

## Overview
This guide explains how to connect your Fargate application to the PostgreSQL RDS instance using private networking without NAT gateways.

## Changes Made

### 1. VPC Configuration Updates
- Added private isolated subnets to the VPC
- Added Secrets Manager VPC endpoint for private subnet access
- Maintained existing S3, ECR, and CloudWatch Logs endpoints

### 2. Fargate Task Definition Updates
- **Environment Variables**: Changed from OpenSearch to PostgreSQL
  - `POSTGRES_HOST`: Database endpoint (set via CDK context)
  - `POSTGRES_USER`: postgres
  - `POSTGRES_DB`: scotustician
- **Secrets**: Added PostgreSQL password from Secrets Manager
- **Security Group**: Created dedicated security group for Fargate tasks
- **IAM Permissions**: Added Secrets Manager access, removed OpenSearch permissions

### 3. Security Group Configuration
- Created `FargateSecurityGroup` that allows outbound traffic
- This security group ID is output for RDS configuration

## Deployment Steps

### Step 1: Update CDK Context
Add these values to your CDK context (cdk.json or CLI):

```json
{
  "postgresHost": "your-rds-endpoint.region.rds.amazonaws.com",
  "postgresSecretName": "your-postgres-secret-name"
}
```

### Step 2: Deploy Infrastructure
```bash
cd infra
npm install
cdk deploy ScotusticianSharedStack
cdk deploy ScotusticianTransformersStack
```

### Step 3: Configure RDS Security Group
In your RDS stack/console, add an inbound rule to the RDS security group:
- **Type**: PostgreSQL (port 5432)
- **Source**: The `FargateSecurityGroupId` from the CDK output
- **Description**: Allow Fargate tasks to access PostgreSQL

### Step 4: Verify Database Schema
Ensure your RDS instance has the required tables. The application expects:
- `scotustician.transcript_embeddings`
- `scotustician.raw_transcripts`
- `scotustician.case_decisions`
- `scotustician.justice_votes`

### Step 5: Run Tasks in Private Subnets
When running ECS tasks, specify:
- **Subnets**: Use the `PrivateSubnetId1` and `PrivateSubnetId2` from CDK outputs
- **Security Groups**: Use the `FargateSecurityGroupId` from CDK outputs
- **Assign Public IP**: Disabled (private subnets)

## Cost Optimization
- **$0/month**: No NAT Gateway charges
- **$0/month**: No VPC Peering charges
- **~$45/month**: VPC Endpoint charges (4 endpoints × ~$11/month each)
- **Trade-off**: Small VPC endpoint cost for secure, private connectivity

## Network Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    ScotusticianVPC                          │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │  Public Subnets │    │      Private Subnets            │ │
│  │                 │    │                                 │ │
│  │  - NAT Gateway  │    │  ┌─────────────────────────────┐ │ │
│  │    (Not Used)   │    │  │      Fargate Tasks          │ │ │
│  │                 │    │  │                             │ │ │
│  └─────────────────┘    │  │  - PostgreSQL Client       │ │ │
│                         │  │  - S3 Access via Endpoint   │ │ │
│  ┌─────────────────┐    │  │  - Secrets via Endpoint     │ │ │
│  │  VPC Endpoints  │    │  └─────────────────────────────┘ │ │
│  │                 │    │                                 │ │
│  │  - S3 Gateway   │◄───┤  ┌─────────────────────────────┐ │ │
│  │  - ECR          │    │  │         RDS Instance        │ │ │
│  │  - Logs         │    │  │                             │ │ │
│  │  - Secrets Mgr  │    │  │  - PostgreSQL 16.1          │ │ │
│  └─────────────────┘    │  │  - pgvector extension       │ │ │
│                         │  │  - Private connectivity     │ │ │
│                         │  └─────────────────────────────┘ │ │
│                         └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Connection Issues
1. **Check Security Groups**: Ensure RDS allows inbound from Fargate SG
2. **Check Subnets**: Ensure tasks run in private subnets
3. **Check VPC**: Ensure RDS and Fargate are in the same VPC
4. **Check Secrets**: Verify secret name and format in Secrets Manager

### VPC Endpoint Issues
1. **DNS Resolution**: Ensure VPC has DNS resolution enabled
2. **Route Tables**: Private subnets should route to VPC endpoints
3. **Security Groups**: VPC endpoints need proper security group rules

### Task Startup Issues
1. **Check Logs**: Look at CloudWatch Logs for error messages
2. **Check IAM**: Ensure task role has Secrets Manager permissions
3. **Check Environment**: Verify all required environment variables are set

## Testing Connectivity
```bash
# Test from within the VPC (e.g., EC2 instance)
psql -h your-rds-endpoint.region.rds.amazonaws.com -U postgres -d scotustician

# Test Secrets Manager access
aws secretsmanager get-secret-value --secret-id your-postgres-secret-name
```