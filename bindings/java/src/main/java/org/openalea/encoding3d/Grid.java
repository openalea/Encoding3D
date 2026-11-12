package org.openalea.encoding3d;

import java.util.List;

/**
 * A grid's layout. Regular: shape cells of size spacing from origin, along axes, periodic per axis, z pointing up or
 * down (zUp). Adaptive: the same for its base level, refined up to maxLevel, its leaf cells (an entity set with level
 * and index columns) explicit. cells: the name of the cells' entity set.
 */
public final class Grid {
    public String kind = "regular";
    public long[] shape = {};
    public double[] origin = {};
    public double[] spacing = {};
    public List<String> axes = List.of("x", "y", "z");
    public boolean[] periodic = {};
    public boolean zUp = true;
    public long maxLevel = 0;
    public String cells = "Cell";
}
