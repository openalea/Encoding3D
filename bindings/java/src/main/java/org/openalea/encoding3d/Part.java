package org.openalea.encoding3d;

/** A shared part (specification §12.1): a {@link Template} or an {@link Operator}, found by its key. */
public sealed interface Part permits Template, Operator {}
