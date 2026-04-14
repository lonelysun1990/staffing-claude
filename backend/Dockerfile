FROM python:3.11-slim

WORKDIR /app

# Install system libraries required by numpy, pandas, scipy, matplotlib
# - libstdc++6: GNU C++ standard library (required by numpy C extensions)
# - libgomp1: OpenMP runtime (used by numpy/scipy for parallelization)
# - libopenblas0: BLAS library for linear algebra
# - libgfortran5: Fortran runtime (used by scipy)
# - gcc, g++: Compilers needed to build some Python packages
# - libpq-dev: PostgreSQL client library (for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libstdc++6 \
    libgomp1 \
    libopenblas0 \
    libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

# Main app dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create directory for per-tool sandbox environments
RUN mkdir -p /sandbox-envs && chmod 755 /sandbox-envs
ENV SANDBOX_ENVS_DIR=/sandbox-envs

# Copy application code (venv, .env, __pycache__ excluded via .dockerignore)
COPY . .

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
