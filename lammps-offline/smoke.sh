#!/usr/bin/env bash
# Invoke inside an allocation after sourcing load-env.sh for this binary.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if (($# < 2)) || [[ $1 != cpu && $1 != gpu ]]; then
    echo 'Usage: smoke.sh cpu|gpu /absolute/path/to/lmp [srun flags ...]' >&2
    exit 2
fi
target=$1 binary=$2
shift 2
if [[ ! -x $binary ]]; then
    echo "LAMMPS executable unavailable: $binary" >&2
    exit 1
fi

output=$(mktemp "${TMPDIR:-/tmp}/lammps-smoke.XXXXXXXX")
trap 'rm -f -- "$output"' EXIT
linkage=$(ldd "$binary")
printf '%s\n' "$linkage"
if [[ $linkage == *'not found'* ]] || ! grep -q 'libmpi_cray' <<< "$linkage"; then
    echo 'Expected resolved Cray MPICH runtime libraries.' >&2
    exit 1
fi

flags=(-var lj_style lj/cut) ranks=2
if [[ $target == gpu ]]; then
    ranks=1
    mpi_gpu=${MPICH_GPU_SUPPORT_ENABLED:-0}
    case "$mpi_gpu" in
        0) gpu_aware=off ;;
        1) gpu_aware=on ;;
        *) echo 'Set MPICH_GPU_SUPPORT_ENABLED to 0 or 1.' >&2; exit 2 ;;
    esac
    grep -q 'libmpi_gtl_cuda' <<< "$linkage" || { echo 'Cray CUDA GTL missing.' >&2; exit 1; }
    export MPICH_GPU_SUPPORT_ENABLED=$mpi_gpu
    flags=(-k on g "${GPUS_PER_NODE:-1}" -sf kk -pk kokkos gpu/aware "$gpu_aware"
           -var lj_style lj/cut/kk)
else
    export MPICH_GPU_SUPPORT_ENABLED=0
fi
srun --ntasks="$ranks" "$@" "$binary" "${flags[@]}" -log none -in "$root/in.smoke" | tee "$output"
if [[ $(grep -c '^Loop time of ' "$output") != 1 ]]; then
    echo 'Expected one completed LAMMPS run. Check rank startup and the Slurm MPI plugin.' >&2
    exit 1
fi
if [[ $target == gpu ]]; then
    grep -q 'GPU(s) per node' "$output" || { echo 'LAMMPS did not report Kokkos GPU execution.' >&2; exit 1; }
fi
