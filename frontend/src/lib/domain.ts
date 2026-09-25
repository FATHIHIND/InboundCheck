/**
 * Domain normalization utility for InboundCheck.
 * Strips protocol, port, userinfo, path, query, hash, and leading 'www.'
 * to provide a clean RFC 1035 apex domain for scanning.
 */
export function normalizeDomainInput(raw: string): string {
  let d = (raw || "").trim();
  if (!d) return "";
  // Strip protocol
  d = d.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, "");
  // Strip credentials
  if (d.includes("@")) {
    d = d.split("@").pop() || "";
  }
  // Strip path, query, hash
  d = d.split("/")[0].split("?")[0].split("#")[0];
  // Strip port
  d = d.split(":")[0];
  // Strip leading www.
  if (d.toLowerCase().startsWith("www.")) {
    d = d.substring(4);
  }
  // Strip trailing dots
  d = d.replace(/\.+$/, "");
  return d.toLowerCase().trim();
}
