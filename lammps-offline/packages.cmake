# Common packages for the generic CPU and Kokkos GPU builds.
set(PKG_COLLOID ON CACHE BOOL "")
set(PKG_KSPACE ON CACHE BOOL "")
set(PKG_MANYBODY ON CACHE BOOL "")
set(PKG_MOLECULE ON CACHE BOOL "")
set(PKG_PHONON ON CACHE BOOL "")
set(PKG_RIGID ON CACHE BOOL "")
set(PKG_SHOCK ON CACHE BOOL "")
set(PKG_MISC ON CACHE BOOL "")

# Add more packages or point CMake to compatible local dependencies here.
# set(PKG_ML-IAP ON CACHE BOOL "")
# set(CMAKE_PREFIX_PATH "/path/to/site/dependencies" CACHE STRING "")
# Copy this file and pass --packages to use different lists for CPU and GPU.
