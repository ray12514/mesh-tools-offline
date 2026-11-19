#!/usr/bin/env bash
# With Kokkos CUDA RDC disabled, the final link is a normal host link.
set -eu
driver=$1
shift
args=()
for arg in "$@"; do
    # Device architecture was consumed when nvcc compiled the objects.
    [[ $arg == -arch=sm_90 ]] || args+=("$arg")
done
exec "$driver" -dynamic --no-as-needed "${args[@]}"
