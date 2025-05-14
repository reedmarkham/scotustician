# 🏛️ scotustician

**scotustician** is a data pipeline and embedding generation service for Supreme Court of the United States (SCOTUS) oral argument (OA) transcripts. 

It supports downstream search, clustering, and visualization tasks by processing SCOTUS OA transcripts into structured embeddings using Hugging Face transformer models.

---

## 📦 Overview

This project is divided into the following components:

```
scotustician/
├── etl/               # FastAPI service for SCOTUS data retrieval and preprocessing
├── transformers/      # Hugging Face pipeline for generating and storing text embeddings
├── infra/             # AWS CDK code defining ECS services, clusters, and infrastructure
└── .github/workflows/ # CI/CD pipelines for automatic deployment via GitHub Actions
```

---

## ⚙️ Architecture

**Infrastructure:**
- AWS CDK (TypeScript) to provision services, clusters, and networking
- ECS Fargate for `etl` (stateless FastAPI service)
- ECS EC2 w/ GPU for `transformers` (long-running embedding generator)
- GitHub Actions CI/CD

**Data Flow:**
1. `etl` collects and preprocesses SCOTUS metadata and case text from Oyez.org API.
2. Processed text from `etl` is passed to `transformers`, which uses [Hugging Face models](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) to generate embeddings.
3. Embeddings are stored in an [OpenSearch vector database](https://www.github.com/reedmarkham/scotustician-db) deployed separately.

---

## 🚀 Deployment

This project uses GitHub Actions CI/CD and AWS CDK to automatically build and deploy services:

- GitHub Actions workflows (`.github/workflows/`) detect changes in `etl/` or `transformers/`, build Docker images, and deploy via `cdk deploy`.
- AWS resources are defined in `infra/lib/`, including:
  - VPC and ECS Clusters
  - Fargate and EC2 Task Definitions
  - GPU-backed Auto Scaling Group for `transformers`
