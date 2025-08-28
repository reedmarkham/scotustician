FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /dbt

# Install dbt with postgres adapter
RUN pip install --no-cache-dir \
    dbt-postgres==1.7.4 \
    boto3==1.34.11

# Copy dbt project files
COPY dbt_project.yml .
COPY profiles.yml .
COPY models/ models/
COPY macros/ macros/
COPY tests/ tests/
COPY analyses/ analyses/
COPY data/ data/
COPY snapshots/ snapshots/

# Create entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Set environment variables
ENV DBT_PROFILES_DIR=/dbt

# Default command
ENTRYPOINT ["/dbt/entrypoint.sh"]
CMD ["dbt", "run"]