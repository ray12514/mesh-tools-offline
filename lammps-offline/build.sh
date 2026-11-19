#!/usr/bin/env bash
# The installer calls this in a child shell so module changes stay local.
set -eo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
lane=$1 target=$2 src=$3 work=$4 prefix=$5 stage=$6 packages=$7 jobs=$8 mode=$9 machine=${10}
shift 10
# shellcheck source=load-env.sh
source "$root/load-env.sh" "$lane" "$target" "$work/runtime-modules.txt"
module list

if [[ $mode == offline ]]; then
    # Block the HTTP/FTP fallback used by upstream CMake/libcurl and limit Git to local sources.
    export http_proxy=http://127.0.0.1:1 https_proxy=http://127.0.0.1:1
    export ftp_proxy=http://127.0.0.1:1 all_proxy=http://127.0.0.1:1 no_proxy=
    export HTTP_PROXY=$http_proxy HTTPS_PROXY=$https_proxy FTP_PROXY=$ftp_proxy ALL_PROXY=$all_proxy NO_PROXY=
    export GIT_ALLOW_PROTOCOL=file
fi

cc_path=$(type -P cc) || { echo 'Cray cc wrapper missing from PATH.' >&2; exit 1; }
cxx_path=$(type -P CC) || { echo 'Cray CC wrapper missing from PATH.' >&2; exit 1; }
"$cxx_path" --version
# Ask CMake FindMPI to use the wrappers already selected as C and C++ compilers.
flags=(
    "-DCMAKE_C_COMPILER:FILEPATH=$cc_path"
    "-DCMAKE_CXX_COMPILER:FILEPATH=$cxx_path"
    "-DMPI_CXX_COMPILER:FILEPATH=$cxx_path"
    "-DBUILD_MPI:BOOL=ON"
    "-DLAMMPS_MACHINE:STRING=$machine"
    "-DFFT:STRING=KISS"
    "-DCMAKE_BUILD_TYPE:STRING=Release"
    "-DCMAKE_INSTALL_PREFIX:PATH=$prefix"
    "-DCMAKE_INSTALL_RPATH_USE_LINK_PATH:BOOL=ON"
    "-DCMAKE_PROJECT_lammps_INCLUDE:FILEPATH=$root/cmake/h200.cmake"
    "-DLAMMPS_CRAY_LANE:STRING=$lane"
    "-DLAMMPS_H200_GPU:BOOL=OFF"
)
extra_presets=()
case "$target" in
    cpu)
        flags+=("-DPKG_GPU:BOOL=OFF" "-DPKG_KOKKOS:BOOL=OFF")
        ;;
    gpu)
        nvcc=$(type -P nvcc) || { echo 'nvcc missing. Check CUDA_MODULE.' >&2; exit 1; }
        host_cxx=$(type -P "${CUDA_HOST_CXX:-g++}") || { echo 'Set CUDA_HOST_CXX to CUDA-compatible g++.' >&2; exit 1; }
        export NVCC_WRAPPER_DEFAULT_COMPILER="$host_cxx"
        "$nvcc" --version
        "$host_cxx" --version
        extra_presets=(-C "$src/cmake/presets/kokkos-cuda-nowrapper.cmake")
        flags+=(
            "-DLAMMPS_H200_GPU:BOOL=ON"
            "-DPKG_KOKKOS:BOOL=ON"
            "-DBUILD_OMP:BOOL=OFF"
            "-DEXTERNAL_KOKKOS:BOOL=OFF"
            "-DDOWNLOAD_KOKKOS:BOOL=OFF"
            "-DFFT_KOKKOS:STRING=CUFFT"
            "-DKokkos_ENABLE_CUDA:BOOL=ON"
            "-DKokkos_ENABLE_SERIAL:BOOL=ON"
            "-DKokkos_ENABLE_OPENMP:BOOL=OFF"
            "-DKokkos_ENABLE_HIP:BOOL=OFF"
            "-DKokkos_ENABLE_SYCL:BOOL=OFF"
            "-DKokkos_ENABLE_CUDA_RELOCATABLE_DEVICE_CODE:BOOL=OFF"
            "-DKokkos_ENABLE_COMPILE_AS_CMAKE_LANGUAGE:BOOL=OFF"
            "-DKokkos_ARCH_HOPPER90:BOOL=ON"
            "-DKokkos_ARCH_NATIVE:BOOL=${KOKKOS_ARCH_NATIVE:-ON}"
            "-DKokkos_COMPILE_LAUNCHER:FILEPATH=$src/lib/kokkos/bin/kokkos_launch_compiler"
            "-DKokkos_NVCC_WRAPPER:FILEPATH=$src/lib/kokkos/bin/nvcc_wrapper"
            "-DCUDAToolkit_ROOT:PATH=$(dirname -- "$(dirname -- "$nvcc")")"
        )
        ;;
esac

# LAMMPS/Kokkos native compiler detection on CrayClang needs CMake 3.28+.
cmake -S "$src/cmake" -B "$work/obj" -G 'Unix Makefiles' \
    "${extra_presets[@]}" -C "$packages" "${flags[@]}" "$@"
cmake --build "$work/obj" --parallel "$jobs"
DESTDIR="$stage" cmake --install "$work/obj"
