// A participant's side of a coupling session (specification §11): a platform declares what it works on, provides and
// requires, then answers each turn's inputs with its outputs, as partial frames. The coordinator is encoding3d's
// (`encoding3d couple`).
//
//     encoding3d::coupling::Participant participant(declaration);      // a JSON declaration; endpoint from the environment
//     while (auto turn = participant.next_turn()) {                  // until the coordinator stops the session
//         ... turn->frame: its entity sets, their entities, its inputs; the model from turn->time to turn->until
//         participant.send_update(frame);                            // its outputs and topology changes
//     }
//
// Transports: a folder ("files:path") always; ZeroMQ ("tcp://…", "ipc://…") when the library is built with libzmq
// (ENCODING3D_WITH_ZMQ).
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "encoding3d/model.hpp"

namespace encoding3d::coupling {

/// The version of the coupling protocol this library speaks.
inline constexpr const char *PROTOCOL_VERSION = "0.3";
/// The environment variables a participant launched by the coordinator reads: the session's endpoint, its name.
inline constexpr const char *ENDPOINT_VARIABLE = "ENCODING3D_ENDPOINT";
inline constexpr const char *PARTICIPANT_VARIABLE = "ENCODING3D_PARTICIPANT";

/// A message: its JSON header and, for turns and updates, a partial frame's GLB bytes.
struct Message {
    json header;
    std::optional<std::vector<std::uint8_t>> payload;
};

/// A participant's channel to the coordinator.
class Channel {
  public:
    virtual ~Channel() = default;
    virtual void send(const json &header, const std::vector<std::uint8_t> *payload = nullptr) = 0;
    /// The next message; throws Error after `timeout` seconds without one (none: wait).
    virtual Message receive(std::optional<double> timeout) = 0;
    /// As the session says (its welcome's keepMessages): keep the messages read, or delete them (the folder transport).
    virtual void keep_messages(bool) {}
};

/// A participant's channel to `endpoint` ("files:path", or a ZeroMQ endpoint).
std::unique_ptr<Channel> participant_channel(const std::string &endpoint, const std::string &participant);

/// Whether this library speaks ZeroMQ (built with libzmq).
bool has_zeromq();

/// A turn: step (0: the initial state, phase "init"), the time it starts from and the time it reaches, and its frame,
/// the participant's inputs (frame.update->removed: the entities removed since its last turn).
struct Turn {
    std::int64_t step = 0;
    std::string phase;
    double time = 0.0;
    double until = 0.0;
    Frame frame;
};

/// A participant in a session: joining it sends the declaration (and the links it proposes) and waits for the welcome.
/// The ids of the entities it creates are in [id_offset, id_offset + id_count).
class Participant {
  public:
    /// `declaration`: its JSON (spec/schema/coupling.schema.json); its participant name, if empty, and `endpoint`, if
    /// empty, from the environment.
    explicit Participant(json declaration, std::string endpoint = "", json links = json::array(),
                         std::optional<double> timeout = std::nullopt);
    /// The next turn, or none when the coordinator stopped the session (`stopped`: its reason).
    std::optional<Turn> next_turn();
    /// Sends the turn's outputs: per entity set, the ids and outputs of the rows sent (and the topology columns of the
    /// entities it adds or changes); in frame.update->removed, the entities it removed.
    void send_update(Frame frame);
    /// Tells the coordinator this participant cannot go on (the session stops).
    void fail(const std::string &message);

    std::string name;
    std::int64_t id_offset = 0;
    std::int64_t id_count = 0;
    json session;
    json couplings;
    std::optional<std::string> stopped;

  private:
    std::unique_ptr<Channel> channel_;
    std::optional<double> timeout_;
    std::int64_t step_ = -1;
};

} // namespace encoding3d::coupling
