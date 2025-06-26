# Use a suitable Python base image
FROM python:3.11-slim-bookworm

# Set working directory
WORKDIR /app

# Update apt sources to include contrib and non-free-firmware, then install dependencies
RUN echo "deb http://deb.debian.org/debian bookworm main contrib non-free-firmware" > /etc/apt/sources.list.d/custom.list && \
    echo "deb http://deb.debian.org/debian-security bookworm-security main contrib non-free-firmware" >> /etc/apt/sources.list.d/custom.list && \
    apt-get update && \
    export DEBIAN_FRONTEND=noninteractive && \
    apt-get install -y --no-install-recommends zfsutils-linux sudo && \
    # Clean up apt cache
    rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
# Assuming the main application logic is within src/
COPY src/ ./src/

# Document intended paths for persistent data volumes
VOLUME ["/opt/zfdash/data", "/root/.config/ZfDash"]

# Expose the default web UI port
EXPOSE 5001

# Default command to run the web UI
# Listen on 0.0.0.0 to be accessible from outside the container
# Running as root by default, which is necessary for zfs commands
CMD ["python3", "src/main.py", "--web", "--host", "0.0.0.0", "--port", "5001"]
