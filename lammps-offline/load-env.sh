#!/usr/bin/env bash
# Source with a compiler lane (gnu or cray) and a target (cpu or gpu).
case "$1" in
    gnu) prgenv=${PRGENV_MODULE:-PrgEnv-gnu} ;;
    cray) prgenv=${PRGENV_MODULE:-PrgEnv-cray} ;;
    *) echo 'Use gnu or cray for the compiler.' >&2; return 2 ;;
esac
case "$2" in
    cpu|gpu) ;;
    *) echo 'Use cpu or gpu for the target.' >&2; return 2 ;;
esac

if ! type module >/dev/null 2>&1; then
    for init in "${MODULESHOME:-/usr/share/Modules}/init/bash" \
        /etc/profile.d/lmod.sh /etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash; do
        [[ -r $init ]] || continue
        # shellcheck disable=SC1090
        source "$init"
        type module >/dev/null 2>&1 && break
    done
fi
type module >/dev/null 2>&1 || { echo 'Initialize site environment modules in Bash.' >&2; return 1; }

IFS=: read -r -a loaded_modules <<< "${LOADEDMODULES:-}"
for loaded in "${loaded_modules[@]}"; do
    case "$loaded" in
        PrgEnv-*)
            if [[ $loaded != "$prgenv" && ${loaded%%/*} != "$prgenv" ]]; then
                module swap "$loaded" "$prgenv" || return 1
            fi
            ;;
        craype-accel-*)
            if [[ $2 == cpu || ( $loaded != "${ACCEL_MODULE:-craype-accel-nvidia90}" &&
                ${loaded%%/*} != "${ACCEL_MODULE:-craype-accel-nvidia90}" ) ]]; then
                module unload "$loaded" || return 1
            fi
            ;;
    esac
done
module load "$prgenv" "${CRAY_MPI_MODULE:-cray-mpich}" || return 1
read -r -a site_modules <<< "${CRAY_EXTRA_MODULES-libfabric xpmem}"
if ((${#site_modules[@]})); then
    module load "${site_modules[@]}" || return 1
fi
if [[ $2 == gpu ]]; then
    module load "${CUDA_MODULE:-cuda/12.9}" "${ACCEL_MODULE:-craype-accel-nvidia90}" || return 1
fi
if [[ -n ${CMAKE_MODULE:-} ]]; then
    module load "$CMAKE_MODULE" || return 1
fi
unset prgenv init loaded loaded_modules site_modules
