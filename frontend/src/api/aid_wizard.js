/**
 * Disabled standalone award-session boundary.
 * No network transport, CROWN runtime dependency, credentials or writes.
 * Replace only after Jireh-specific school/role/UUID acceptance.
 */
const unavailable = () => Promise.reject(
  new Error("Standalone Jireh award setup is disabled until authorized server integration is approved.")
);

export const createAidWizardSession = unavailable;
export const configureAidWizardSession = unavailable;
export const saveAidBuckets = unavailable;
export const stageAidAwards = unavailable;
export const commitAidSetup = unavailable;
export const verifyAidSetup = unavailable;
