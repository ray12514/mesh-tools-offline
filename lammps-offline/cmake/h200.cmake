if(CMAKE_VERSION VERSION_LESS 3.28)
  message(FATAL_ERROR "Load CMake 3.28 or newer for CrayClang compiler detection.")
endif()

if(LAMMPS_CRAY_LANE STREQUAL "gnu" AND NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
  message(FATAL_ERROR "The selected Cray CC driver is using ${CMAKE_CXX_COMPILER_ID}, expected GNU.")
elseif(LAMMPS_CRAY_LANE STREQUAL "cray" AND NOT CMAKE_CXX_COMPILER_ID MATCHES "^Cray(Clang)?$")
  message(FATAL_ERROR "The selected Cray CC driver is using ${CMAKE_CXX_COMPILER_ID}, expected CCE.")
endif()

function(lammps_cray_link)
  get_property(launcher GLOBAL PROPERTY RULE_LAUNCH_COMPILE)
  if(NOT launcher MATCHES "kokkos_launch_compiler")
    message(FATAL_ERROR "Expected bundled Kokkos to route CUDA compilation through nvcc_wrapper.")
  endif()

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
  cmake_language(DEFER CALL lammps_cray_link)
endif()
