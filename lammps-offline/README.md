# LAMMPS on Cray with CMake

Build LAMMPS with `cc` and `CC`, Cray MPICH, and a separate install prefix for each compiler and target.

| Target | Default executable | FFT and acceleration |
| --- | --- | --- |
| Generic CPU | `bin/lmp` | MPI with KISS FFT (Kokkos disabled) |
| NVIDIA H200 | `bin/lmp_kokkos_cuda_cray` | KISS FFT for regular styles, cuFFT for Kokkos, and bundled Kokkos targeting `HOPPER90` |

Both targets enable `COLLOID`, `KSPACE`, `MANYBODY`, `MOLECULE`, `PHONON`, `RIGID`, `SHOCK`, and `MISC`. Pass `--machine NAME` to set the LAMMPS binary suffix for an existing site naming convention.

The setup resolves the latest stable release when connected, or uses a pinned archive that you stage ahead of time. On November 19, 2026, the latest stable release was `stable_30Sep2026_update1`. [LAMMPS release](https://github.com/lammps/lammps/releases/tag/stable_30Sep2026_update1)

## Set the site paths and modules

Use Bash on a target Linux build node with Cray PE, CMake 3.28 or newer, GNU Make, and Python 3.12 or a patched Python that provides `tarfile.data_filter`. Source downloads use `curl`. Keep the build directory on scratch for both the home and shared installs. Paths for the checkout, prefix and build directory should have no spaces or shell punctuation.

```bash
export BUILD_ROOT=/path/to/scratch/lammps
export CUDA_MODULE=cuda/12.9
# export CMAKE_MODULE=cmake/<site-version>
```

Check the CUDA module label on the target. `load-env.sh` selects `PrgEnv-gnu` or `PrgEnv-cray`, loads `cray-mpich`, and loads CUDA and `craype-accel-nvidia90` for GPU builds. It defaults to `libfabric xpmem` for the site module names. Use `CRAY_EXTRA_MODULES=''` if the site already supplies those dependencies. Set `PRGENV_MODULE`, `CRAY_MPI_MODULE` or `ACCEL_MODULE` to pin specific module names or versions for a given build. [HPE Cray MPI](https://cpe.ext.hpe.com/docs/25.09/mpt/mpich/intro_mpi.html)

CPU C++ compilation and linkage use the selected Cray wrapper and its compiler. GPU builds use the upstream Kokkos launcher to compile CUDA-capable C++ with `nvcc` and a compatible `g++`. The final link goes through the selected Cray `CC` wrapper so it can add the Cray CUDA GTL. For a GPU build with `PrgEnv-cray`, load a compatible GNU host compiler if needed and set `CUDA_HOST_CXX` to its `g++`. Match that compiler's C++ runtime to the site CCE stack. The GPU build uses the Kokkos Serial host backend with OpenMP off. It defaults to `Kokkos_ARCH_NATIVE=ON`, so build on a node with the same CPU architecture as the H200 nodes, or set `KOKKOS_ARCH_NATIVE=OFF` when building on a different node type. [LAMMPS Kokkos build options](https://docs.lammps.org/Build_extras.html#kokkos) · [CUDA host compiler support](https://docs.nvidia.com/cuda/archive/12.9.2/cuda-installation-guide-linux/index.html#host-compiler-support-policy)

The GPU build passes the loaded Cray MPICH include directory to `nvcc` because the Kokkos launcher bypasses `CC` when compiling CUDA. Look for `Cray MPICH headers for nvcc` in `build.log`. On sites that expose the path through `MPICH_DIR`, the header is at `$MPICH_DIR/include/mpi.h`. [HPCMP CUDA and MPI build guidance](https://centers.hpc.mil/users/docs/advancedTopics/Build_CUDA_src_with_MPI_when_mpih_not_found.html)

## Stage the offline source bundle

From a connected machine, prepare the transfer bundle. Use `latest` or a specific tag. For an archive already downloaded, pass its tag and `--source /path/to/source.tar.gz`. Add `--sha256` with the upstream digest when available. The bundle includes a manifest with the resolved tag and archive hash.

```bash
python3 prepare.py stable_30Sep2026_update1
```

Transfer `dist/lammps-offline.tar.gz` and `dist/lammps-offline.tar.gz.sha256` together. On the build node, verify the outer checksum and extract into a fresh directory. The installer verifies the inner archive before using it.

```bash
sha256sum -c lammps-offline.tar.gz.sha256 && tar -xzf lammps-offline.tar.gz
cd lammps-offline
```

If the tarball is already on the build node, you can also use `install.py --offline --source /path/to/source.tar.gz --release TAG` with the same compiler, target and prefix flags. Keep the same source archive for the home and shared builds.

## Rehearse the build in your home directory

Set `tag` to the release you staged. If you prepared `latest`, use the resolved tag in `sources/source.json`. Adjust the [package settings](#select-packages) and site modules first, then build both GNU variants. Set `compiler=cray` and repeat if you plan to deploy the Cray variants.

```bash
tag=stable_30Sep2026_update1
compiler=gnu
test_root="$HOME/lammps-test/$tag"
smoke_root="$test_root"

for target in cpu gpu; do
  python3 install.py --offline --release "$tag" \
    --compiler "$compiler" --target "$target" \
    --prefix "$test_root/$compiler-$target" \
    --module-root "$test_root/modulefiles" \
    --build-root "$BUILD_ROOT" --jobs 8 || break
done
```

Each build keeps a `build.log` and `obj/CMakeCache.txt` in the scratch directory printed at startup. The installed `build-info.json` records the source and package-file hashes. If you change the configuration and rerun, choose a fresh `test_root` such as `"$HOME/lammps-test/$tag-retry1"`. The installer requires a new prefix for each variant or rebuild.

## Load the installed LAMMPS module

The installer writes a Tcl modulefile under `<prefix>/modulefiles/lammps/<release>-<compiler>-<target>`. `--module-root` publishes a link under a directory you can add to `MODULEPATH`, such as the shared application module tree. Use `--module-version` if the site uses a different version name. The installer prints the module name and prerequisites, and records both in `build-info.json`.

Choose the programming environment yourself using your site's normal master module or module commands. A GNU build requires the matching `PrgEnv-gnu` and Cray MPICH. A Cray build requires the matching `PrgEnv-cray` and Cray MPICH. GPU builds also require the matching CUDA module. The installer records the versions exposed by the module system at build time, including loaded CPE and GCC or CCE modules. An application module that finds a missing prerequisite stops and lists what the user needs to load. With a matching environment it adds the installation's `bin` directory to `PATH`. [Lmod Tcl modulefiles](https://lmod.readthedocs.io/en/latest/051_tcl_modulefiles.html) · [Environment Modules modulefiles](https://modules.readthedocs.io/en/latest/modulefile.html)

For example, from a login shell with `PrgEnv-cray` loaded, switch to the GNU environment if that matches the build. Use the exact versions reported by the installer if the site defaults differ. Some sites load CUDA through `craype-accel-nvidia90`.

```bash
module swap PrgEnv-cray PrgEnv-gnu
module list
# Load any remaining required modules reported by the installer.
module use "$test_root/modulefiles"
module load "lammps/$tag-gnu-gpu"
command -v lmp_kokkos_cuda_cray
```

In a fresh session, set `tag` and `test_root` to the values used during the home build. For shared installs, use the site's application module directory. When switching programming environments, unload the application module and load the variant built for the new environment.

CMake adds eligible linker search paths to the installed runtime search path. Cray MPICH and CUDA can also load libraries through dependencies of the binary, and the runtime environment can affect which copies the loader selects. Keep the module checks and verify actual linkage through the Slurm smoke tests. [CMake install RPATH](https://cmake.org/cmake/help/latest/variable/CMAKE_INSTALL_RPATH_USE_LINK_PATH.html) · [Linux dynamic linker](https://man7.org/linux/man-pages/man8/ld.so.8.html)

## Run a Slurm smoke test

From the checkout or extracted bundle, submit `smoke.sbatch` against the home binaries. The job loads the runtime modules for the selected build, checks Cray MPICH and GPU GTL linkage, then runs ten steps of a small Lennard-Jones case. `sbatch --wait` reports the job's exit status. [Slurm sbatch](https://slurm.schedmd.com/sbatch.html) · [LAMMPS Kokkos runtime options](https://docs.lammps.org/Speed_kokkos.html)

```bash
account=YOUR_PROJECT
cpu_partition=YOUR_CPU_PARTITION
gpu_partition=YOUR_H200_PARTITION
gpu_gres=gpu:YOUR_H200_GRES_TYPE:1

sbatch --wait -A "$account" -p "$cpu_partition" -n 2 smoke.sbatch \
  "$compiler" cpu "$smoke_root/$compiler-cpu/bin/lmp"

MPICH_GPU_SUPPORT_ENABLED=0 GPUS_PER_NODE=1 \
  sbatch --wait -A "$account" -p "$gpu_partition" -n 1 --gres="$gpu_gres" smoke.sbatch \
  "$compiler" gpu "$smoke_root/$compiler-gpu/bin/lmp_kokkos_cuda_cray"
```

Both jobs should exit zero. Check `slurm-<jobid>.out` for one completed run (`Loop time of`) and, for the GPU job, Kokkos reporting its GPUs. For a two-GPU check on one node, submit the GPU example with `MPICH_GPU_SUPPORT_ENABLED=1 GPUS_PER_NODE=2`, `-n 2`, and a two-GPU GRES request. Pass `--gpu-bind=none` after the binary so both ranks can see both GPUs and Kokkos can map the local ranks to devices. Pass `--mpi=PLUGIN` in the same position if your site requires a specific Slurm MPI plugin. An existing interactive allocation can use `source ./load-env.sh gnu gpu` and `./smoke.sh gpu /path/to/lmp_kokkos_cuda_cray`.

## Build and install in the shared software tree

After the home tests pass, rebuild the validated variants using the same source bundle, compiler, modules, and package configuration. Keep any `--packages` argument that you used for the rehearsal. Set `APP_ROOT` to the site's writable LAMMPS software directory. CMake configures each build for its final install prefix, and the installer stages the files before publishing them there.

```bash
APP_ROOT=/path/to/existing/lammps
APP_MODULE_ROOT=/path/to/site/modulefiles
shared_root="$APP_ROOT/$tag"

for target in cpu gpu; do
  python3 install.py --offline --release "$tag" \
    --compiler "$compiler" --target "$target" \
    --prefix "$shared_root/$compiler-$target" \
    --module-root "$APP_MODULE_ROOT" \
    --build-root "$BUILD_ROOT" --jobs 8 || break
done
```

Set `smoke_root="$shared_root"` and rerun the Slurm checks against the shared binaries. Compare `build-info.json` for each home and shared variant to confirm the source archive, package configuration, and required modules match.

## Build online

The online installer downloads the latest stable upstream source asset and verifies its upstream SHA-256. For a home trial that you will reproduce later, use an explicit release tag.

```bash
python3 install.py --online --release stable_30Sep2026_update1 --compiler gnu --target cpu \
  --prefix "$HOME/lammps-test/stable_30Sep2026_update1/gnu-cpu" \
  --build-root "$BUILD_ROOT" --jobs 8
```

## Select packages

Edit `packages.cmake`, or make separate copies for CPU and GPU and pass `--packages /path/to/file.cmake` to `install.py`. Add or change entries with the standard LAMMPS CMake package names.

```cmake
set(PKG_REAXFF ON CACHE BOOL "")
```

You can carry a customized default in the transfer bundle with `prepare.py --packages /path/to/file.cmake`. For offline builds, point packages that need external libraries to compatible, locally installed dependencies using `CMAKE_PREFIX_PATH` or their package-specific variables. For example, ML-PACE can use an installed `pace` or sources staged via `LOCAL_ML-PACE`. Stage any additional potential files required by your inputs. The offline installer disables upstream `DOWNLOAD_*` defaults and FetchContent retrieval. [LAMMPS package selection](https://docs.lammps.org/Build_package.html) · [Package dependencies](https://docs.lammps.org/Build_extras.html)
