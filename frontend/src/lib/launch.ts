/**
 * What the alpha access form reports back while it is still in charge. An
 * accepted code is reported separately as "approved", which hands the screen
 * to the moon intro (components/moon-intro).
 */
export type GatePhase = "idle" | "validating" | "denied";
