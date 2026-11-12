package org.openalea.encoding3d.coupling;

import org.openalea.encoding3d.Frame;

/**
 * A turn: step (0: the initial state, phase "init"), the time it starts from and the time it reaches, and its frame,
 * the participant's inputs (frame.update.removed: the entities removed since its last turn).
 */
public record Turn(long step, String phase, double time, double until, Frame frame) {}
