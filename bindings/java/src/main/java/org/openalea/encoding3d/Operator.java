package org.openalea.encoding3d;

/**
 * A linear operator of derived fields (a shared part, specification §12.1), rows × columns: {@code format} "dense"
 * ({@code values}, row by row), "csr" ({@code sparse}) or "solve" (S⁻¹ R, S {@code system}, rows × rows, R
 * {@code rightHandSide}, rows × columns, solved when evaluated).
 */
public final class Operator implements Part {
    public final String format;
    public final int rows;
    public final int columns;
    public final double[] values;
    public final SparseMatrix sparse;
    public final SparseMatrix system;
    public final SparseMatrix rightHandSide;

    private Operator(String format, int rows, int columns, double[] values, SparseMatrix sparse, SparseMatrix system,
                     SparseMatrix rightHandSide) {
        this.format = format;
        this.rows = rows;
        this.columns = columns;
        this.values = values;
        this.sparse = sparse;
        this.system = system;
        this.rightHandSide = rightHandSide;
    }

    public static Operator dense(int rows, int columns, double[] rowByRow) {
        if (rowByRow.length != rows * columns) throw new Encoding3dException("a dense operator holds rows × columns values");
        return new Operator("dense", rows, columns, rowByRow, null, null, null);
    }

    public static Operator csr(int rows, int columns, SparseMatrix matrix) {
        if (matrix.indptr().length != rows + 1) throw new Encoding3dException("a csr operator's indptr holds rows + 1 values");
        return new Operator("csr", rows, columns, null, matrix, null, null);
    }

    public static Operator solve(int rows, int columns, SparseMatrix system, SparseMatrix rightHandSide) {
        if (system.indptr().length != rows + 1 || rightHandSide.indptr().length != rows + 1)
            throw new Encoding3dException("a solve operator's system and right-hand side have rows + 1 indptr values");
        return new Operator("solve", rows, columns, null, null, system, rightHandSide);
    }
}
