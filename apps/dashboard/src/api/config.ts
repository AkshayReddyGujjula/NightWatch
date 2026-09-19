/**
 * Shared control-API configuration.
 *
 * The operator token is entered at runtime (plan §15) and never lives in the
 * static bundle. `baseUrl` is what the deployed `control_asgi` origin resolves
 * to for the dashboard; an empty string means same origin.
 */

export interface ControlApiConfig {
  baseUrl: string;
  token: string;
}
