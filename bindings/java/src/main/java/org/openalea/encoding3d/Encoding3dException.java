package org.openalea.encoding3d;

/** What the specification forbids, or a file that is not encoding3d. */
public class Encoding3dException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    public Encoding3dException(String message) {
        super(message);
    }

    public Encoding3dException(String message, Throwable cause) {
        super(message, cause);
    }
}
