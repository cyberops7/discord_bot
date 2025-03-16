#!/usr/bin/env bash

# Exit on error
set -e

# Import logging functions
REPO_DIR="$(git rev-parse --show-toplevel)"
source "${REPO_DIR}/scripts/logger.sh"

# Default tag value
CONTAINER_NAME=bot-test
IMAGE="ghcr.io/cyberops7/discord_bot"
TAG="test-$(date +%Y%m%d)" # Initialize TAG with default

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -h|--help) # Provide help information
            echo "Usage: $0 [--tag tag-name]"
            echo "  --tag tag-name    Specify a custom tag for the Docker image"
            exit 0 ;;
        --image|-i)
            IMAGE="$2"
            shift 2
            ;;
        --tag|-t) # Check for --tag option
            TAG="$2"
            shift 2 ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1 ;;
    esac
done

info "Using tag: ${TAG}"

info "Starting container '${CONTAINER_NAME}': ${IMAGE}:${TAG}"
docker run --name "${CONTAINER_NAME}" \
    --env-file .env \
    -p 8080:8080 \
    -dit \
    "${IMAGE}":"${TAG}"

if docker ps --filter "name=${CONTAINER_NAME}" --filter "status=running" --quiet > /dev/null; then
    success "The container '${CONTAINER_NAME}' is up and running."
    docker ps
else
    error "The container '${CONTAINER_NAME}' failed to start or is not running."
    warning "Try running \`docker logs ${CONTAINER_NAME}\` for clues."
    exit 1
fi
