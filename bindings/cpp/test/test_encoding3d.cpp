// The C++ codec's tests: the conformance files read as their expected values, written and read back the same, every
// column type, meshes, sequences, instances and their derived fields, shared parts, archives, and what the
// specification forbids refused.
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
            entry.path().string().find("coupling") == std::string::npos &&   // the coupling sessions: their own check
            entry.path().string().find("instances") == std::string::npos)    // the instances: test_instances
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

json read_json(const filesystem::path &path) {
    std::ifstream file(path, std::ios::binary);
    return json::parse(file);
}

/// {"<data structure>/<instance set>/<field>": values per instance} of a frame's derived fields, as JSON.
json evaluated_json(const Frame &frame) {
    json out = json::object();
    for (const auto &data_structure : frame.data_structures)
        for (const auto &instance_set : data_structure.instance_sets)
            for (const auto &derived : instance_set.derived) {
                json instances = json::array();
                for (const auto &values : evaluate(frame, derived.name, data_structure.id, instance_set.name)) {
                    json items = json::array();
                    for (const auto value : values) items.push_back(std::isnan(value) ? json(nullptr) : json(value));
                    instances.push_back(items);
                }
                out[data_structure.id + "/" + instance_set.name + "/" + derived.name] = instances;
            }
    return out;
}

/// Whether two evaluated fields agree within a relative 1e-12 (a solved operator's values depend on the rounding).
bool close(const json &actual, const json &expected) {
    if (expected.is_object() || expected.is_array()) {
        if (actual.size() != expected.size() || actual.type() != expected.type()) return false;
        if (expected.is_object()) {
            for (const auto &item : expected.items())
                if (!actual.contains(item.key()) || !close(actual[item.key()], item.value())) return false;
            return true;
        }
        for (std::size_t item = 0; item < expected.size(); ++item)
            if (!close(actual[item], expected[item])) return false;
        return true;
    }
    if (expected.is_number())
        return actual.is_number() &&
               std::abs(actual.get<double>() - expected.get<double>()) <= 1e-12 * std::abs(expected.get<double>());
    return actual == expected;
}

void test_instances(const filesystem::path &conformance) {
    const auto folder = conformance / "instances";
    for (const auto &name : {"frame_000000", "frame_000001"}) {
        const auto frame = read_frame((folder / (std::string(name) + ".glb")).string());
        report(compare(json::parse(frame_to_json(frame).dump()), read_json(folder / (std::string(name) + ".expected.json"))),
               std::string("instances read as expected: ") + name);
        check(close(evaluated_json(frame), read_json(folder / (std::string(name) + ".evaluated.json"))),
              std::string("instances evaluated as expected: ") + name);
        const auto again = from_bytes(to_bytes(frame), frame.parts_folder);    // written and read: the same keys
        report(compare(json::parse(frame_to_json(again).dump()), read_json(folder / (std::string(name) + ".expected.json"))),
               std::string("instances written and read: ") + name);
        for (const auto &archive : {"instances_stored", "instances_deflate", "instances_lzma", "instances_zip64"}) {
            const auto in_archive = read_frame((conformance / "archives" / (std::string(archive) + ".fspm.zip") /
                                                (std::string(name) + ".glb")).string());
            report(compare(json::parse(frame_to_json(in_archive).dump()),
                           read_json(folder / (std::string(name) + ".expected.json"))),
                   std::string("read from an archive: ") + archive + "/" + name);
            check(close(evaluated_json(in_archive), read_json(folder / (std::string(name) + ".evaluated.json"))),
                  std::string("evaluated from an archive: ") + archive + "/" + name);
        }
    }
    const auto embedded = read_frame((folder / "embedded.glb").string());
    check(embedded.part_bytes.size() == 5, "embedded: five parts in the frame");
    check(close(evaluated_json(embedded), read_json(folder / "frame_000001.evaluated.json")), "embedded: evaluated");
    for (const auto &entry : filesystem::directory_iterator(folder / "parts")) {
        const auto key = entry.path().stem().string();
        const auto bytes = file_bytes(entry.path());
        check(content_key(bytes) == key, "a part's key is the SHA-256 of its bytes: " + key);
        report(compare(json::parse(part_to_json(read_part(bytes, key)).dump()), read_json(folder / "expected" / (key + ".json"))),
               "part read as expected: " + key);
        check_throws([&] { read_part(bytes, std::string(64, '0')); }, "a part whose bytes do not hash to its key");
    }
    const auto index = read_index((conformance / "archives" / "instances_deflate.fspm.zip").string());
    check(index.frames.size() == 2 && index.parts.size() == 5, "an archive's index: its frames and parts");
    check(content_key({'a', 'b', 'c'}) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          "SHA-256 of 'abc'");
    check(content_key({}) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "SHA-256 of ''");
}

/// A template of `cells` cells (a fan of triangles), its entity set Cell with an area per cell.
Template fan(std::size_t cells) {
    Template made;
    EntitySet set("Cell");
    std::vector<double> area(cells, 0.5);
    set.set("area", Column(area));
    made.data_structure.entity_sets.push_back(set);
    Mesh mesh;
    mesh.name = "section";
    std::vector<std::int64_t> rows;
    for (std::size_t cell = 0; cell < cells; ++cell) {
        const double pi = std::acos(-1.0), first = 2 * pi * double(cell) / double(cells),
                     second = 2 * pi * double(cell + 1) / double(cells);
        mesh.positions.insert(mesh.positions.end(), {0, 0, 0, std::cos(first), std::sin(first), 0, std::cos(second),
                                                     std::sin(second), 0});
        rows.insert(rows.end(), 3, static_cast<std::int64_t>(cell));
    }
    mesh.feature_rows.emplace_back("Cell", rows);
    made.data_structure.meshes.push_back(mesh);
    return made;
}

