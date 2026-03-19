#!/usr/bin/env bash
set -euo pipefail

REGISTRY="rg.fr-par.scw.cloud/printemps-des-terres"
IMAGE_NAME="printemps-terres-scan-classified"
IMAGE_TAG="latest"
FULL_IMAGE="$REGISTRY/$IMAGE_NAME:$IMAGE_TAG"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

# --- Check prerequisites ---

if ! command -v docker &> /dev/null; then
    echo "Error: docker not found."
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi

echo "Registry: $REGISTRY"
echo "Image:    $FULL_IMAGE"
echo ""

# --- Parse command ---

COMMAND="${1:-help}"

case "$COMMAND" in

login)
    echo "==> Logging in to Scaleway registry..."
    if [ -z "${SCW_SECRET_KEY:-}" ]; then
        echo "Error: SCW_SECRET_KEY not set. Export it or add it to .env"
        exit 1
    fi
    docker login "$REGISTRY" -u nologin --password-stdin <<< "$SCW_SECRET_KEY"
    echo "Logged in. Next: $0 build"
    ;;

build)
    echo "==> Building image..."
    cd "$SCRIPT_DIR"

    # Copy project files and .env into build context
    cp "$REPO_ROOT/pyproject.toml" "$REPO_ROOT/uv.lock" "$ENV_FILE" .

    # Build with a temporary Dockerfile that includes .env
    cat Dockerfile - <<'EXTRA' > Dockerfile.scaleway
# Copy .env for Scaleway (secrets baked into image)
COPY .env ./
EXTRA

    docker build -f Dockerfile.scaleway -t "$IMAGE_NAME:$IMAGE_TAG" .

    # Clean up
    rm -f pyproject.toml uv.lock .env Dockerfile.scaleway

    echo ""
    echo "Build complete. Next: $0 push"
    ;;

push)
    echo "==> Pushing image to Scaleway registry..."
    docker tag "$IMAGE_NAME:$IMAGE_TAG" "$FULL_IMAGE"
    docker push "$FULL_IMAGE"

    echo ""
    echo "Push complete."
    ;;

all)
    echo "==> Full pipeline: build + push"
    echo ""
    "$0" login
    echo ""
    "$0" build
    echo ""
    "$0" push
    ;;

help|*)
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  login     Log in to Scaleway container registry"
    echo "  build     Build Docker image locally (includes .env)"
    echo "  push      Tag and push image to Scaleway registry"
    echo "  all       Login + build + push"
    echo ""
    echo "Requires SCW_SECRET_KEY env var for login."
    ;;

esac
