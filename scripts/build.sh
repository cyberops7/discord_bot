#!/usr/bin/env bash

# Exit on error
set -e

# Get repo directory
REPO_DIR="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="${REPO_DIR}/scripts"

# Import logging functions
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/logger.sh"

info "Repo directory: ${REPO_DIR}"

# Define context and Dockerfile relative to the script location
CONTEXT="${REPO_DIR}"
DOCKERFILE="${REPO_DIR}/docker/Dockerfile"
IMAGE_NAME="ghcr.io/cyberops7/discord_bot"
IMAGE_NAME_TEST="${IMAGE_NAME}_test"

# Default values
CACHE_FLAG="--no-cache"     # Default behavior is to disable caching
LOCAL_FLAG=""               # Default is no local import into the Docker daemon
PUSH_FLAG=""                # Default behavior is to build, but not push
SINGLE_PLATFORM_FLAG=""     # Default is multi-platform build
TAG="test-$(date +%Y%m%d)"  # Default image tag

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --cache)
            CACHE_FLAG="" # If --cache flag is present, remove --no-cache
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--tag <tag>] [--push] [--cache]"
            echo "Options:"
            echo "  --help, -h            Show this help message and exit."
            echo "  --cache               Enable Docker caching (default is no cache)."
            echo "  --image, -i           Specify the image name to build (default ${IMAGE_NAME}"
            echo "  --local               Export the built image from the buildx builder to the local Docker daemon."
            echo "  --push                Enable pushing the image to the registry."
            echo "  --single              Build for local architecture only (instead of multi-platform)."
            echo "  --tag, -t <tag>       Specify the image tag (default: 'test-YYYYMMDD')."
            echo "  --test                Build the version of the image for unit testing."
            exit 0
            ;;
        --image|-i)
            IMAGE_NAME="$2"
            shift 2
            ;;
        --local)
            LOCAL_FLAG="--output type=oci,dest=.tmp/oci-image.tar"
            shift
            ;;
        --push)
            PUSH_FLAG="--push"
            shift
            ;;
        --single)
            SINGLE_PLATFORM_FLAG="true"
            shift
            ;;
        --tag|-t)
            # Check if the next argument exists and isn't empty or another flag
            if [[ -z "$2" || "$2" == -* ]]; then
                error "Error: '--tag' option requires a value."
                info "Run '$0 --help' for usage information."
            exit 1
            fi
            TAG="$2"
            shift 2
            ;;
        --test)
            DOCKERFILE="${DOCKERFILE}-test"
            IMAGE_NAME=${IMAGE_NAME_TEST}
            shift
            ;;
        *)
            error "Unknown option: $1"
            warning "Run '$0 --help' for usage information."
            exit 1
            ;;
    esac
done

info "Building image: ${IMAGE_NAME} from ${DOCKERFILE}"
info "Using tag: ${TAG}"

# Determine platform architecture
if [[ -n "$SINGLE_PLATFORM_FLAG" ]]; then
    # Get local architecture and convert to Docker platform format
    LOCAL_ARCH=$(uname -m)
    case "$LOCAL_ARCH" in
        x86_64)
            PLATFORM="linux/amd64"
            ;;
        aarch64|arm64)
            PLATFORM="linux/arm64"
            ;;
        *)
            error "Unsupported architecture: $LOCAL_ARCH"
            exit 1
            ;;
    esac
    info "Building for single platform: ${PLATFORM}"
else
    PLATFORM="linux/amd64,linux/arm64"
    info "Building for multiple platforms: ${PLATFORM}"
fi


# Set up the Docker buildx builder for multiarch builds
divider
info "Setting up Docker buildx builder..."
# Check if the builder already exists
BUILDER_NAME="temp-multiarch-builder"
EXISTING_BUILDER=$(docker buildx ls | grep -w "$BUILDER_NAME" || true)
if [ -z "$EXISTING_BUILDER" ]; then
    info "Builder '${BUILDER_NAME}' does not exist. Creating it now..."
    docker buildx create --name "${BUILDER_NAME}" --use
    success "Builder '${BUILDER_NAME}' has been created and set as the current builder."
else
    info "Builder '${BUILDER_NAME}' already exists. Using it now..."
    docker buildx use "$BUILDER_NAME"
fi

info "Bootstrapping builder..."
docker buildx inspect --bootstrap
success "Builder bootstrapped successfully."

# Build the docker build command
divider
info "Constructing build command..."

CMD="docker buildx build \
    --tag ${IMAGE_NAME}:${TAG} \
    --platform ${PLATFORM}"
# Include --no-cache flag if set
if [[ -n "$CACHE_FLAG" ]]; then
    CMD+=" $CACHE_FLAG"
    info "Caching disabled."
else
    info "Caching enabled."
fi

# Add oci output if it's not empty
if [[ -n "$LOCAL_FLAG" ]]; then
    CMD+=" $LOCAL_FLAG"
    info "Image will be exported to the local Docker daemon."
    # Make sure the .tmp/ directory exists
    TMP_DIR="${REPO_DIR}/.tmp"
    if [[ ! -d "$TMP_DIR" ]]; then
        mkdir -p "$TMP_DIR"
        info "Created directory: $TMP_DIR"
    fi

fi

# Add PUSH_FLAG if it's not empty
if [[ -n "$PUSH_FLAG" ]]; then
    CMD+=" $PUSH_FLAG"
    info "Image will be pushed to the registry"
fi

# Specify Dockerfile and context at the end
CMD+=" -f ${DOCKERFILE} ${CONTEXT}"

# Print the final command (for debugging)
info "Final build command:"
echo -e "${CYAN}${CMD}${RESET}"

# Execute the constructed command
divider
info "Building the image..."
eval "$CMD"
success "Image built successfully with tag: ${TAG}"

# Output the path to the tarball if --local was passed
if [[ -n "$LOCAL_FLAG" ]]; then
    divider
    info "Converting the OCI image to Docker format..."

    # Determine the architecture for skopeo based on platform
    if [[ "$PLATFORM" == *"arm64"* ]]; then
        SKOPEO_ARCH="arm64"
    else
        SKOPEO_ARCH="amd64"
    fi

    skopeo copy --override-os linux --override-arch \
        ${SKOPEO_ARCH} oci-archive:"${CONTEXT}/.tmp/oci-image.tar" \
        docker-archive:"${CONTEXT}/.tmp/docker-compatible-image.tar":"${IMAGE_NAME}:${TAG}"
    success "OCI image converted to Docker archive."

    info "Importing the image into the Docker daemon"
    docker load < "${CONTEXT}/.tmp/docker-compatible-image.tar"
    success "Image imported into Docker daemon. Image now available locally."
    docker image ls "${IMAGE_NAME}"

    info "Performing clean-up of temporary files..."
    rm "${CONTEXT}/.tmp/oci-image.tar" \
        "${CONTEXT}/.tmp/docker-compatible-image.tar" \
        2>/dev/null || true
    success "Temporary files cleaned."
fi

# Clean up after ourselves
divider
info "Removing builder '${BUILDER_NAME}'..."
docker buildx rm "${BUILDER_NAME}"
success "Builder '${BUILDER_NAME}' removed successfully."

info "Cleaning up unused dangling images..."
docker image prune -f
success "Clean-up complete. Dangling images removed."
divider
success "Build process completed!"
