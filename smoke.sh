#!/usr/bin/env bash
# Run with the two installed modulefiles loaded.
set -eu -o pipefail
export LC_ALL=C
tmp=$(mktemp -d "${TMPDIR:-/tmp}/mesh-smoke.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
cd "$tmp"

# Extrude a triangular base to make a closed surface using built-in CAD.
cat > prism.geo <<'GEO'
Point(1) = {0, 0, 0, 0.35};
Point(2) = {1, 0, 0, 0.35};
Point(3) = {0, 1, 0, 0.35};
Line(1) = {1, 2};
Line(2) = {2, 3};
Line(3) = {3, 1};
Curve Loop(1) = {1, 2, 3};
Plane Surface(1) = {1};
Extrude {0, 0, 1} { Surface{1}; }
GEO
gmsh -nopopup -v 2 -setnumber General.AbortOnError 3 -2 prism.geo -format stl -o surface.stl
admesh --write-binary-stl=repaired.stl surface.stl
test -s repaired.stl

# Read the ADMesh output back, parametrize its surfaces, and mesh its volume.
cat > volume.geo <<'GEO'
Merge "repaired.stl";
ClassifySurfaces{40 * Pi/180, 1, 0, Pi};
CreateGeometry;
Surface Loop(1) = Surface{:};
Volume(1) = {1};
Mesh.MeshSizeMax = 0.35;
Mesh.Binary = 0;
GEO
gmsh -nopopup -v 2 -setnumber General.AbortOnError 3 -3 volume.geo -format msh2 -o volume.msh
awk '/^\$Elements$/ {in_elements=1; next}
     /^\$EndElements$/ {in_elements=0}
     in_elements && NF > 3 && $2 == 4 {tets++}
     END {if (!tets) exit 1; print "STL round trip passed (" tets " tetrahedra)"}' volume.msh
