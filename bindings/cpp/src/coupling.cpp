// A participant's side of a coupling session: the folder transport, the participant, and the ZeroMQ transport when
// built with libzmq (FSPM_TF_WITH_ZMQ).
#include "fspm_tf/coupling.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <thread>

#include "fspm_tf/fspm_tf.hpp"

#ifdef FSPM_TF_WITH_ZMQ
#include <zmq.h>
#endif

namespace fspm_tf::coupling {

namespace {

namespace filesystem = std::filesystem;

std::vector<std::uint8_t> read_bytes(const filesystem::path &path) {
    std::ifstream file(path, std::ios::binary);
    return std::vector<std::uint8_t>((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}

void write_bytes(const filesystem::path &path, const void *data, std::size_t size) {
    std::ofstream file(path, std::ios::binary);
    file.write(static_cast<const char *>(data), static_cast<std::streamsize>(size));
}

std::string numbered(std::int64_t number) {
    std::ostringstream text;
    text << std::setw(8) << std::setfill('0') << number;
    return text.str();
}

/// A participant's folder queues: <folder>/<participant>/to_coordinator/ and to_participant/. Message n is n.json
/// (its header) and n.glb (its payload), the payload written first and the header renamed into place last.
class FolderChannel : public Channel {
  public:
    FolderChannel(const std::string &folder, const std::string &participant)
        : incoming_(filesystem::path(folder) / participant / "to_participant"),
          outgoing_(filesystem::path(folder) / participant / "to_coordinator") {
        filesystem::create_directories(incoming_);
        filesystem::create_directories(outgoing_);
    }

    void send(const json &header, const std::vector<std::uint8_t> *payload) override {
        const auto stem = outgoing_ / numbered(next_write_);
        json written = header;
        if (payload) {
            write_bytes(stem.string() + ".glb", payload->data(), payload->size());
            written["payload"] = numbered(next_write_) + ".glb";
        }
        const std::string text = written.dump();
        write_bytes(stem.string() + ".json.part", text.data(), text.size());
        filesystem::rename(stem.string() + ".json.part", stem.string() + ".json");
        ++next_write_;
    }

    Message receive(std::optional<double> timeout) override {
        const auto stem = incoming_ / numbered(next_read_);
        const auto start = std::chrono::steady_clock::now();
        while (!filesystem::exists(stem.string() + ".json")) {
            if (timeout && std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() > *timeout)
                throw Error("no message in " + std::to_string(*timeout) + " s");
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        const auto text = read_bytes(stem.string() + ".json");
        Message message{json::parse(text.begin(), text.end()), std::nullopt};
        std::vector<filesystem::path> files{stem.string() + ".json"};
        if (message.header.contains("payload")) {
            files.push_back(incoming_ / message.header["payload"].get<std::string>());
            message.payload = read_bytes(files.back());
            message.header.erase("payload");
        }
        ++next_read_;
        if (keep_) read_files_.insert(read_files_.end(), files.begin(), files.end());
        else for (const auto &path : files) filesystem::remove(path);
        return message;
    }

    void keep_messages(bool keep) override {
        if (keep) return;
        keep_ = false;
        for (const auto &path : read_files_) filesystem::remove(path);
        read_files_.clear();
    }

  private:
    filesystem::path incoming_, outgoing_;
    std::int64_t next_read_ = 0, next_write_ = 0;
    bool keep_ = true;                               // false: a message's files deleted once read
    std::vector<filesystem::path> read_files_;       // those of the messages read and kept
};

#ifdef FSPM_TF_WITH_ZMQ
/// A DEALER socket named after the participant, connected to the coordinator's ROUTER socket; a message is one or two
/// frames, its header then its payload.
class ZmqChannel : public Channel {
  public:
    ZmqChannel(const std::string &endpoint, const std::string &participant) {
        context_ = zmq_ctx_new();
        socket_ = zmq_socket(context_, ZMQ_DEALER);
        zmq_setsockopt(socket_, ZMQ_ROUTING_ID, participant.data(), participant.size());
        const int linger = 1000;
        zmq_setsockopt(socket_, ZMQ_LINGER, &linger, sizeof linger);
        if (zmq_connect(socket_, endpoint.c_str()) != 0)
            throw Error("cannot connect to " + endpoint + ": " + zmq_strerror(zmq_errno()));
    }
    ~ZmqChannel() override {
        zmq_close(socket_);
        zmq_ctx_term(context_);
    }

    void send(const json &header, const std::vector<std::uint8_t> *payload) override {
        const std::string text = header.dump();
        zmq_send(socket_, text.data(), text.size(), payload ? ZMQ_SNDMORE : 0);
        if (payload) zmq_send(socket_, payload->data(), payload->size(), 0);
    }

    Message receive(std::optional<double> timeout) override {
        zmq_pollitem_t item{socket_, 0, ZMQ_POLLIN, 0};
        if (zmq_poll(&item, 1, timeout ? static_cast<long>(*timeout * 1000) : -1) <= 0)
            throw Error("no message in " + std::to_string(timeout.value_or(0.0)) + " s");
        std::vector<std::vector<std::uint8_t>> parts;
        int more = 1;
        while (more) {
            zmq_msg_t part;
            zmq_msg_init(&part);
            zmq_msg_recv(&part, socket_, 0);
            const auto *data = static_cast<const std::uint8_t *>(zmq_msg_data(&part));
            parts.emplace_back(data, data + zmq_msg_size(&part));
            more = zmq_msg_more(&part);
            zmq_msg_close(&part);
        }
        Message message{json::parse(parts[0].begin(), parts[0].end()), std::nullopt};
        if (parts.size() > 1) message.payload = std::move(parts[1]);
        return message;
    }

  private:
    void *context_ = nullptr;
    void *socket_ = nullptr;
};
#endif

std::string environment(const char *name) {
    const char *value = std::getenv(name);
    return value ? value : "";
}

} // namespace

bool has_zeromq() {
#ifdef FSPM_TF_WITH_ZMQ
    return true;
#else
    return false;
#endif
}

std::unique_ptr<Channel> participant_channel(const std::string &endpoint, const std::string &participant) {
    if (endpoint.rfind("files:", 0) == 0) return std::make_unique<FolderChannel>(endpoint.substr(6), participant);
#ifdef FSPM_TF_WITH_ZMQ
    return std::make_unique<ZmqChannel>(endpoint, participant);
#else
    throw Error("the endpoint " + endpoint + " needs ZeroMQ: build fspm_tf with libzmq, or use a folder (files:path)");
#endif
}

Participant::Participant(json declaration, std::string endpoint, json links, std::optional<double> timeout)
    : timeout_(timeout) {
    if (endpoint.empty()) endpoint = environment(ENDPOINT_VARIABLE);
    if (endpoint.empty()) throw Error(std::string("no endpoint: give one, or set ") + ENDPOINT_VARIABLE);
    name = declaration.value("participant", std::string());
    if (name.empty()) {
        name = environment(PARTICIPANT_VARIABLE);
        declaration["participant"] = name;
    }
    channel_ = participant_channel(endpoint, name);
    channel_->send({{"type", "hello"}, {"protocol", PROTOCOL_VERSION}, {"declaration", declaration},
                    {"links", links}});
    const auto welcome = channel_->receive(timeout_);
    const auto type = welcome.header.at("type").get<std::string>();
    if (type == "stop")
        throw Error("the coordinator refused " + name + ": " + welcome.header.value("reason", std::string()));
    if (type != "welcome") throw Error("expected a welcome, got " + type);
    id_offset = welcome.header.at("idOffset").get<std::int64_t>();
    id_count = welcome.header.at("idCount").get<std::int64_t>();
    session = welcome.header.at("session");
    channel_->keep_messages(session.value("keepMessages", true));
    couplings = welcome.header.value("couplings", json::array());
}

std::optional<Turn> Participant::next_turn() {
    auto message = channel_->receive(timeout_);
    const auto type = message.header.at("type").get<std::string>();
    if (type == "stop") {
        stopped = message.header.value("reason", std::string());
        return std::nullopt;
    }
    if (type != "turn") throw Error("expected a turn, got " + type);
    step_ = message.header.at("step").get<std::int64_t>();
    return Turn{step_, message.header.at("phase").get<std::string>(), message.header.at("time").get<double>(),
                message.header.at("until").get<double>(), from_bytes(message.payload.value())};
}

void Participant::send_update(Frame frame) {
    if (!frame.update) frame.update = Update{};
    frame.update->participant = name;
    const auto bytes = to_bytes(frame);
    channel_->send({{"type", "update"}, {"step", step_}}, &bytes);
}

void Participant::fail(const std::string &message) { channel_->send({{"type", "error"}, {"message", message}}); }

} // namespace fspm_tf::coupling
