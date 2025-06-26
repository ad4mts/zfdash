#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define image and container names
IMAGE_NAME="zfdash-docker"
CONTAINER_NAME="zfdash"

echo "--- Building Docker image: $IMAGE_NAME ---"
# Build the Docker image using the Dockerfile in the current directory
sudo docker build -t "$IMAGE_NAME" .

echo "--- Stopping existing container (if any): $CONTAINER_NAME ---"
# Stop the container if it's running, ignore error if it doesn't exist
sudo docker stop "$CONTAINER_NAME" || true

echo "--- Removing existing container (if any): $CONTAINER_NAME ---"
# Remove the container if it exists, ignore error if it doesn't exist
sudo docker rm "$CONTAINER_NAME" || true

echo "--- Running new container: $CONTAINER_NAME ---"
# Run the new container in detached mode, mapping port 5001,
# mounting /dev/zfs, and running as root.
# Mount volumes for persistent data (credentials, config)
# replacing --privileged with --cap-add SYS_ADMIN (more granular and secure) > (the container doesnt have access to block devices, which make create pool.. etc not possible.. maybe mount /dev/disk for future ver. (--device=/dev/disk:/dev/disk))
sudo docker run -d --name "$CONTAINER_NAME" \
  --privileged \
  --device=/dev/zfs:/dev/zfs \
  --user=root \
  -v "$(pwd)/data":/opt/zfdash/data \
  -v "$(pwd)/config":/root/.config/ZfDash \
  -p 5001:5001 \
  "$IMAGE_NAME"

echo "--- ZfDash container '$CONTAINER_NAME' started. Access at http://localhost:5001 ---"
