#!/bin/bash
set -e

# Log the command being executed
echo "Executing: $@"

# Export database connection from environment variables
export DBT_HOST=${DB_HOST}
export DBT_PORT=${DB_PORT}
export DBT_USER=${DB_USER}
export DBT_PASSWORD=${DB_PASSWORD}
export DBT_DATABASE=${DB_NAME}

# Run dbt deps to install packages (if any)
dbt deps || true

# Execute the command passed to the container
exec "$@"