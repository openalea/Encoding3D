# Tutorial 4, CPlantBox's side: the root architecture as a coupling session's participant (../README.md).
#
#   cmake -S . -B build -DCPLANTBOX_SOURCE_DIR=/path/to/CPlantBox -DCPLANTBOX_LIBRARY=/path/to/libCPlantBox.a
cmake_minimum_required(VERSION 3.16)
project(encoding3d_tutorial_four_platforms_cplantbox LANGUAGES CXX)

set(CPLANTBOX_SOURCE_DIR "" CACHE PATH "CPlantBox's source folder")
set(CPLANTBOX_LIBRARY "" CACHE FILEPATH "CPlantBox's built library (libCPlantBox.a)")
if(NOT CPLANTBOX_SOURCE_DIR OR NOT CPLANTBOX_LIBRARY)
    message(FATAL_ERROR "give CPlantBox: -DCPLANTBOX_SOURCE_DIR=... -DCPLANTBOX_LIBRARY=... (../README.md)")
endif()
set(ENCODING3D_CPLANTBOX_SOURCE_DIR "${CPLANTBOX_SOURCE_DIR}" CACHE PATH "" FORCE)
set(ENCODING3D_CPLANTBOX_LIBRARY "${CPLANTBOX_LIBRARY}" CACHE FILEPATH "" FORCE)
set(ENCODING3D_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory(../../../bindings/cpp encoding3d)

add_executable(roots roots.cpp)
target_link_libraries(roots PRIVATE encoding3d::cplantbox)
target_compile_definitions(roots PRIVATE CPLANTBOX_PARAMETERS="${CPLANTBOX_SOURCE_DIR}/modelparameter/structural")
