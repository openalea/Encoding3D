"""
Coupling platforms through fspm-TF (specification §11): a session between participants, each a platform's model
in its own process (or a recorded sequence), coordinated by a coordinator that holds the shared structure.

- messages: the declarations, links and errors (Declaration, EntitySetSpec, VariableSpec, Link, CouplingError);
- resolution: each input's provider and the stages (resolve, stages);
- store: the session's structure, the updates merged into it and the inputs read from it (SessionStore);
- channels: the transports, ZeroMQ and a folder;
- participant: a platform's side (Participant, Turn);
- coordinator: the coordinator (Coordinator), launching participants and recording the session;
- replay: a recorded sequence as a participant (Replay).
"""
from openalea.fspm_tf.coupling.messages import (ID_COUNT, PROTOCOL_VERSION, CouplingError, Declaration,  # noqa: F401
                                                EntitySetSpec, Link, VariableSpec)
from openalea.fspm_tf.coupling.resolution import Coupling, resolve, stages  # noqa: F401
from openalea.fspm_tf.coupling.participant import Participant, Turn  # noqa: F401
from openalea.fspm_tf.coupling.coordinator import Coordinator, python_command  # noqa: F401
from openalea.fspm_tf.coupling.replay import Replay  # noqa: F401
