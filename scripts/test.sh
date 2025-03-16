#!/usr/bin/env bash

REPO_DIR="$(git rev-parse --show-toplevel)"

source "${REPO_DIR}/scripts/logger.sh"

# Default values
IMAGE_NAME="ghcr.io/cyberops7/discord_bot_test"  # Docker image name for tests
TAG="test"                                       # Default tag for the image
USE_DOCKER=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --docker|-d)
            USE_DOCKER=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--docker | -d]"
            echo "Options:"
            echo "  --docker, -d                Run tests inside the unit-test Docker image."
            echo "  --image <image_name>, -i    Specify a custom Docker image name for testing."
            echo "  --tag <tag>, -t             Specify a custom tag for the Docker image."

            exit 0
            ;;
        --image|-i)
            if [[ -n "$2" && "$2" != -* ]]; then
                IMAGE_NAME="$2"
                shift 2
            else
                error "The --image flag requires a value."
                exit 1
            fi
            ;;
        --tag|-t)
            if [[ -n "$2" && "$2" != -* ]]; then
                TAG="$2"
                shift 2
            else
                error "The --tag flag requires a value."
                exit 1
            fi
            ;;
        *)
            error "Unknown option: $1"
            warning "Run '$0 --help' for usage information."
            exit 1
            ;;
    esac
done

if $USE_DOCKER; then
    info "Running tests using Docker image: ${IMAGE_NAME}:${TAG}"
    # Run tests inside the Docker container
    docker run --rm -t \
        --name unit-test-run \
        -v "${REPO_DIR}/conf:/app/conf" \
        -v "${REPO_DIR}/lib:/app/lib" \
        -v "${REPO_DIR}/tests:/app/tests" \
        -v "${REPO_DIR}/main.py:/app/main.py" \
        -v "${REPO_DIR}/pyproject.toml:/app/pyproject.toml" \
        -v "${REPO_DIR}/uv.lock:/app/uv.lock" \
        "${IMAGE_NAME}:${TAG}"
else
    info "Running tests directly (local environment)..."
    # Run tests directly in the local environment using uv
    which python3
    info "Running pytest..."
    uv run pytest
fi
