// The C++ codec's tests: the conformance files read as their expected values, written and read back the same, every
// column type, meshes, sequences, and what the specification forbids refused.
//
//     encoding3d_tests CONFORMANCE
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "encoding3d/encoding3d.hpp"

namespace filesystem = std::filesystem;
using namespace encoding3d;

namespace {

int failures = 0, checks = 0;

void check(bool condition, const std::string &what) {
    ++checks;
    if (!condition) {
        ++failures;
        std::cerr << "FAILED: " << what << "\n";
    }
}

template <typename Function> void check_throws(Function function, const std::string &what) {
    bool thrown = false;
    try {
        function();
    } catch (const Error &) {
        thrown = true;
    }
    check(thrown, what + " (an Error expected)");
}

std::vector<filesystem::path> conformance_files(const filesystem::path &conformance) {
    std::vector<filesystem::path> files;
    for (const auto &entry : filesystem::recursive_directory_iterator(conformance))
        if (entry.is_regular_file() && entry.path().extension() == ".glb" &&
            entry.path().string().find("coupling") == std::string::npos)    // the coupling sessions: their own check
            files.push_back(entry.path());
    std::sort(files.begin(), files.end());
    return files;
}

json expected_of(const filesystem::path &glb) {
    auto path = glb;
    path.replace_extension(".expected.json");
    std::ifstream file(path, std::ios::binary);
    return json::parse(file);
}

std::vector<std::uint8_t> file_bytes(const filesystem::path &path) {
    std::ifstream file(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

void report(const std::vector<std::string> &differences, const std::string &what) {
    for (std::size_t item = 0; item < std::min<std::size_t>(differences.size(), 5); ++item)
        std::cerr << "  " << differences[item] << "\n";
    check(differences.empty(), what);
}

void test_conformance(const filesystem::path &conformance) {
    const auto files = conformance_files(conformance);
    check(files.size() == 10, "ten conformance files");
    for (const auto &path : files) {
        const auto name = filesystem::relative(path, conformance).string();
        const auto data = file_bytes(path);
        auto [document, binary] = unpack(data);                              // the container, repacked
        auto [again, binary_again] = unpack(pack(document, binary));
        check(binary_again == binary && again == document && binary.size() % 8 == 0, "GLB repacked: " + name);
        const auto frame = read_frame(path.string());                         // reading
        report(compare(json::parse(frame_to_json(frame).dump()), expected_of(path)), "read as expected: " + name);
        const auto written = from_bytes(to_bytes(frame));                     // writing
        report(compare(json::parse(frame_to_json(written).dump()), expected_of(path)), "written and read: " + name);
    }
}

void test_columns() {
    EntitySet organs("Organ", 1);
    organs.set("id", std::vector<std::int32_t>{0, 1, 2})
        .set("label", {"Leaf", "Internode", "Leaf"})
        .set("parent", std::vector<std::int64_t>{-1, 0, 1})
        .set("edge_type", {"none", "successor", "branch"})
        .set("with_nan", std::vector<double>{1.0, std::nan(""), -2.5})
        .set("with_infinities", std::vector<float>{std::numeric_limits<float>::infinity(), 1.f,
                                                   -std::numeric_limits<float>::infinity()})
        .set("flag", std::vector<bool>{true, false, true})
        .set("name", {"\xc3\xa9", "", "a b"})
        .set("position", Column(std::vector<double>{1, 2, 3, 4, 5, 6, 7, 8, 9}, 3))
        .set("column_int8", std::vector<std::int8_t>{1, 2, 3})
        .set("column_uint8", std::vector<std::uint8_t>{1, 2, 3})
        .set("column_int16", std::vector<std::int16_t>{1, 2, 3})
        .set("column_uint16", std::vector<std::uint16_t>{1, 2, 3})
        .set("column_int32", std::vector<std::int32_t>{1, 2, 3})
        .set("column_uint32", std::vector<std::uint32_t>{1, 2, 3})
        .set("column_uint64", std::vector<std::uint64_t>{1, 2, 3});
    Variable length;
    length.unit = "m";
    length.standard_name = "length";
    length.kind = "extensive";
    length.description = "a length";
    length.minimum = 0;
    length.references = {"a reference"};
    organs.declare("with_nan", length);
    DataStructure plants("plants");
    plants.entity_sets.push_back(organs);
    plants.origin = {1, 0, 0, 0.5, 0, 1, 0, 0, 0, 0, 1, -0.1, 0, 0, 0, 1};
    plants.extras = {{"platform", {1, 2}}};
    Frame frame;
    frame.data_structures.push_back(plants);
    frame.time = 2.5;
    frame.time_unit = "h";
    frame.step = 3;

    const auto read_back = from_bytes(to_bytes(frame));
    const auto &set = read_back.data_structure("plants").entity_set("Organ");
    check(set.column("id").holds<std::int64_t>(), "ids are int64");
    const auto &with_nan = set.column("with_nan").as<double>();
    check(with_nan[0] == 1.0 && std::isnan(with_nan[1]) && with_nan[2] == -2.5, "NaN read back");
    const auto &infinities = set.column("with_infinities").as<float>();
    check(std::isinf(infinities[0]) && infinities[0] > 0 && infinities[1] == 1.f && std::isinf(infinities[2]) &&
              infinities[2] < 0, "infinities read back");
    check(set.column("flag").as<bool>() == std::vector<bool>{true, false, true}, "booleans read back");
    check(set.column("name").as<std::string>() == std::vector<std::string>{"\xc3\xa9", "", "a b"}, "text read back");
    check(set.column("position").width == 3 &&
              set.column("position").as<double>() == std::vector<double>{1, 2, 3, 4, 5, 6, 7, 8, 9}, "vectors read back");
    check(set.column("label").as<std::string>() == std::vector<std::string>{"Leaf", "Internode", "Leaf"}, "labels");
    check(set.column("column_uint16").as<std::uint16_t>() == std::vector<std::uint16_t>{1, 2, 3}, "uint16 read back");
    check(set.column("column_uint64").as<std::uint64_t>() == std::vector<std::uint64_t>{1, 2, 3}, "uint64 read back");
    check(set.variables.at("with_nan") == length, "declaration read back");
    check(read_back.data_structure("plants").origin == plants.origin, "origin read back");
    check(read_back.data_structure("plants").extras == plants.extras, "extras read back");
    check(read_back.time == 2.5 && read_back.time_unit == "h" && read_back.step == 3, "time read back");
}

void test_mesh() {
    EntitySet segments("SubOrgan", 6);
    segments.set("id", std::vector<std::int64_t>{10, 11});
    Mesh mesh;
    mesh.name = "roots";
    mesh.positions = {0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1};
    mesh.feature_rows = {{"SubOrgan", {0, 1, 1, -1}}};
    mesh.indices = std::vector<std::int64_t>{0, 1, 2, 0, 2, 3};
    mesh.display = {{"radius", {1.f, 2.f, 2.f, 0.f}}};
    mesh.display_sources = {{"radius", "SubOrgan"}};
    DataStructure roots("roots");
    roots.entity_sets.push_back(segments);
    roots.meshes.push_back(mesh);
    Frame frame;
    frame.data_structures.push_back(roots);
    const auto read_back = from_bytes(to_bytes(frame)).data_structures[0].meshes[0];
    check(read_back.positions == mesh.positions && read_back.feature_rows == mesh.feature_rows &&
              read_back.indices == mesh.indices && read_back.display == mesh.display &&
              read_back.display_sources == mesh.display_sources, "mesh read back");
}

void test_refused() {
    auto frame_with = [](EntitySet set) {
        DataStructure plants("plants");
        plants.entity_sets.push_back(std::move(set));
        Frame frame;
        frame.data_structures.push_back(plants);
        return frame;
    };
    EntitySet bad_column("Organ");
    bad_column.set("id", std::vector<std::int64_t>{0}).set("1st", std::vector<double>{1.0});
    check_throws([&] { to_bytes(frame_with(bad_column)); }, "a column name that is not an identifier");
    Frame bad_id;
    bad_id.data_structures.emplace_back("bad id");
    check_throws([&] { to_bytes(bad_id); }, "a data structure id that is not an identifier");
    EntitySet bad_edge("Organ");
    bad_edge.set("id", std::vector<std::int64_t>{0}).set("parent", std::vector<std::int64_t>{-1}).set("edge_type", {"root"});
    check_throws([&] { to_bytes(frame_with(bad_edge)); }, "an unknown edge type");
    EntitySet both("Organ");
    both.set("id", std::vector<std::int64_t>{0, 1})
        .set("x", std::vector<double>{std::nan(""), std::numeric_limits<double>::lowest()});
    check_throws([&] { to_bytes(frame_with(both)); }, "NaN and its stand-in in one column");
    EntitySet lengths("Organ");
    lengths.set("id", std::vector<std::int64_t>{0, 1}).set("x", std::vector<double>{1.0});
    check_throws([&] { to_bytes(frame_with(lengths)); }, "columns of different lengths");
    check_throws([] { unpack({1, 2, 3}); }, "not a GLB file");
}

void test_sequence(const filesystem::path &conformance) {
    const auto folder = filesystem::temp_directory_path() / "encoding3d_cpp_sequence";
    filesystem::remove_all(folder);
    std::vector<Frame> frames;
    for (int step = 0; step < 3; ++step) {
        EntitySet plant("Plant", 1);
        plant.set("id", std::vector<std::int64_t>{0}).set("biomass", std::vector<double>{double(step)});
        DataStructure plants("plants");
        plants.entity_sets.push_back(plant);
        Frame frame;
        frame.data_structures.push_back(plants);
        frame.time = step / 24.0;
        frame.step = step;
        frames.push_back(frame);
    }
    const auto index = write_sequence(folder.string(), frames);
    const auto entries = read_index(index).frames;
    check(entries.size() == 3 && entries[2].step == 2, "index written and read");
    const auto read_back = read_sequence(index);
    check(read_back.size() == 3 && read_back[2].data_structures[0].entity_sets[0].column("biomass").as<double>()[0] == 2.0,
          "sequence read back");
    const auto growing = read_index((conformance / "growing_sequence" / INDEX_FILE).string());
    check(std::all_of(growing.frames.begin(), growing.frames.end(),
                      [](const IndexEntry &entry) { return filesystem::exists(entry.path); }),
          "the conformance sequence's files found");
    filesystem::remove_all(folder);
}

} // namespace

void test_partial_frame() {
    // A coupling session's message: the sender and the removed entities kept, the reference checks lifted
    EntitySet segments("SubOrgan", 6);
    segments.set("id", Column(std::vector<std::int64_t>{10, 11}))
        .set("complex", Column(std::vector<std::int64_t>{3, 3}))
        .set("sugar", Column(std::vector<double>{1.0, 2.0}));
    DataStructure plant("plant");
    plant.entity_sets.push_back(segments);
    Frame frame;
    frame.data_structures.push_back(plant);
    frame.update = Update{"vpl", {{{"plant", "SubOrgan"}, {5, 6}}}};
    const auto again = from_bytes(to_bytes(frame));
    check(again.update && again.update->participant == "vpl", "partial frame: its sender");
    check(again.update->removed.at({"plant", "SubOrgan"}) == std::vector<std::int64_t>{5, 6},
          "partial frame: its removed entities");
    check(frame_to_json(again)["update"]["removed"][0]["ids"] == json::array({5, 6}), "partial frame: its dump");
}

int main(int argument_count, char **arguments) {
    if (argument_count != 2) {
        std::cerr << "usage: encoding3d_tests CONFORMANCE\n";
        return 2;
    }
    const filesystem::path conformance = arguments[1];
    const std::vector<std::pair<std::string, std::function<void()>>> tests = {
        {"conformance", [&] { test_conformance(conformance); }}, {"columns", test_columns}, {"mesh", test_mesh},
        {"refused", test_refused}, {"sequence", [&] { test_sequence(conformance); }},
        {"partial frame", test_partial_frame}};
    for (const auto &[name, test] : tests) {
        try {
            test();
        } catch (const std::exception &error) {
            check(false, name + ": " + error.what());
        }
    }
    std::cout << checks - failures << " of " << checks << " checks passed\n";
    return failures == 0 ? 0 : 1;
}
