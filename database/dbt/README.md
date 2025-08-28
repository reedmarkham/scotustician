# Scotustician dbt Project

This dbt project transforms Supreme Court oral argument data stored in the RDS PostgreSQL database.

## Architecture

The dbt project runs on AWS ECS Fargate and connects to the RDS PostgreSQL instance within the VPC. It includes:

- **ECS Cluster**: Runs dbt transformations as Fargate tasks
- **EventBridge**: Schedules daily dbt runs at 2 AM UTC
- **Lambda Trigger**: Manual execution of dbt commands
- **CloudWatch Logs**: Captures dbt run logs

## Project Structure

```
dbt/
├── models/
│   ├── bronze/          # Raw data layer with minimal transformations
│   ├── silver/          # Cleaned and enriched data with business logic
│   └── gold/            # Business-ready analytics tables
├── macros/              # Reusable SQL functions
├── tests/               # Data quality tests
└── profiles.yml         # Database connection configuration
```

## Models (Medallion Architecture)

### Bronze Layer (Raw)
- `bronze_transcript_embeddings` - Raw transcript embeddings with basic type casting
- `bronze_oa_text` - Raw oral argument utterances with computed fields
- `bronze_document_chunks` - Raw document chunk embeddings

### Silver Layer (Refined)
- `silver_case_summaries` - Aggregated case statistics and metrics

### Gold Layer (Business-Ready)
- `gold_oral_arguments_analytics` - Case-level analytics with engagement metrics
- `gold_speaker_analytics` - Speaker participation and performance metrics

## Running dbt

### Scheduled Runs
dbt runs automatically every Sunday at 12 PM ET (Eastern Time) via EventBridge.

### Manual Execution
Use the Lambda trigger function to run dbt commands:

```bash
aws lambda invoke \
  --function-name <DbtTriggerFunctionName> \
  --payload '{"dbt_command": "dbt run"}' \
  response.json
```

Available commands:
- `dbt run` - Run all models
- `dbt test` - Run data quality tests
- `dbt run --models bronze` - Run only bronze layer models
- `dbt run --models silver` - Run only silver layer models
- `dbt run --models gold` - Run only gold layer models
- `dbt run --models +gold_oral_arguments_analytics` - Run specific model and dependencies

### Local Development
To run dbt locally:

1. Install dbt-postgres: `pip install dbt-postgres`
2. Set environment variables for database connection
3. Run: `dbt run --profiles-dir .`

## Monitoring

View dbt logs in CloudWatch:
- Log Group: `/ecs/scotustician-dbt`
- Filter by task ID or timestamp to find specific runs

## Database Connection

Connection details are retrieved from AWS Secrets Manager and injected as environment variables:
- `DB_HOST` - RDS endpoint
- `DB_PORT` - PostgreSQL port (5432)
- `DB_NAME` - Database name (scotustician)
- `DB_USER` - Database username
- `DB_PASSWORD` - Database password