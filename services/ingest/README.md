# Scotustician Data Ingestion Pipeline

## Overview

This directory contains the consolidated dlt-based data ingestion pipeline for Supreme Court oral arguments from the Oyez.org API. The pipeline extracts transcript data and metadata, handling incremental loading and error management automatically.

## Reference

Original work by [walkerdb](https://github.com/walkerdb/supreme_court_transcripts) - Supreme Court transcript collection and processing.

## Architecture

### DLT Pipeline Structure

The ingestion system uses dlt (data load tool) to provide a declarative, configuration-driven approach to data extraction:

- **Source**: `oyez_scotus_source()` - Extracts oral arguments from Oyez.org API
- **Resources**: 
  - `oral_arguments` - Main data extraction with incremental loading
  - `ingestion_summary` - Pipeline metadata and statistics
- **Destination**: AWS S3 with configurable bucket structure

### Key Features

#### Automatic Capabilities
- **Rate limiting**: Built into dlt's request handling
- **Incremental loading**: dlt state management tracks extraction progress
- **Error handling & retries**: Automatic retry logic with exponential backoff
- **Schema management**: Automatic detection and evolution
- **Junk data handling**: Malformed records logged to separate table

#### Performance Optimizations
Tuned for c5.large instances (2 vCPUs, 4GB RAM):
- **MAX_WORKERS**: 2 concurrent workers
- **BATCH_SIZE**: 5 records per batch for memory efficiency
- **MEMORY_LIMIT**: 3GB allocated, 1GB reserved for system overhead

## File Structure

### Core Files
- `main.py` - Consolidated dlt pipeline with incremental loading
- `helpers.py` - Utility functions and legacy API compatibility
- `Dockerfile` - Container configuration for AWS deployment

### Configuration
- `.dlt/config.toml` - Pipeline configuration
- `.dlt/secrets.toml` - Credentials with environment variable substitution
- `requirements.txt` - Python dependencies

### Infrastructure
- CDK stack configured in `../../infrastructure/lib/scotustician-ingest-stack.ts`

## Configuration

### Environment Variables

#### Required
- `S3_BUCKET` - Target S3 bucket name (default: "scotustician")
- AWS credentials via IAM roles or environment variables

#### Optional Tuning
- `START_TERM` - Starting term year (default: 1980)
- `END_TERM` - Ending term year (default: current year)
- `MAX_WORKERS` - Concurrent API requests (default: 2)
- `BATCH_SIZE` - Records per processing batch (default: 5)
- `MODE` - Pipeline mode: "ingest" or "test" (default: "ingest")

### DLT Configuration

#### `.dlt/config.toml`
```toml
[sources.oyez_scotus_source]
max_parallel = 2

[destination.s3]
bucket_url = "s3://scotustician"
```

#### `.dlt/secrets.toml`
```toml
[destination.s3.credentials]
aws_access_key_id = "${AWS_ACCESS_KEY_ID}"
aws_secret_access_key = "${AWS_SECRET_ACCESS_KEY}"
region_name = "${AWS_DEFAULT_REGION}"
```

## Usage

### Local Development

#### Test Mode
```bash
export MODE=test
python main.py
```
Test mode processes a limited dataset (2023-2024 terms) to filesystem destination.

#### Full Pipeline
```bash
export S3_BUCKET=your-bucket
export AWS_ACCESS_KEY_ID=your-key
export AWS_SECRET_ACCESS_KEY=your-secret
python main.py
```

### AWS Deployment

The pipeline runs on AWS Fargate using the CDK-defined infrastructure:

1. **Build and deploy infrastructure:**
   ```bash
   cd ../infrastructure
   npm run build
   cdk deploy ScotusticianIngestStack
   ```

2. **Run task manually:**
   ```bash
   aws ecs run-task --cluster your-cluster --task-definition scotustician-ingest
   ```

### Scheduled Tasks

The ingest task is orchestrated via Step Functions scheduling:

- **Scheduled Execution**: Runs twice weekly (Monday/Thursday 10 AM ET) during Supreme Court term (October-July)
  - Automatically processes current year data only
  - Triggered by EventBridge rule in OrchestrationStack
  - Parameters: START_TERM=current year, END_TERM=current year

- **Manual Execution Options**:
  - **Current year**: `./scripts/run.sh` (processes current year only)
  - **Historical backfill**: `./scripts/backfill.sh` (processes 1980-2025)
  - **Individual components**: See `scripts/README.md`

## Data Output

### S3 Structure
```
scotustician/
├── oral_arguments/           # Main oral argument data
│   ├── _dlt_loads/          # DLT load metadata
│   └── oral_arguments.parquet
├── ingestion_summary/        # Pipeline run summaries
└── junk_data/               # Malformed records
```

### Data Schema

#### Oral Arguments
- `id` - Unique oral argument identifier
- `term` - Supreme Court term year
- `case_id` - Case identifier
- `docket_number` - Court docket number
- `title` - Case title
- `transcript` - Full transcript data with speaker sections
- `_dlt_extracted_at` - Extraction timestamp for incremental loading

#### Junk Data
- `junk_id` - Unique identifier for malformed record
- `term` - Term where error occurred
- `context` - Error context (e.g., "missing_docket_number")
- `item` - Truncated problematic data
- `timestamp` - Error timestamp

## Migration from Legacy Pipeline

The current pipeline represents a consolidated migration from the original multi-file approach:

### Improvements
1. **Reduced Complexity**: 60% fewer lines of code compared to original
2. **Built-in Best Practices**: Automatic rate limiting, retries, state management
3. **Better Incremental Loading**: No S3 scanning required for existing data detection
4. **Configuration-Driven**: Environment-based configuration for different deployment scenarios
5. **Automatic Schema Evolution**: Handles API changes gracefully

### Backward Compatibility
- Maintains same S3 bucket structure and naming conventions
- Uses identical environment variable names
- Preserves AWS IAM permission requirements

## Troubleshooting

### Common Issues

#### Rate Limiting
dlt handles Oyez.org API rate limits automatically. If experiencing issues:
- Reduce `MAX_WORKERS` environment variable
- Increase `REQUEST_TIMEOUT` for slower responses

#### Memory Issues
For memory-constrained environments:
- Reduce `BATCH_SIZE` to process fewer records at once
- Lower `MEMORY_LIMIT_MB` environment variable
- Consider using smaller instance types

#### Incremental Loading
dlt maintains state automatically. To reset incremental loading:
```bash
rm -rf .dlt/pipelines/
```

### Monitoring
- Check CloudWatch logs for pipeline execution details
- Monitor S3 bucket for output files and structure
- Use `MODE=test` for validation with limited data

## Development

### Adding New Data Sources
1. Define new `@dlt.resource` in `oyez_scotus_source()`
2. Update configuration in `.dlt/config.toml`
3. Test with `MODE=test` before production deployment

### Modifying Data Processing
- Update resource functions in `main.py`
- Test schema changes with limited term ranges
- Validate output structure matches downstream requirements

## Support

For issues related to:
- **Pipeline logic**: Review `main.py` source and resource definitions
- **Infrastructure**: Check CDK stack in `../infrastructure/`
- **Data quality**: Monitor junk_data table for systematic issues
- **Performance**: Adjust environment variables for instance capacity