# Offline Gmsh and ADMesh installation

Build Gmsh 4.15.2 and ADMesh 0.98.5 on the target Linux cluster. Gmsh runs headless with its built-in geometry kernel, meshing, STL reparametrization, postprocessing and the GEO parser. Its release includes Eigen, GMM, ANN, MathEx and METIS for this configuration. STEP/IGES, OpenCASCADE, FLTK and the Gmsh SDK are outside this build profile. ADMesh installs its CLI, shared C library and headers.

## Get the transfer bundle

The GitHub release includes both source archives, the installer, and the home and shared-site configurations. Download the two release assets on a machine with access to the repository and transfer them together. [Download the release](https://github.com/ray12514/mesh-tools-offline/releases/latest)

```sh
gh release download v0.1.0 --repo ray12514/mesh-tools-offline --pattern 'mesh-tools-offline.tar.gz*'
```

## Prepare a bundle from the repository

On any machine with Python 3.6+ and access to both upstream sites, run this from the installer directory.

```sh
python3 prepare.py --output mesh-tools-offline.tar.gz
```

If different machines can reach different sites, download the two release archives by any available route, collect them in one directory and keep their original filenames. The staging machine can package them without network access.

```sh
python3 prepare.py --from-dir /path/to/downloads --output mesh-tools-offline.tar.gz
```

Transfer the resulting archive and its `.sha256` file. Both prepare and install check the source files against the hashes in `sources.json`. The Gmsh pin matches the project's published SHA-256. The ADMesh pin matches the maintainer's release asset and the Homebrew source formula. [Gmsh tarball](https://gmsh.info/src/gmsh-4.15.2-source.tgz) · [Gmsh checksum](https://gmsh.info/src/gmsh-4.15.2-source.tgz.sha256) · [ADMesh release tarball](https://github.com/admesh/admesh/releases/download/v0.98.5/admesh-0.98.5.tar.gz) · [ADMesh source formula](https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/a/admesh.rb)

## Build on the target

Use a Linux build node with the target OS and CPU baseline. It needs Python 3.6+, Bash, a C99/C++14 compiler toolchain, CMake 3.15+, GNU Make, tar/gzip, awk, coreutils, readelf, ldd and Lmod or Environment Modules. The compiler runtimes and installation paths must also be visible on the compute nodes. No root access, package manager or network is needed during installation.

```sh
sha256sum -c mesh-tools-offline.tar.gz.sha256
tar -xzf mesh-tools-offline.tar.gz
cd mesh-tools
```

### First run in your home directory

Use the supplied `home.ini` after extracting the bundle. Load your compiler and CMake as usual, then run these commands from `mesh-tools/`.

```sh
python3 install.py home.ini
module use "$HOME/mesh-test/modulefiles"
module avail gmsh admesh
module load gmsh/4.15.2-home-test admesh/0.98.5-home-test
gmsh --version
admesh --version
```

`home.ini` puts the software in `~/mesh-test/software`, the module links in `~/mesh-test/modulefiles`, and private build directories in `~/mesh-test/build`. Each real modulefile stays under its package's version and build tag. For example, `~/mesh-test/modulefiles/gmsh/4.15.2-home-test` points to `~/mesh-test/software/gmsh/4.15.2/home-test/modules/4.15.2-home-test`.

`module_root` is the parent containing the `gmsh/` and `admesh/` directories. In an independent shell or batch job, run `module use` if that root is absent from `MODULEPATH`. When you publish into a writable root already in `MODULEPATH`, go straight to `module avail` or `module load`. The installer tests loads in a child shell. [Environment Modules command reference](https://modules.readthedocs.io/en/latest/module.html#module-subcommand-use)

### Install in a shared software tree

Copy `site.ini` to `cluster.ini`. Edit `cluster.ini` and load the site's compiler and CMake modules in the current shell. For Intel oneAPI set `cc = icx` and `cxx = icpx`. For GCC use `gcc` and `g++`. If the loaded environment already exports `CC` and `CXX`, leave both fields empty. Compiler module names alone may not select the compiler behind `cc` and `c++`. Compiler wrapper commands such as `cc` and `CC` also work when they are executable drivers on PATH.

Set `install_root` to the software parent, `module_root` to an existing MODULEPATH entry (or a new directory you plan to add with `module use`), `build_root` to scratch, and `group` to your team's Unix group. Pick a versioned `build_tag`, such as `intel-2025.3` or `gcc-13.3`. Set `jobs` to the parallelism allowed by your allocation. Use absolute build/install/runtime paths without spaces or shell punctuation for the upstream build tools. For rehearsal, use separate test install and module roots.

Both scripts use the Python standard library. If `python3 --version` reports 3.6 or later, use the existing interpreter in your compiler environment. A versioned executable such as `python3.11` works in the same command. Calling it directly lets you keep the compiler and CMake modules you chose. The installed `gmsh` and `admesh` commands run independently of Python.

```sh
python3 install.py cluster.ini
```

The installer verifies both sources, builds each release under a private scratch directory, stages the installs, checks versions and ELF linkage with the loader environment cleared, and tests both modulefiles together before publishing. The end-to-end check meshes a closed prism from built-in GEO, processes its STL with ADMesh, and remeshes the result in Gmsh. It requires actual tetrahedra in the output. The installer repeats the check through the shared module path. Build logs and linkage reports remain in the private directory printed at startup.

For the example Intel tag, the published layout is

```text
<install_root>/gmsh/4.15.2/intel-2025.3/bin/gmsh
<install_root>/gmsh/4.15.2/intel-2025.3/modules/4.15.2-intel-2025.3
<module_root>/gmsh/4.15.2-intel-2025.3 -> the modulefile above

<install_root>/admesh/0.98.5/intel-2025.3/bin/admesh
<install_root>/admesh/0.98.5/intel-2025.3/lib/libadmesh.so.1
<install_root>/admesh/0.98.5/intel-2025.3/modules/0.98.5-intel-2025.3
<module_root>/admesh/0.98.5-intel-2025.3 -> the modulefile above
```

Installed directories use `2775`, executables use `0775`, and ordinary files use `0664`. Newly created shared parents inherit the selected group. Existing site directories retain their permissions. The per-run build and log directory is `0700`. Each build includes `build-info.json` with compiler versions, flags, runtime paths and source checksums. A rerun rechecks a matching installation. For a different toolchain or recipe, use a new build tag to publish alongside it.

## Use alongside Cart3D

Gmsh, ADMesh and NASA's Cart3D run as separate programs in this workflow. You can use GCC-built mesh tools with an Intel-built Cart3D. Each program needs its own runtime libraries, and each file handoff needs a format the receiving program supports. For example, Cart3D's `flowCart` reads surface geometry as a Cart3D triangulation such as `Components.i.tri`. [Cart3D documentation](https://www.nas.nasa.gov/publications/software/docs/cart3d/) · [flowCart input files](https://www.nas.nasa.gov/publications/software/docs/cart3d/pages/flowCart_io.html)

Load the mesh tools alongside your usual Cart3D environment. Use the module names matching your build tag. Run `module use /your/module/root` first if your site does not already expose that directory.

```sh
module load gmsh/4.15.2-intel-2025.3 admesh/0.98.5-intel-2025.3
gmsh --version
admesh --version
```

A successful install includes the library, module and Gmsh/ADMesh file-exchange checks. The separate `python3 install.py --verify-only cluster.ini` command is optional. It repeats those checks on the two installed mesh commands, for example on another compute node or after a site module changes.

Both modulefiles add only their own `bin` directory to PATH. Each executable gets Linux `DT_RPATH` beginning with its own versioned `lib` directory, followed by target runtime directories. ADMesh also embeds the path in its shared library. The installer queries the chosen compiler drivers for their runtime locations. If a site compiler needs other libraries, add their absolute, versioned directories to `runtime_dirs` before building. Use directories shared by every target node.

On glibc Linux, DT_RPATH takes precedence over LD_LIBRARY_PATH for a binary without DT_RUNPATH. Each mesh executable can resolve its own libraries while sharing a shell with Cart3D. [Linux dynamic loader](https://man7.org/linux/man-pages/man8/ld.so.8.html)
