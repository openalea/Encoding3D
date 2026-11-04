# CPlantBox's adapter (encoding3d::cplantbox), on CPlantBox's built library and its sources' headers:
#
#   cmake -S bindings/cpp -B build -DENCODING3D_CPLANTBOX_SOURCE_DIR=/path/to/CPlantBox \
#         -DENCODING3D_CPLANTBOX_LIBRARY=/path/to/build/src/libCPlantBox.a
#
# It is meant to move into CPlantBox once its team agrees (devplan_bindings.md, P4).
set(CPLANTBOX_SOURCE "${ENCODING3D_CPLANTBOX_SOURCE_DIR}/src")
add_library(CPlantBox::CPlantBox UNKNOWN IMPORTED)
set_target_properties(CPlantBox::CPlantBox PROPERTIES
    IMPORTED_LOCATION "${ENCODING3D_CPLANTBOX_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${CPLANTBOX_SOURCE}/structural;${CPLANTBOX_SOURCE}/functional;${CPLANTBOX_SOURCE}/visualisation;${CPLANTBOX_SOURCE}/external/tinyxml2;${CPLANTBOX_SOURCE}/external/eigen")

add_library(encoding3d_cplantbox src/cplantbox.cpp)
add_library(encoding3d::cplantbox ALIAS encoding3d_cplantbox)
target_include_directories(encoding3d_cplantbox PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(encoding3d_cplantbox PUBLIC encoding3d::encoding3d CPlantBox::CPlantBox)
if(MSVC)
    target_compile_definitions(encoding3d_cplantbox PRIVATE _USE_MATH_DEFINES NOMINMAX)
endif()

if(ENCODING3D_BUILD_TESTS)
    add_executable(encoding3d_cplantbox_tests test/test_cplantbox.cpp)
    target_link_libraries(encoding3d_cplantbox_tests PRIVATE encoding3d::cplantbox)
    add_test(NAME encoding3d_cplantbox_tests
             COMMAND encoding3d_cplantbox_tests "${ENCODING3D_CONFORMANCE}" "${ENCODING3D_CPLANTBOX_SOURCE_DIR}/modelparameter/structural"
                     "${CMAKE_CURRENT_BINARY_DIR}/cplantbox_out")
endif()
