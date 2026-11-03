package org.openalea.fspmtf.coupling;

import com.fasterxml.jackson.databind.ObjectMapper;

/** The JSON mapper of the session's headers. */
final class Json {
    static final ObjectMapper MAPPER = new ObjectMapper();

    private Json() {}
}
