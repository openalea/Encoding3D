package org.openalea.encoding3d;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * The declaration of a variable (a column): its unit (a UCUM code), its standard name in the vocabulary, its kind
 * (extensive, intensive, ...: how it maps between scales and grids), its role and its provenance.
 */
public final class Variable {
    public String unit = "1";
    public String standardName;
    public String kind;
    public String role = "state";
    public String description;
    public Double minimum;
    public Double maximum;
    public List<String> references = new ArrayList<>();
    public List<String> doi = new ArrayList<>();
    /** A text column of dates or times: "date", "date-time" or "time" (ISO 8601). */
    public String format;

    public Variable() {}

    public Variable(String unit, String standardName, String kind, String role) {
        this.unit = unit;
        this.standardName = standardName;
        this.kind = kind;
        this.role = role;
    }

    @Override
    public boolean equals(Object other) {
        if (!(other instanceof Variable variable)) return false;
        return Objects.equals(unit, variable.unit) && Objects.equals(standardName, variable.standardName)
                && Objects.equals(kind, variable.kind) && Objects.equals(role, variable.role)
                && Objects.equals(description, variable.description) && Objects.equals(minimum, variable.minimum)
                && Objects.equals(maximum, variable.maximum) && references.equals(variable.references)
                && doi.equals(variable.doi) && Objects.equals(format, variable.format);
    }

    @Override
    public int hashCode() {
        return Objects.hash(unit, standardName, kind, role);
    }
}
