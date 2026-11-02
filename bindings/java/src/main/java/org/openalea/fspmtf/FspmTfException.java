package org.openalea.fspmtf;

/** What the specification forbids, or a file that is not fspm-TF. */
public class FspmTfException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    public FspmTfException(String message) {
        super(message);
    }

    public FspmTfException(String message, Throwable cause) {
        super(message, cause);
    }
}