void test_instances_written(const filesystem::path &scratch) {
    Frame frame;
    DataStructure plant("plant");
    EntitySet segments("SubOrgan", 0);
    segments.set("id", Column(std::vector<std::int64_t>{7, 8, 9}));
    plant.entity_sets.push_back(segments);
    InstanceSet sections("sections", "SubOrgan");
    sections.parts = {add_part(frame, fan(3)),                                                  // 0: a template
                      add_part(frame, Operator::dense(3, 2, {1, 0, 0.5, 0.5, 0, 1})),           // 1: dense
                      add_part(frame, Operator::csr(3, 2, {{0, 1, 2, 3}, {0, 1, 0}, {2, 3, 4}})),   // 2: csr
                      add_part(frame, Operator::solve(3, 2, {{0, 1, 2, 3}, {0, 1, 2}, {2, 4, 8}},  // 3: diag(2, 4, 8)⁻¹ R
                                                      {{0, 2, 3, 4}, {0, 1, 0, 1}, {2, 2, 4, 8}}))};
    check(sections.parts[1] == add_part(frame, Operator::dense(3, 2, {1, 0, 0.5, 0.5, 0, 1})),
          "the same part, the same key");
    sections.set("template", Column(std::vector<std::int64_t>{0, 0, 0}))
        .set("owner", Column(std::vector<std::int64_t>{7, 8, 9}))
        .set("age", Column(std::vector<double>{1, 2, 3}))
        .declare("age", Variable{"d"});
    sections.vectors.emplace_back("ends", Ragged::of({{1, 2}, {3, 4}, {5, 6}}));
    sections.vectors.emplace_back("sources", Ragged::of({{}, {10, 20, 30}, {}}));
    DerivedField potential;
    potential.name = "water_potential";
    potential.entity_set = "Cell";
    potential.input = "ends";
    potential.terms = 2;
    potential.operators = {1, NO_ID, 2, 1, 3, NO_ID};
    potential.weights = {1, 0, 0.5, 0.5, 2, 0};
    potential.offsets = {std::string("sources"), std::nullopt};
    potential.variable.unit = "MPa";
    potential.variable.role = "derived";
    sections.derived.push_back(potential);
    plant.instance_sets.push_back(sections);
    frame.data_structures.push_back(plant);
    const std::vector<std::vector<double>> expected = {
        {1, 1.5, 2},                                                  // dense · (1, 2)
        {0.5 * (2 * 3 + 10) + 0.5 * 3, 0.5 * (3 * 4 + 20) + 0.5 * 3.5, 0.5 * (4 * 3 + 30) + 0.5 * 4},
        {2 * (2 * 5 + 2 * 6) / 2, 2 * (4 * 5) / 4, 2 * (8 * 6) / 8}};  // diag(2, 4, 8)⁻¹ R (5, 6), weighed by 2
    check(evaluate(frame, "water_potential") == expected, "evaluated from the parts added");
    check(evaluate(frame, "water_potential", "plant", "sections", {2}) == std::vector<std::vector<double>>{expected[2]},
          "evaluated for some instances");
    filesystem::remove_all(scratch);
    const auto index_path = write_sequence(scratch.string(), {frame});
    check(filesystem::exists(scratch / "parts" / (sections.parts[0] + ".glb")), "its parts written under parts/");
    const auto index = read_index(index_path);
    check(index.parts.size() == 4, "the index lists its parts");
    const auto again = read_frame(index.frames[0].path);
    check(evaluate(again, "water_potential") == expected, "written and read: evaluated the same");
    const auto &read_sections = again.data_structure("plant").instance_set("sections");
    check(read_sections.owners == std::optional<std::string>("SubOrgan") && read_sections.count() == 3 &&
              read_sections.vector("sources").counts == std::vector<std::int64_t>{0, 3, 0} &&
              !read_sections.has_column("ends__count") && read_sections.variables.at("age").unit == "d",
          "written and read: the instance set");
    const auto embedded = from_bytes(to_bytes(frame, true));
    check(embedded.part_bytes.size() == 4 && evaluate(embedded, "water_potential") == expected, "embedded parts");
    for (const auto &compression : {"stored", "deflate", "lzma"}) {
        const auto archive = (scratch / (std::string("run_") + compression + ".fspm.zip")).string();
        pack_archive(scratch.string(), archive, compression);
        const auto packed = read_index(archive);
        check(packed.parts.size() == 4 && evaluate(read_frame(packed.frames[0].path), "water_potential") == expected,
              std::string("packed, read from the archive: ") + compression);
    }
    filesystem::remove_all(scratch / "parts");
    const auto without_parts = read_frame(index.frames[0].path);
    bool missing = false;
    try {
        evaluate(without_parts, "water_potential");
    } catch (const MissingPartError &error) {
        missing = error.key.size() == 64 && std::string(error.what()).find(error.key) != std::string::npos;
    }
    check(missing, "a missing part: an error naming its key");
    filesystem::remove_all(scratch);
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
        {"partial frame", test_partial_frame}, {"instances", [&] { test_instances(conformance); }},
        {"instances written", [&] { test_instances_written(filesystem::temp_directory_path() / "encoding3d_tests_instances"); }}};
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
