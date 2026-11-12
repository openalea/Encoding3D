// Archives (specification §8.2): a sequence packed into one .fspm.zip file, a ZIP archive (ZIP64 when it needs to be)
// whose members are the folder's files, each compressed alone (stored, deflate or lzma). A file inside an archive is
// named "<archive>.fspm.zip/<member>"; read_file_bytes and file_exists read such paths as they read a folder's files.
// ZIP through minizip-ng (its ZIP64 records, deflate with zlib, lzma with liblzma).
#include "encoding3d/encoding3d.hpp"

#include <filesystem>
#include <fstream>
#include <iterator>
#include <optional>
#include <set>

#include <mz.h>
#include <mz_strm.h>
#include <mz_zip.h>
#include <mz_zip_rw.h>

namespace encoding3d {

namespace {

namespace filesystem = std::filesystem;

/// (archive, member) when `path` is a file inside an archive ("x.fspm.zip/frame_000000.glb"), or an archive itself
/// (its index, "scene.fspm.json"); none otherwise.
std::optional<std::pair<std::string, std::string>> split_archive(const std::string &path) {
    std::string normalised = path;
    for (auto &character : normalised)
        if (character == '\\') character = '/';
    const std::string suffix = ARCHIVE_SUFFIX;
    if (normalised.size() >= suffix.size() &&
        normalised.compare(normalised.size() - suffix.size(), suffix.size(), suffix) == 0 &&
        filesystem::is_regular_file(path))
        return std::make_pair(path, std::string(INDEX_FILE));
    for (auto position = normalised.find(suffix + "/"); position != std::string::npos;
         position = normalised.find(suffix + "/", position + 1)) {
        const std::string archive = path.substr(0, position + suffix.size());
        if (filesystem::is_regular_file(archive)) {
            std::string member;
            for (std::size_t start = position + suffix.size() + 1; start <= normalised.size();) {
                const auto end = std::min(normalised.find('/', start), normalised.size());
                const std::string part = normalised.substr(start, end - start);
                if (part == "..") throw Error("member '" + normalised.substr(position + suffix.size() + 1) +
                                              "': no '..' in an archive's paths");
                if (!part.empty() && part != ".") member += (member.empty() ? "" : "/") + part;
                start = end + 1;
            }
            return std::make_pair(archive, member);
        }
    }
    return std::nullopt;
}

/// A minizip-ng reader open on an archive, closed when it goes.
struct Reader {
    void *handle = nullptr;
    explicit Reader(const std::string &archive) : handle(mz_zip_reader_create()) {
        if (!handle) throw Error("cannot read the archive '" + archive + "'");
        if (mz_zip_reader_open_file(handle, archive.c_str()) != MZ_OK) {
            mz_zip_reader_delete(&handle);
            throw Error("'" + archive + "' is not a ZIP archive");
        }
    }
    ~Reader() {
        mz_zip_reader_close(handle);
        mz_zip_reader_delete(&handle);
    }
    Reader(const Reader &) = delete;
    Reader &operator=(const Reader &) = delete;
    bool locate(const std::string &member) { return mz_zip_reader_locate_entry(handle, member.c_str(), 0) == MZ_OK; }
};

std::vector<std::uint8_t> read_plain_file(const std::string &path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw Error("cannot read '" + path + "'");
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

/// The keys of the parts a frame file's instance sets use (its JSON chunk only).
std::set<std::string> part_keys_of(const std::string &path) {
    std::set<std::string> keys;
    const json document = unpack(read_file_bytes(path)).first;
    const auto &scene = document.at("extensions").at("FSPM_scene");
    for (const auto &data_structure : scene.value("dataStructures", json::array()))
        for (const auto &instance_set : data_structure.value("instanceSets", json::array()))
            for (const auto &key : instance_set.value("parts", json::array())) keys.insert(key.get<std::string>());
    return keys;
}

} // namespace

std::vector<std::uint8_t> read_file_bytes(const std::string &path) {
    const auto inside = split_archive(path);
    if (!inside) return read_plain_file(path);
    Reader reader(inside->first);
    if (!reader.locate(inside->second)) throw Error(inside->first + " holds no '" + inside->second + "'");
    if (mz_zip_reader_entry_open(reader.handle) != MZ_OK)
        throw Error("cannot read '" + inside->second + "' in " + inside->first + " (its compression method?)");
    mz_zip_file *information = nullptr;
    mz_zip_reader_entry_get_info(reader.handle, &information);
    std::vector<std::uint8_t> bytes;
    if (information && information->uncompressed_size > 0) bytes.reserve(static_cast<std::size_t>(information->uncompressed_size));
    std::vector<std::uint8_t> block(1 << 20);
    while (true) {
        const auto read = mz_zip_reader_entry_read(reader.handle, block.data(), static_cast<std::int32_t>(block.size()));
        if (read < 0) {
            mz_zip_reader_entry_close(reader.handle);
            throw Error("cannot read '" + inside->second + "' in " + inside->first + ": error " + std::to_string(read));
        }
        if (read == 0) break;
        bytes.insert(bytes.end(), block.begin(), block.begin() + read);
    }
    if (mz_zip_reader_entry_close(reader.handle) != MZ_OK)          // its CRC-32 checked
        throw Error("'" + inside->second + "' in " + inside->first + " is corrupt (its CRC-32 differs)");
    return bytes;
}

bool file_exists(const std::string &path) {
    const auto inside = split_archive(path);
    if (!inside) return filesystem::exists(path);
    Reader reader(inside->first);
    return reader.locate(inside->second);
}

std::string pack_archive(const std::string &folder, const std::string &path, const std::string &compression) {
    std::uint16_t method;
    if (compression == "deflate") method = MZ_COMPRESS_METHOD_DEFLATE;
    else if (compression == "stored") method = MZ_COMPRESS_METHOD_STORE;
    else if (compression == "lzma") method = MZ_COMPRESS_METHOD_LZMA;
    else throw Error("compression '" + compression + "': deflate, lzma or stored");
    const std::string suffix = ARCHIVE_SUFFIX;
    if (path.size() < suffix.size() || path.compare(path.size() - suffix.size(), suffix.size(), suffix) != 0)
        throw Error("'" + path + "': an archive's name ends in " + suffix);
    const filesystem::path index_path = filesystem::is_directory(folder) ? filesystem::path(folder) / INDEX_FILE
                                                                         : filesystem::path(folder);
    const auto base = filesystem::absolute(index_path).parent_path();
    const Index index = read_index(index_path.string());
    std::vector<std::string> members = {INDEX_FILE};
    if (filesystem::exists(base / "views.json")) members.push_back("views.json");
    std::set<std::string> keys(index.parts.begin(), index.parts.end());
    for (const auto &entry : index.frames) {
        members.push_back(entry.file);
        const auto used = part_keys_of(entry.path);
        keys.insert(used.begin(), used.end());
    }
    for (const auto &key : keys) members.push_back("parts/" + key + ".glb");
    for (const auto &member : members)
        if (!filesystem::exists(base / member)) {
            if (member.rfind("parts/", 0) == 0)
                throw MissingPartError(member.substr(6, member.size() - 10), {(base / member).string()});
            throw Error((base / member).string() + " does not exist");
        }
    const std::string temporary = path + ".part";
    void *writer = mz_zip_writer_create();
    if (!writer) throw Error("cannot write '" + path + "'");
    mz_zip_writer_set_compress_method(writer, method);
    if (mz_zip_writer_open_file(writer, temporary.c_str(), 0, 0) != MZ_OK) {
        mz_zip_writer_delete(&writer);
        throw Error("cannot write '" + temporary + "'");
    }
    std::int32_t status = MZ_OK;
    for (const auto &member : members) {
        status = mz_zip_writer_add_file(writer, (base / member).string().c_str(), member.c_str());
        if (status != MZ_OK) break;
    }
    const auto closed = mz_zip_writer_close(writer);
    mz_zip_writer_delete(&writer);
    if (status != MZ_OK || closed != MZ_OK) {
        filesystem::remove(temporary);
        throw Error("cannot write '" + path + "': error " + std::to_string(status != MZ_OK ? status : closed));
    }
    filesystem::rename(temporary, path);
    return path;
}

} // namespace encoding3d
