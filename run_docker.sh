#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# Set the Docker Hub repository where the image is published.
# Replace 'your-dockerhub-username' with your actual Docker Hub username.
DOCKERHUB_REPO="ad4mts/zfdash"
IMAGE_NAME="${DOCKERHUB_REPO}:latest"
CONTAINER_NAME="zfdash"

echo "--- Pulling latest Docker image: $IMAGE_NAME ---"
sudo docker pull "$IMAGE_NAME"

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
  -v zfdash_data:/opt/zfdash/data \
  -v zfdash_config:/root/.config/ZfDash \
  -p 5001:5001 \
  --restart unless-stopped \
  "$IMAGE_NAME"

echo "--- ZfDash container '$CONTAINER_NAME' started. Access at http://localhost:5001 ---"
