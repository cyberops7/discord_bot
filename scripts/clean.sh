#!/usr/bin/env bash

# Import logging functions
REPO_DIR="$(git rev-parse --show-toplevel)"
source "${REPO_DIR}/scripts/logger.sh"

# Define variables
BUILD_DIR=.tmp/
BUILDER_NAME="temp-multiarch-builder"
CONTAINER_NAME=bot-test
TEST_NAME=unit-test-run

# Remove the container if it is running
if [ "$(docker ps --filter "name=${CONTAINER_NAME}" --filter "status=running" -q)" ]; then
    info "Container '${CONTAINER_NAME}' is running. Stopping and removing it..."
    docker stop "${CONTAINER_NAME}"
    docker rm "${CONTAINER_NAME}"
    success "Stopped and removed '${CONTAINER_NAME}'"
else
    info "No running container named '${CONTAINER_NAME}' exists."

    # Remove the container if it exists, but is stopped
    if [ "$(docker ps -a --filter "name=${CONTAINER_NAME}" --filter "status=exited" -q)" ]; then
        info "Container '${CONTAINER_NAME}' exists, but is stopped. Removing it..."
        docker rm "${CONTAINER_NAME}"
        success "Removed '${CONTAINER_NAME}'"
    else
        info "No stopped container named '${CONTAINER_NAME}' exists."
    fi
fi

# Remove the test container if it is running
if [ "$(docker ps --filter "name=${TEST_NAME}" --filter "status=running" -q)" ]; then
    info "Container '${TEST_NAME}' is running. Stopping and removing it..."
    docker stop "${TEST_NAME}"
    docker rm "${TEST_NAME}"
    success "Stopped and removed '${TEST_NAME}'"
else
    info "No running container named '${TEST_NAME}' exists."

    # Remove the container if it exists, but is stopped
    if [ "$(docker ps -a --filter "name=${TEST_NAME}" --filter "status=exited" -q)" ]; then
        info "Container '${TEST_NAME}' exists, but is stopped. Removing it..."
        docker rm "${TEST_NAME}"
        success "Removed '${TEST_NAME}'"
    else
        info "No stopped container named '${TEST_NAME}' exists."
    fi
fi

# Clean up the buildx builder, if it exists
if docker buildx ls | grep -qw "${BUILDER_NAME}"; then
    info "Builder '${BUILDER_NAME}' exists. Removing it..."
    docker buildx rm "${BUILDER_NAME}"
    success "Builder '${BUILDER_NAME}' removed."
else
    info "Builder '${BUILDER_NAME}' does not exist."
fi

# Clean up build artifacts
info "Cleaning build artifacts."
rm "${BUILD_DIR}/oci-image.tar" \
    "${BUILD_DIR}/docker-compatible-image.tar" \
    2>/dev/null || true
success "Build artifacts cleaned."
