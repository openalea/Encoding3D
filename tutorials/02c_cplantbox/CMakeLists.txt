# Tutorial 2c: CPlantBox writes and reads encoding3d. Built on CPlantBox's sources and library (README.md):
#
#   cmake -S . -B build -DCPLANTBOX_SOURCE_DIR=/path/to/CPlantBox -DCPLANTBOX_LIBRARY=/path/to/libCPlantBox.a
#   cmake --build build && ./build/cplantbox_tutorial /path/to/CPlantBox/modelparameter/structural outputs
cmake_minimum_required(VERSION 3.16)
project(encoding3d_tutorial_cplantbox LANGUAGES CXX)

set(CPLANTBOX_SOURCE_DIR "" CACHE PATH "CPlantBox's source folder")
set(CPLANTBOX_LIBRARY "" CACHE FILEPATH "CPlantBox's built library (libCPlantBox.a)")
if(NOT CPLANTBOX_SOURCE_DIR OR NOT CPLANTBOX_LIBRARY)
    message(FATAL_ERROR "give CPlantBox: -DCPLANTBOX_SOURCE_DIR=... -DCPLANTBOX_LIBRARY=... (README.md)")
endif()

# encoding3d's C++ codec and CPlantBox's adapter, from this repository
set(ENCODING3D_CPLANTBOX_SOURCE_DIR "${CPLANTBOX_SOURCE_DIR}" CACHE PATH "" FORCE)
set(ENCODING3D_CPLANTBOX_LIBRARY "${CPLANTBOX_LIBRARY}" CACHE FILEPATH "" FORCE)
set(ENCODING3D_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory(../../bindings/cpp encoding3d)

add_executable(cplantbox_tutorial cplantbox_tutorial.cpp)
target_link_libraries(cplantbox_tutorial PRIVATE encoding3d::cplantbox)
