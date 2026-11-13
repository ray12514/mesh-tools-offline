#!/usr/bin/env bash
# Called by install.py with CC, CXX and LDFLAGS from the site configuration.
set -eu -o pipefail
package=$1 archive=$2 prefix=$3 stage=$4 jobs=$5
mkdir src obj
tar -xf "$archive" -C src --strip-components=1
case "$package" in
    admesh)
        cd obj
        ../src/configure --prefix="$prefix" --libdir="$prefix/lib" --disable-static
        make -j "$jobs"
        make DESTDIR="$stage" install
        ;;
    gmsh)
        # Built-in CAD, STL reparametrization, meshing and size fields.
        # These features and their contributed libraries ship in the release.
        # Set RPATH through LDFLAGS because upstream replaces CMAKE_INSTALL_RPATH.
        cmake -S src -B obj -G 'Unix Makefiles' \
            -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib \
            -DCMAKE_BUILD_TYPE=Release -DGMSH_RELEASE=ON \
            -DDEFAULT=OFF -DENABLE_MESH=ON -DENABLE_PARSER=ON \
            -DENABLE_POST=ON -DENABLE_SOLVER=ON -DENABLE_GMM=ON \
            -DENABLE_MATHEX=ON -DENABLE_ANN=ON -DENABLE_EIGEN=ON -DENABLE_METIS=ON \
            -DENABLE_SYSTEM_CONTRIB=OFF -DENABLE_RPATH=OFF
        cmake --build obj --parallel "$jobs"
        DESTDIR="$stage" cmake --install obj
        ;;
    *) echo "Unknown package: $package" >&2; exit 2 ;;
esac
