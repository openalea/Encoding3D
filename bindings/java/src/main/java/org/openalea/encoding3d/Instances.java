package org.openalea.encoding3d;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Derived fields rebuilt for each instance from its vectors and the shared operators (specification §12.3). */
public final class Instances {
    private Instances() {}

    /**
     * The derived field {@code field} evaluated for the instances at {@code rows} (all when null) of the instance set
     * holding it (in {@code dataStructure} and named {@code instanceSet} when not null, if several have one of that
     * name): one array each, on the rows of the field's entity set in the instance's template, Σ_k w_k (A_k v + b_k)
     * over its terms whose operator is not NO_ID; NaN for an instance without any. Its parts are found through the
     * frame ({@link Parts#part}).
     */
    public static List<double[]> evaluate(Frame frame, String field, String dataStructure, String instanceSet, int[] rows) {
        InstanceSet found = null;
        for (DataStructure candidate : frame.dataStructures) {
            if (dataStructure != null && !candidate.id.equals(dataStructure)) continue;
            for (InstanceSet set : candidate.instanceSets) {
                if (instanceSet != null && !set.name.equals(instanceSet)) continue;
                if (set.derived.stream().noneMatch(derived -> derived.name.equals(field))) continue;
                if (found != null)
                    throw new Encoding3dException("several instance sets with the derived field '" + field
                            + "': name the data structure or the instance set");
                found = set;
            }
        }
        if (found == null) throw new Encoding3dException("the frame has no instance set with the derived field '" + field + "'");
        final InstanceSet holder = found;
        DerivedField derived = holder.derivedField(field);
        long[] templates = holder.column("template").longs();
        Ragged input = holder.vector(derived.input);
        int[] inputOffsets = input.offsets();
        int[] chosen = rows;
        if (chosen == null) {
            chosen = new int[holder.count()];
            for (int row = 0; row < chosen.length; row++) chosen[row] = row;
        }
        Map<Long, Part> decoded = new HashMap<>();
        Map<Long, Factorisation> factorisations = new HashMap<>();
        List<double[]> out = new ArrayList<>();
        for (int row : chosen) {
            if (row < 0 || row >= holder.count())
                throw new Encoding3dException("instance row " + row + " outside '" + holder.name + "'");
            if (!(partAt(frame, holder, templates[row], decoded) instanceof Template template))
                throw new Encoding3dException("'" + holder.name + "': part " + templates[row] + " is not a template");
            int size = template.entitySet(derived.entitySet).rowCount();
            double[] result = new double[size];
            Arrays.fill(result, Double.NaN);
            double[] vector = Arrays.copyOfRange(input.values, inputOffsets[row], inputOffsets[row + 1]);
            boolean started = false;
            for (int term = 0; term < derived.terms; term++) {
                long operatorIndex = derived.operatorOf(row, term);
                if (operatorIndex == EntitySet.NO_ID) continue;
                if (!(partAt(frame, holder, operatorIndex, decoded) instanceof Operator operator))
                    throw new Encoding3dException("'" + holder.name + "': part " + operatorIndex + " is not an operator");
                if (vector.length != operator.columns)
                    throw new Encoding3dException("'" + holder.name + "' instance " + row + ": " + vector.length + " values of '"
                            + derived.input + "', its operator takes " + operator.columns);
                if (operator.rows != size)
                    throw new Encoding3dException("'" + holder.name + "' instance " + row + ": operator " + operatorIndex + " has "
                            + operator.rows + " rows, its template's '" + derived.entitySet + "' " + size);
                double weight = derived.weightOf(row, term);
                double[] values = apply(operator, vector, factorisations.computeIfAbsent(operatorIndex,
                        index -> operator.format.equals("solve") ? new Factorisation(operator.system, operator.rows) : null));
                for (int item = 0; item < size; item++) values[item] *= weight;
                String offsetName = derived.offsets[term];
                if (offsetName != null) {
                    double[] offset = holder.vector(offsetName).at(row);
                    if (offset.length != 0) {
                        if (offset.length != size)
                            throw new Encoding3dException("'" + holder.name + "' instance " + row + ": offset '" + offsetName
                                    + "' has " + offset.length + " values, " + size + " expected");
                        for (int item = 0; item < size; item++) values[item] += weight * offset[item];
                    }
                }
                for (int item = 0; item < size; item++) result[item] = started ? result[item] + values[item] : values[item];
                started = true;
            }
            out.add(result);
        }
        return out;
    }

