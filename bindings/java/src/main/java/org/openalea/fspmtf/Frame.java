package org.openalea.fspmtf;

import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * A scene at one time step (time in timeUnit, step), or a parameter set. unknown: the content of a read file this
 * library does not interpret (other root extensions, the root's extras), written back as it was.
 */
public final class Frame {
    public final List<DataStructure> dataStructures = new ArrayList<>();
    public final List<Mapping> mappings = new ArrayList<>();
    public double time = 0.0;
    public String timeUnit = "d";
    public long step = 0;
    public ObjectNode writer = JsonNodeFactory.instance.objectNode();
    public String vocabularyVersion;
    /** Set for a partial frame, a coupling session's message. */
    public Update update;
    public ObjectNode unknown = JsonNodeFactory.instance.objectNode();

    public DataStructure dataStructure(String id) {
        for (DataStructure dataStructure : dataStructures) if (dataStructure.id.equals(id)) return dataStructure;
        throw new FspmTfException("the frame has no data structure '" + id + "'");
    }
}
