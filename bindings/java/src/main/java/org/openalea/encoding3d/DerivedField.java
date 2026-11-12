package org.openalea.encoding3d;

/**
 * A derived field (specification §12.3): a field on the entity set {@code entitySet} of the instances' templates,
 * rebuilt for each instance i from its vector {@code input} v as f = Σ_k w_ik (A_ik v + b_ik) over its {@code terms} K
 * terms. {@code operators} and {@code weights}: K per instance, row by row (instance i's term k at i * K + k); an operator
 * is an index in the instance set's parts, NO_ID for none. {@code offsets}: K names of vectors, or null, each term's
 * offset b.
 */
public final class DerivedField {
    public String name;
    public String entitySet;
    public String input;
    public int terms = 1;
    public long[] operators;
    public double[] weights;
    public String[] offsets;
    public Variable variable = new Variable();

    public DerivedField(String name, String entitySet, String input, int terms, long[] operators, double[] weights,
                        String[] offsets, Variable variable) {
        this.name = name;
        this.entitySet = entitySet;
        this.input = input;
        this.terms = terms;
        this.operators = operators;
        this.weights = weights;
        this.offsets = offsets == null ? new String[terms] : offsets;
        this.variable = variable;
    }

    public long operatorOf(int row, int term) {
        return operators[row * terms + term];
    }

    public double weightOf(int row, int term) {
        return weights[row * terms + term];
    }
}
