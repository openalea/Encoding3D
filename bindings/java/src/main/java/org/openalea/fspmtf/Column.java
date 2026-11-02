package org.openalea.fspmtf;

import java.lang.reflect.Array;
import java.util.Arrays;

/**
 * A column: its values (a Java array, see {@link ComponentType}), {@code width} per row (1: one value per row; 2 or more:
 * a fixed-size vector per row, row after row), and which rows are missing ({@code missing}, one flag per row, null when
 * none is; NaN in a float column).
 */
public final class Column {
    public final ComponentType type;
    public final Object values;
    public final int width;
    public boolean[] missing;

    public Column(ComponentType type, Object values, int width) {
        if (!values.getClass().isArray()) throw new FspmTfException("a column's values are an array");
        Class<?> expected = switch (type) {
            case INT8, UINT8 -> byte.class;
            case INT16, UINT16 -> short.class;
            case INT32, UINT32 -> int.class;
            case INT64, UINT64 -> long.class;
            case FLOAT32 -> float.class;
            case FLOAT64 -> double.class;
            case BOOLEAN -> boolean.class;
            case STRING -> String.class;
        };
        if (values.getClass().getComponentType() != expected)
            throw new FspmTfException("a " + type + " column holds " + expected.getSimpleName() + " values");
        if (width < 1) throw new FspmTfException("a column's width is at least 1");
        this.type = type;
        this.values = values;
        this.width = width;
    }

    public Column(ComponentType type, Object values) {
        this(type, values, 1);
    }

    public static Column of(long... values) { return new Column(ComponentType.INT64, values); }
    public static Column of(int... values) { return new Column(ComponentType.INT32, values); }
    public static Column of(double... values) { return new Column(ComponentType.FLOAT64, values); }
    public static Column of(float... values) { return new Column(ComponentType.FLOAT32, values); }
    public static Column of(boolean... values) { return new Column(ComponentType.BOOLEAN, values); }
    public static Column of(String... values) { return new Column(ComponentType.STRING, values); }
    /** A vector column: {@code width} values per row, row after row. */
    public static Column vectors(int width, double... values) { return new Column(ComponentType.FLOAT64, values, width); }

    /** Marks rows as missing (one flag per row); returns the column, for chaining. */
    public Column withMissing(boolean... rows) {
        if (rows.length != rows()) throw new FspmTfException("one missing flag per row");
        missing = rows;
        return this;
    }

    public boolean isMissing(int row) {
        return missing != null && missing[row];
    }

    public boolean hasMissing() {
        if (missing != null) for (boolean flag : missing) if (flag) return true;
        return false;
    }

    /** The number of values (rows × width). */
    public int size() {
        return Array.getLength(values);
    }

    public int rows() {
        return size() / width;
    }

    public long[] longs() { return (long[]) values; }
    public int[] ints() { return (int[]) values; }
    public double[] doubles() { return (double[]) values; }
    public float[] floats() { return (float[]) values; }
    public boolean[] booleans() { return (boolean[]) values; }
    public String[] strings() { return (String[]) values; }

    /** The value at {@code index} as a double (unsigned integers read as unsigned). */
    public double doubleAt(int index) {
        return switch (type) {
            case INT8 -> ((byte[]) values)[index];
            case UINT8 -> Byte.toUnsignedInt(((byte[]) values)[index]);
            case INT16 -> ((short[]) values)[index];
            case UINT16 -> Short.toUnsignedInt(((short[]) values)[index]);
            case INT32 -> ((int[]) values)[index];
            case UINT32 -> Integer.toUnsignedLong(((int[]) values)[index]);
            case INT64 -> ((long[]) values)[index];
            case UINT64 -> Double.parseDouble(Long.toUnsignedString(((long[]) values)[index]));
            case FLOAT32 -> ((float[]) values)[index];
            case FLOAT64 -> ((double[]) values)[index];
            default -> throw new FspmTfException("a " + type + " column has no numbers");
        };
    }

    @Override
    public boolean equals(Object other) {
        if (!(other instanceof Column column)) return false;
        return type == column.type && width == column.width && Arrays.deepEquals(new Object[] {values}, new Object[] {column.values})
                && hasMissing() == column.hasMissing() && (!hasMissing() || Arrays.equals(missing, column.missing));
    }

    @Override
    public int hashCode() {
        return type.hashCode() * 31 + width;
    }
}
