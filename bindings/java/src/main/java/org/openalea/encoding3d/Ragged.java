package org.openalea.encoding3d;

import java.util.Arrays;
import java.util.List;

/**
 * One array of numbers per instance, of each instance's own length (specification §12.2): {@code values} holds them one
 * after the other, in the instances' order; {@code counts} each one's length.
 */
public final class Ragged {
    public final double[] values;
    public final long[] counts;

    public Ragged(double[] values, long[] counts) {
        this.values = values;
        this.counts = counts;
    }

    /** The ragged array of one vector per instance. */
    public static Ragged of(List<double[]> vectors) {
        long[] counts = new long[vectors.size()];
        int total = 0;
        for (int row = 0; row < counts.length; row++) {
            counts[row] = vectors.get(row).length;
            total += vectors.get(row).length;
        }
        double[] values = new double[total];
        int start = 0;
        for (double[] vector : vectors) {
            System.arraycopy(vector, 0, values, start, vector.length);
            start += vector.length;
        }
        return new Ragged(values, counts);
    }

    /** The number of instances. */
    public int size() {
        return counts.length;
    }

    /** Where each instance's values start in {@code values} (one more than size(): the end). */
    public int[] offsets() {
        int[] starts = new int[counts.length + 1];
        for (int row = 0; row < counts.length; row++) {
            if (counts[row] < 0) throw new Encoding3dException("a ragged array's counts are not negative");
            starts[row + 1] = starts[row] + (int) counts[row];
        }
        if (starts[counts.length] != values.length)
            throw new Encoding3dException("a ragged array's counts sum to " + starts[counts.length] + ", it holds "
                    + values.length + " values");
        return starts;
    }

    /** The values of instance {@code row}. */
    public double[] at(int row) {
        int[] starts = offsets();
        return Arrays.copyOfRange(values, starts[row], starts[row + 1]);
    }
}
