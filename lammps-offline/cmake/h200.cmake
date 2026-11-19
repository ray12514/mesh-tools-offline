if(CMAKE_VERSION VERSION_LESS 3.28)
  message(FATAL_ERROR "Load CMake 3.28 or newer for CrayClang compiler detection.")
endif()

if(LAMMPS_CRAY_LANE STREQUAL "gnu" AND NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
  message(FATAL_ERROR "The selected Cray CC driver is using ${CMAKE_CXX_COMPILER_ID}, expected GNU.")
elseif(LAMMPS_CRAY_LANE STREQUAL "cray" AND NOT CMAKE_CXX_COMPILER_ID MATCHES "^Cray(Clang)?$")
  message(FATAL_ERROR "The selected Cray CC driver is using ${CMAKE_CXX_COMPILER_ID}, expected CCE.")
endif()

function(lammps_cray_cuda)
  get_property(launcher GLOBAL PROPERTY RULE_LAUNCH_COMPILE)
  if(NOT launcher MATCHES "kokkos_launch_compiler")
    message(FATAL_ERROR "Expected bundled Kokkos to route CUDA compilation through nvcc_wrapper.")
  endif()

  # FindMPI can succeed using CC's implicit MPI flags. The Kokkos launcher
  # bypasses CC for CUDA compilation, so nvcc must receive the header path.
  set(mpi_hints ${MPI_CXX_INCLUDE_DIRS})
  if(NOT "$ENV{MPICH_DIR}" STREQUAL "")
    list(PREPEND mpi_hints "$ENV{MPICH_DIR}/include")
  endif()
  find_path(cray_mpi_include NAMES mpi.h HINTS ${mpi_hints} NO_DEFAULT_PATH NO_CACHE)
  if(NOT cray_mpi_include)
    message(FATAL_ERROR "Cannot find mpi.h for nvcc. Check that the loaded cray-mpich module provides MPICH_DIR/include/mpi.h.")
  endif()
  message(STATUS "Cray MPICH headers for nvcc: ${cray_mpi_include}")
  foreach(target IN ITEMS lammps lmp)
    # An include directory marked implicit by CC can be dropped by CMake.
    target_compile_options(${target} BEFORE PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:-I${cray_mpi_include}>")
  endforeach()

  # Kokkos normally hands CXX links to nvcc too. Keep Cray CC on the final
  # link so the accelerator module contributes its matching CUDA-aware MPI GTL.
  find_package(CUDAToolkit REQUIRED)
  set(link_launcher "bash ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/cray-link.sh")
  set_property(TARGET lmp PROPERTY RULE_LAUNCH_LINK "${link_launcher}")
  target_link_libraries(lmp PRIVATE CUDA::cudart)
  get_target_property(lammps_type lammps TYPE)
  if(lammps_type STREQUAL "SHARED_LIBRARY")
    set_property(TARGET lammps PROPERTY RULE_LAUNCH_LINK "${link_launcher}")
    target_link_libraries(lammps PRIVATE CUDA::cudart)
  endif()
endfunction()

if(LAMMPS_H200_GPU)
  cmake_language(DEFER CALL lammps_cray_cuda)
endif()
