# LAMMPS on Cray with CMake

Build LAMMPS with `cc` and `CC`, Cray MPICH, and a separate install prefix for each compiler and target.

| Target | Default executable | FFT and acceleration |
| --- | --- | --- |
| Generic CPU | `bin/lmp` | KISS FFT, MPI, and Kokkos disabled |
| NVIDIA H200 | `bin/lmp_kokkos_cuda_cray` | KISS FFT for regular styles, cuFFT for Kokkos, and bundled Kokkos targeting `HOPPER90` |

Both targets enable `COLLOID`, `KSPACE`, `MANYBODY`, `MOLECULE`, `PHONON`, `RIGID`, `SHOCK`, and `MISC`. Pass `--machine NAME` to set the LAMMPS binary suffix for an existing site naming convention.

The setup resolves the latest stable release when connected, or uses a pinned archive that you stage ahead of time. On November 19, 2026, the latest stable release was `stable_30Sep2026_update1`. [LAMMPS release](https://github.com/lammps/lammps/releases/tag/stable_30Sep2026_update1)

## Set the site paths and modules

Use Bash on a target Linux build node with Cray PE, CMake 3.28 or newer, GNU Make, and Python 3.12 or a patched Python that provides `tarfile.data_filter`. Source downloads use `curl`. Use scratch for the build directory and a new variant directory under your existing LAMMPS software tree. Paths for the checkout, prefix and build directory should have no spaces or shell punctuation.

```bash
export APP_ROOT=/path/to/existing/lammps
export BUILD_ROOT=/path/to/scratch/lammps
export CUDA_MODULE=cuda/12.9
# export CMAKE_MODULE=cmake/<site-version>
```

Check the CUDA module label on the target. `load-env.sh` selects `PrgEnv-gnu` or `PrgEnv-cray`, loads `cray-mpich`, and loads CUDA and `craype-accel-nvidia90` for GPU builds. It defaults to `libfabric xpmem` for the site module names. Use `CRAY_EXTRA_MODULES=''` if the site already supplies those dependencies. Set `PRGENV_MODULE`, `CRAY_MPI_MODULE` or `ACCEL_MODULE` to pin specific module names or versions for a given build. [HPE Cray MPI](https://cpe.ext.hpe.com/docs/25.09/mpt/mpich/intro_mpi.html)

CPU C++ compilation and linkage use the selected Cray wrapper and its compiler. GPU builds use the upstream Kokkos launcher to compile CUDA-capable C++ with `nvcc` and a compatible `g++`. The final link goes through the selected Cray `CC` wrapper so it can add the Cray CUDA GTL. For a GPU build with `PrgEnv-cray`, load a compatible GNU host compiler if needed and set `CUDA_HOST_CXX` to its `g++`. Match that compiler's C++ runtime to the site CCE stack. The GPU build uses the Kokkos Serial host backend with OpenMP off. It defaults to `Kokkos_ARCH_NATIVE=ON`, so build on a node with the same CPU architecture as the H200 nodes, or set `KOKKOS_ARCH_NATIVE=OFF` when building on a different node type. [LAMMPS Kokkos build options](https://docs.lammps.org/Build_extras.html#kokkos) · [CUDA host compiler support](https://docs.nvidia.com/cuda/archive/12.9.2/cuda-installation-guide-linux/index.html#host-compiler-support-policy)

## Build online

The online installer downloads the latest stable upstream source asset and verifies its upstream SHA-256. Use `--release stable_30Sep2026_update1` to pin that release explicitly. The installer loads `packages.cmake` and applies the selected CPU or GPU build settings.

```bash
python3 install.py --online --release latest --compiler gnu --target cpu \
  --prefix "$APP_ROOT/gnu-cpu" --build-root "$BUILD_ROOT" --jobs 8
```

## Stage once and build offline

From a connected machine, prepare the transfer bundle. Use `latest` or a specific tag. For an archive already downloaded, pass its tag and `--source /path/to/source.tar.gz`. Add `--sha256` with the upstream digest when available. The bundle includes a manifest with the resolved tag and archive hash.

```bash
python3 prepare.py stable_30Sep2026_update1
```

Transfer `dist/lammps-offline.tar.gz` and `dist/lammps-offline.tar.gz.sha256` together. On the build node, verify the outer checksum and extract into a fresh directory. The installer verifies the inner archive before using it.

```bash
sha256sum -c lammps-offline.tar.gz.sha256 && tar -xzf lammps-offline.tar.gz
cd lammps-offline

tag=stable_30Sep2026_update1
for compiler in gnu cray; do
  for target in cpu gpu; do
    python3 install.py --offline --release "$tag" \
      --compiler "$compiler" --target "$target" \
      --prefix "$APP_ROOT/$tag/$compiler-$target" \
      --build-root "$BUILD_ROOT" --jobs 8 || break 2
  done
done
```

If the tarball is already on the build node, you can also use `install.py --offline --source /path/to/source.tar.gz --release "$tag"` with the same compiler, target and prefix flags. Each build uses a fresh work directory. Its `build.log` records the module list and the CMake output. Look in `obj/CMakeCache.txt` for the resolved configuration. The installed `build-info.json` records the source and package-file hashes. A completed install publishes to the chosen prefix in one rename. Use a fresh prefix for each variant or rebuild.

## Select packages

Edit `packages.cmake`, or make separate copies for CPU and GPU and pass `--packages /path/to/file.cmake` to `install.py`. Add or change entries with the standard LAMMPS CMake package names.

```cmake
set(PKG_REAXFF ON CACHE BOOL "")
```

You can carry a customized default in the transfer bundle with `prepare.py --packages /path/to/file.cmake`. For offline builds, point packages that need external libraries to compatible, locally installed dependencies using `CMAKE_PREFIX_PATH` or their package-specific variables. For example, ML-PACE can use an installed `pace` or sources staged via `LOCAL_ML-PACE`. Stage any additional potential files required by your inputs. The offline installer disables upstream `DOWNLOAD_*` defaults and FetchContent retrieval. [LAMMPS package selection](https://docs.lammps.org/Build_package.html) · [Package dependencies](https://docs.lammps.org/Build_extras.html)

## Run a Slurm smoke test

From the checkout or extracted bundle, submit `smoke.sbatch` with your site account, partitions and GPU GRES name. The script loads the runtime modules for the selected build, checks Cray MPICH and GPU GTL linkage, then runs ten steps of a small Lennard-Jones case. The commands use the prefixes from the offline example. [Slurm sbatch](https://slurm.schedmd.com/sbatch.html) · [LAMMPS Kokkos runtime options](https://docs.lammps.org/Speed_kokkos.html)

```bash
account=YOUR_PROJECT
cpu_partition=YOUR_CPU_PARTITION
gpu_partition=YOUR_H200_PARTITION
gpu_gres=gpu:YOUR_H200_GRES_TYPE:1

sbatch -A "$account" -p "$cpu_partition" -n 2 smoke.sbatch \
  gnu cpu "$APP_ROOT/$tag/gnu-cpu/bin/lmp"

sbatch -A "$account" -p "$gpu_partition" -n 1 --gres="$gpu_gres" smoke.sbatch \
  gnu gpu "$APP_ROOT/$tag/gnu-gpu/bin/lmp_kokkos_cuda_cray"
```

Repeat with `cray` and the corresponding binary paths. For a two-GPU check on one node, submit the GPU example with `MPICH_GPU_SUPPORT_ENABLED=1 GPUS_PER_NODE=2`, `-n 2`, and a two-GPU GRES request. Pass `--gpu-bind=none` after the binary so both ranks can see both GPUs and Kokkos can map the local ranks to devices. Pass `--mpi=PLUGIN` in the same position if your site requires a specific Slurm MPI plugin. An existing interactive allocation can use `source ./load-env.sh gnu gpu` and `./smoke.sh gpu /path/to/lmp_kokkos_cuda_cray`.