    public static List<double[]> evaluate(Frame frame, String field) {
        return evaluate(frame, field, null, null, null);
    }

    private static Part partAt(Frame frame, InstanceSet holder, long index, Map<Long, Part> decoded) {
        if (index < 0 || index >= holder.parts.size())
            throw new Encoding3dException("'" + holder.name + "': part " + index + " outside its parts");
        return decoded.computeIfAbsent(index, at -> Parts.part(frame, holder.parts.get((int) (long) at)));
    }

    private static double[] sparseProduct(SparseMatrix matrix, int rows, double[] vector) {
        double[] product = new double[rows];
        for (int row = 0; row < rows; row++)
            for (long entry = matrix.indptr()[row]; entry < matrix.indptr()[row + 1]; entry++)
                product[row] += matrix.values()[(int) entry] * vector[(int) matrix.indices()[(int) entry]];
        return product;
    }

    private static double[] apply(Operator operator, double[] vector, Factorisation factorisation) {
        return switch (operator.format) {
            case "dense" -> {
                double[] product = new double[operator.rows];
                for (int row = 0; row < operator.rows; row++)
                    for (int column = 0; column < operator.columns; column++)
                        product[row] += operator.values[row * operator.columns + column] * vector[column];
                yield product;
            }
            case "csr" -> sparseProduct(operator.sparse, operator.rows, vector);
            default -> factorisation.solve(sparseProduct(operator.rightHandSide, operator.rows, vector));
        };
    }

    /** A dense LU factorisation with partial pivoting of a square system, solved for many right-hand sides. */
    private static final class Factorisation {
        final int size;
        final double[] lowerUpper;
        final int[] pivots;

        Factorisation(SparseMatrix system, int rows) {
            size = rows;
            lowerUpper = new double[rows * rows];
            pivots = new int[rows];
            for (int row = 0; row < rows; row++)
                for (long entry = system.indptr()[row]; entry < system.indptr()[row + 1]; entry++)
                    lowerUpper[row * rows + (int) system.indices()[(int) entry]] += system.values()[(int) entry];
            for (int column = 0; column < rows; column++) {
                int pivot = column;
                for (int row = column + 1; row < rows; row++)
                    if (Math.abs(lowerUpper[row * rows + column]) > Math.abs(lowerUpper[pivot * rows + column])) pivot = row;
                if (lowerUpper[pivot * rows + column] == 0.0) throw new Encoding3dException("a solve operator's system is singular");
                pivots[column] = pivot;
                if (pivot != column)
                    for (int item = 0; item < rows; item++) {
                        double swapped = lowerUpper[pivot * rows + item];
                        lowerUpper[pivot * rows + item] = lowerUpper[column * rows + item];
                        lowerUpper[column * rows + item] = swapped;
                    }
                for (int row = column + 1; row < rows; row++) {
                    double factor = lowerUpper[row * rows + column] / lowerUpper[column * rows + column];
                    lowerUpper[row * rows + column] = factor;
                    for (int item = column + 1; item < rows; item++) lowerUpper[row * rows + item] -= factor * lowerUpper[column * rows + item];
                }
            }
        }

        double[] solve(double[] right) {
            for (int column = 0; column < size; column++) {
                double swapped = right[column];
                right[column] = right[pivots[column]];
                right[pivots[column]] = swapped;
            }
            for (int row = 0; row < size; row++)
                for (int item = 0; item < row; item++) right[row] -= lowerUpper[row * size + item] * right[item];
            for (int row = size - 1; row >= 0; row--) {
                for (int item = row + 1; item < size; item++) right[row] -= lowerUpper[row * size + item] * right[item];
                right[row] /= lowerUpper[row * size + row];
            }
            return right;
        }
    }
}
