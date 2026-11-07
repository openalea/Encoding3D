package org.openalea.encoding3d;

/** A matrix in compressed sparse rows: row r's entries are indices[indptr[r] .. indptr[r + 1]) and their values. */
public record SparseMatrix(long[] indptr, long[] indices, double[] values) {}
