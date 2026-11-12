package org.openalea.encoding3d;

/**
 * The type of a column's values. Integers are held in the Java array of their width (UINT8 in a byte[], UINT64 in a
 * long[]), their bits as stored; booleans in a boolean[]; text, labels and edge types in a String[].
 */
public enum ComponentType {
    INT8(1, "int8"), UINT8(1, "uint8"), INT16(2, "int16"), UINT16(2, "uint16"), INT32(4, "int32"),
    UINT32(4, "uint32"), INT64(8, "int64"), UINT64(8, "uint64"), FLOAT32(4, "float32"), FLOAT64(8, "float64"),
    BOOLEAN(0, "bool"), STRING(0, "string");

    /** Bytes per value (0: booleans and text). */
    public final int size;
    /** The type's name in the conformance files' expected values (numpy's, or "string"). */
    public final String dtype;

    ComponentType(int size, String dtype) {
        this.size = size;
        this.dtype = dtype;
    }

    public boolean isNumber() {
        return size > 0;
    }

    public boolean isFloat() {
        return this == FLOAT32 || this == FLOAT64;
    }

    public boolean isUnsigned() {
        return this == UINT8 || this == UINT16 || this == UINT32 || this == UINT64;
    }
}
