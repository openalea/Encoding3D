# CPlantBox's adapter (fspm_tf::cplantbox), on CPlantBox's built library and its sources' headers:
#
#   cmake -S bindings/cpp -B build -DFSPM_TF_CPLANTBOX_SOURCE_DIR=/path/to/CPlantBox \
#         -DFSPM_TF_CPLANTBOX_LIBRARY=/path/to/build/src/libCPlantBox.a
#
# It is meant to move into CPlantBox once its team agrees (devplan_bindings.md, P4).
set(CPLANTBOX_SOURCE "${FSPM_TF_CPLANTBOX_SOURCE_DIR}/src")
add_library(CPlantBox::CPlantBox UNKNOWN IMPORTED)
set_target_properties(CPlantBox::CPlantBox PROPERTIES
    IMPORTED_LOCATION "${FSPM_TF_CPLANTBOX_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${CPLANTBOX_SOURCE}/structural;${CPLANTBOX_SOURCE}/functional;${CPLANTBOX_SOURCE}/visualisation;${CPLANTBOX_SOURCE}/external/tinyxml2;${CPLANTBOX_SOURCE}/external/eigen")

add_library(fspm_tf_cplantbox src/cplantbox.cpp)
add_library(fspm_tf::cplantbox ALIAS fspm_tf_cplantbox)
target_include_directories(fspm_tf_cplantbox PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(fspm_tf_cplantbox PUBLIC fspm_tf::fspm_tf CPlantBox::CPlantBox)
if(MSVC)
    target_compile_definitions(fspm_tf_cplantbox PRIVATE _USE_MATH_DEFINES NOMINMAX)
endif()

if(FSPM_TF_BUILD_TESTS)
    add_executable(fspm_tf_cplantbox_tests test/test_cplantbox.cpp)
    target_link_libraries(fspm_tf_cplantbox_tests PRIVATE fspm_tf::cplantbox)
    add_test(NAME fspm_tf_cplantbox_tests
             COMMAND fspm_tf_cplantbox_tests "${FSPM_TF_CONFORMANCE}" "${FSPM_TF_CPLANTBOX_SOURCE_DIR}/modelparameter/structural"
                     "${CMAKE_CURRENT_BINARY_DIR}/cplantbox_out")
endif()
