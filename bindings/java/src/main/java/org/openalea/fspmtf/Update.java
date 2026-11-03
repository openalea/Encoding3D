package org.openalea.fspmtf;

import java.util.Map;
import java.util.TreeMap;

/**
 * What makes a frame partial: a coupling session's message (specification §11). participant: its sender
 * ("coordinator" for a turn's inputs); its tables hold some rows and columns only. removed: "data structure/entity set"
 * keys (see {@link #key}) to the ids of the entities removed, sorted by key.
 */
public final class Update {
    public String participant;
    public final Map<String, long[]> removed = new TreeMap<>();

    public Update(String participant) {
        this.participant = participant;
    }

    /** The key of an entity set in {@link #removed}. */
    public static String key(String dataStructure, String entitySet) {
        return dataStructure + "/" + entitySet;
    }
}
