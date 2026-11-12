package org.openalea.encoding3d;

import java.util.List;

/** A shared part a frame refers to is nowhere it may be (specification §12.1): its key, and where it was looked for. */
public final class MissingPartException extends Encoding3dException {
    private static final long serialVersionUID = 1L;
    public final String key;
    public final List<String> looked;

    public MissingPartException(String key, List<String> looked) {
        super("the shared part " + key + " is missing (looked for " + (looked.isEmpty() ? "-" : String.join(", ", looked))
                + "): copy the sequence's parts/ folder with its frames, or write the frame with its parts embedded");
        this.key = key;
        this.looked = List.copyOf(looked);
    }
}
