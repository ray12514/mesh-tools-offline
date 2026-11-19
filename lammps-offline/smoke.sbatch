#!/usr/bin/env bash
#SBATCH --job-name=lammps-smoke
#SBATCH --time=00:05:00
#SBATCH --nodes=1
set -eo pipefail
if (($# < 3)); then
    echo 'Usage: sbatch [allocation flags] smoke.sbatch gnu|cray cpu|gpu /absolute/path/to/lmp [srun flags ...]' >&2
    exit 2
fi
root=${LAMMPS_REPO:-${SLURM_SUBMIT_DIR:?Submit from the LAMMPS installer checkout or set LAMMPS_REPO.}}
lane=$1 target=$2 binary=$3
shift 3
# shellcheck source=load-env.sh
source "$root/load-env.sh" "$lane" "$target"
exec bash "$root/smoke.sh" "$target" "$binary" --ntasks="${SLURM_NTASKS:-1}" "$@"
