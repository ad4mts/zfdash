# Use a suitable Python base image
# Update python version when updating uv pinned version; match .python-version to avoid issues with wheels (no longer required).
FROM python:3.13-slim-bookworm

# Set working directory
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 1. Update apt sources to include contrib and non-free-firmware, then install dependencies
#    - ca-certificates: uv needs this to verify SSL when downloading Python/Packages.
#    - curl: useful for healthchecks/debugging
#    - git: Required if project installs any packages from git URLs (just in case).
#    - zfsutils-linux/sudo: ZfDash dependencies
RUN echo "deb http://deb.debian.org/debian bookworm main contrib non-free-firmware" > /etc/apt/sources.list.d/custom.list && \
    echo "deb http://deb.debian.org/debian-security bookworm-security main contrib non-free-firmware" >> /etc/apt/sources.list.d/custom.list && \
    apt-get update && \
    export DEBIAN_FRONTEND=noninteractive && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    zfsutils-linux \
    sudo && \
    # Remove baked-in hostid to prevent mismatches with host ZFS pools
    rm -f /etc/hostid && \
    # Clean up apt cache
    rm -rf /var/lib/apt/lists/*

# Copy and setup entrypoint script for hostid synchronization
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 2. Install Python Dependencies (The Optimization Layer)
#    We copy ONLY the lockfiles first.
COPY pyproject.toml uv.lock ./

#    We use --no-install-project so we don't need 'src/' or 'README.md' yet.
#    Docker will skip this slow step if cached even if source code changes.
RUN uv sync --frozen --no-install-project --no-dev --no-editable

# 3. Copy Application Code
#    copy the source and README.
COPY README.md ./
COPY src/ ./src/

#    Install Python dependencies using uv from lockfile (reproducible, no dev deps)
#    ZfDash is just scripts, but this is fast/safe to run anyway (most dependencies already installed).
#    README.md is required by hatchling build backend (referenced in pyproject.toml)
RUN uv sync --frozen --no-dev --no-editable

# 4. Enable the Virtual Environment globally
ENV PATH="/app/.venv/bin:$PATH"

# Document volumes and ports
VOLUME ["/opt/zfdash/data", "/root/.config/ZfDash"]
EXPOSE 5001
# Set entrypoint to handle hostid synchronization
ENTRYPOINT ["/entrypoint.sh"]

# 5. Clean CMD
#    Because of the ENV PATH above, we can just call 'python'. (uv run can take longer to start)
CMD ["python", "src/main.py", "--web", "--host", "0.0.0.0", "--port", "5001"]
