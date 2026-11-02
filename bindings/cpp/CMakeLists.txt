# fspm_tf, the C++ codec of fspm-TF: a library (fspm_tf::fspm_tf), its tests, the conformance tool, and, when
# CPlantBox is given (FSPM_TF_CPLANTBOX_SOURCE_DIR and FSPM_TF_CPLANTBOX_LIBRARY), CPlantBox's adapter.
#
#   cmake -S bindings/cpp -B build && cmake --build build && ctest --test-dir build
cmake_minimum_required(VERSION 3.16)
project(fspm_tf VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(FSPM_TF_BUILD_TESTS "Build the tests and the conformance tool" ${PROJECT_IS_TOP_LEVEL})
set(FSPM_TF_CPLANTBOX_SOURCE_DIR "" CACHE PATH "CPlantBox's source folder (its src/ holds structural/), for the adapter")
set(FSPM_TF_CPLANTBOX_LIBRARY "" CACHE FILEPATH "CPlantBox's built library (libCPlantBox), for the adapter")

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

add_library(fspm_tf
    src/model.cpp
    src/glb.cpp
    src/codec.cpp
    src/sequence.cpp
    src/dump.cpp)
add_library(fspm_tf::fspm_tf ALIAS fspm_tf)
target_include_directories(fspm_tf PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries(fspm_tf PUBLIC nlohmann_json::nlohmann_json)
target_compile_features(fspm_tf PUBLIC cxx_std_17)
set_target_properties(fspm_tf PROPERTIES POSITION_INDEPENDENT_CODE ON)
if(MSVC)
    target_compile_options(fspm_tf PRIVATE /W4 /bigobj)
else()
    target_compile_options(fspm_tf PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Installed as a CMake package: find_package(fspm_tf) then target_link_libraries(... fspm_tf::fspm_tf)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
install(TARGETS fspm_tf EXPORT fspm_tfTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT fspm_tfTargets NAMESPACE fspm_tf:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/fspm_tf)
configure_package_config_file(cmake/fspm_tfConfig.cmake.in ${CMAKE_CURRENT_BINARY_DIR}/fspm_tfConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/fspm_tf)
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/fspm_tfConfigVersion.cmake
    COMPATIBILITY SameMinorVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/fspm_tfConfig.cmake ${CMAKE_CURRENT_BINARY_DIR}/fspm_tfConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/fspm_tf)

if(FSPM_TF_BUILD_TESTS)
    enable_testing()
    set(FSPM_TF_CONFORMANCE "${CMAKE_CURRENT_SOURCE_DIR}/../../conformance")
    add_executable(fspm_tf_conformance_run tools/conformance_run.cpp)
    target_link_libraries(fspm_tf_conformance_run PRIVATE fspm_tf::fspm_tf)
    add_executable(fspm_tf_tests test/test_fspm_tf.cpp)
    target_link_libraries(fspm_tf_tests PRIVATE fspm_tf::fspm_tf)
    add_test(NAME fspm_tf_tests COMMAND fspm_tf_tests "${FSPM_TF_CONFORMANCE}")
endif()

# CPlantBox's adapter: built when CPlantBox's sources and library are given
if(FSPM_TF_CPLANTBOX_SOURCE_DIR AND FSPM_TF_CPLANTBOX_LIBRARY)
    add_subdirectory(cplantbox)
endif()
