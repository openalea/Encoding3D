# encoding3d, the C++ codec of encoding3d: a library (encoding3d::encoding3d), its tests, the conformance tool, and, when
# CPlantBox is given (ENCODING3D_CPLANTBOX_SOURCE_DIR and ENCODING3D_CPLANTBOX_LIBRARY), CPlantBox's adapter.
#
#   cmake -S bindings/cpp -B build && cmake --build build && ctest --test-dir build
#
# Licence: GPL-3.0 (LICENSE), as CPlantBox; the rest of encoding3d is CeCILL-C.
cmake_minimum_required(VERSION 3.16)
project(encoding3d VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(ENCODING3D_BUILD_TESTS "Build the tests and the conformance tool" ${PROJECT_IS_TOP_LEVEL})
set(ENCODING3D_CPLANTBOX_SOURCE_DIR "" CACHE PATH "CPlantBox's source folder (its src/ holds structural/), for the adapter")
set(ENCODING3D_CPLANTBOX_LIBRARY "" CACHE FILEPATH "CPlantBox's built library (libCPlantBox), for the adapter")

# The one dependency, header-only: nlohmann_json, found installed or fetched
find_package(nlohmann_json 3.11 QUIET)
if(NOT nlohmann_json_FOUND)
    include(FetchContent)
    FetchContent_Declare(nlohmann_json
        URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
        URL_HASH SHA256=42f6e95cad6ec532fd372391373363b62a14af6d771056dbfc86160e6dfff7aa)
    set(JSON_Install ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(nlohmann_json)
endif()

add_library(encoding3d
    src/model.cpp
    src/glb.cpp
    src/codec.cpp
    src/sequence.cpp
    src/dump.cpp
    src/coupling.cpp)
add_library(encoding3d::encoding3d ALIAS encoding3d)
target_include_directories(encoding3d PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(encoding3d PUBLIC nlohmann_json::nlohmann_json)

# The coupling's ZeroMQ transport, with libzmq when found (its folder transport needs nothing)
option(ENCODING3D_WITH_ZMQ "Build the coupling's ZeroMQ transport (libzmq)" ON)
if(ENCODING3D_WITH_ZMQ)
    find_path(ZMQ_INCLUDE_DIR zmq.h)
    find_library(ZMQ_LIBRARY NAMES zmq libzmq)
    if(ZMQ_INCLUDE_DIR AND ZMQ_LIBRARY)
        target_include_directories(encoding3d PRIVATE ${ZMQ_INCLUDE_DIR})
        target_link_libraries(encoding3d PRIVATE ${ZMQ_LIBRARY})
        target_compile_definitions(encoding3d PRIVATE ENCODING3D_WITH_ZMQ)
        message(STATUS "encoding3d: the coupling's ZeroMQ transport, with ${ZMQ_LIBRARY}")
    else()
        message(STATUS "encoding3d: libzmq not found, the coupling's folder transport only")
    endif()
endif()
target_compile_features(encoding3d PUBLIC cxx_std_17)
set_target_properties(encoding3d PROPERTIES POSITION_INDEPENDENT_CODE ON)
if(MSVC)
    target_compile_options(encoding3d PRIVATE /W4 /bigobj)
else()
    target_compile_options(encoding3d PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Installed as a CMake package: find_package(encoding3d) then target_link_libraries(... encoding3d::encoding3d)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
install(TARGETS encoding3d EXPORT encoding3dTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(FILES LICENSE DESTINATION ${CMAKE_INSTALL_DATADIR}/encoding3d)
install(EXPORT encoding3dTargets NAMESPACE encoding3d:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/encoding3d)
configure_package_config_file(cmake/encoding3dConfig.cmake.in ${CMAKE_CURRENT_BINARY_DIR}/encoding3dConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/encoding3d)
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/encoding3dConfigVersion.cmake
    COMPATIBILITY SameMinorVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/encoding3dConfig.cmake ${CMAKE_CURRENT_BINARY_DIR}/encoding3dConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/encoding3d)

if(ENCODING3D_BUILD_TESTS)
    enable_testing()
    set(ENCODING3D_CONFORMANCE "${CMAKE_CURRENT_SOURCE_DIR}/../../conformance")
    add_executable(encoding3d_conformance_run tools/conformance_run.cpp)
    target_link_libraries(encoding3d_conformance_run PRIVATE encoding3d::encoding3d)
    add_executable(encoding3d_coupling_conformance tools/coupling_conformance.cpp)
    target_link_libraries(encoding3d_coupling_conformance PRIVATE encoding3d::encoding3d)
    add_executable(encoding3d_tests test/test_encoding3d.cpp)
    target_link_libraries(encoding3d_tests PRIVATE encoding3d::encoding3d)
    add_test(NAME encoding3d_tests COMMAND encoding3d_tests "${ENCODING3D_CONFORMANCE}")
endif()

# CPlantBox's adapter: built when CPlantBox's sources and library are given
if(ENCODING3D_CPLANTBOX_SOURCE_DIR AND ENCODING3D_CPLANTBOX_LIBRARY)
    add_subdirectory(cplantbox)
endif()
