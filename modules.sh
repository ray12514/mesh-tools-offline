#!/usr/bin/env bash
# Keep module initialization and test loads inside this child shell.
set -eo pipefail
if [[ -n $MESH_MODULE_INIT ]]; then
    # shellcheck disable=SC1090
    source "$MESH_MODULE_INIT"
elif ! type module >/dev/null 2>&1; then
    for init in "${MODULESHOME:-/usr/share/Modules}/init/bash" \
        /etc/profile.d/lmod.sh /etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash; do
        if [[ -r $init ]]; then
            # shellcheck disable=SC1090
            source "$init"
            type module >/dev/null 2>&1 && break
        fi
    done
fi
type module >/dev/null 2>&1 || {
    echo 'Set module_init in site.ini to the Bash initializer for Lmod or Environment Modules.' >&2
    exit 1
}
[[ $# -gt 0 ]] || exit 0
# A verification run can start with these exact modules already loaded.
# Force a new lookup through the requested module root in this child shell.
for name in "$2" "$4"; do
    case ":${LOADEDMODULES:-}:" in
        *":$name:"*) module unload "$name" ;;
    esac
done
loader_path=${LD_LIBRARY_PATH-}
module use "$1"
module load "$2" "$4"
[[ ${LD_LIBRARY_PATH-} == "$loader_path" ]] || {
    echo 'The mesh module load changed LD_LIBRARY_PATH.' >&2
    exit 1
}
[[ $(command -v gmsh) == "$3/bin/gmsh" && $(command -v admesh) == "$5/bin/admesh" ]] || {
    echo 'The loaded modules did not select the expected executables.' >&2
    exit 1
}
bash "$6"
