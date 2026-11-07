/**
 * Stripe redirect allow-list (audit finding FE-8).
 *
 * Checkout and Customer Portal URLs come back from our backend, but the browser must
 * never be sent to an arbitrary destination if that response is tampered with or
 * misconfigured. Only Stripe's hosted Checkout and Billing Portal origins are allowed.
 */
export const ALLOWED_STRIPE_REDIRECT_ORIGINS: readonly string[] = [
  "https://checkout.stripe.com",
  "https://billing.stripe.com",
];

/**
 * Returns the normalized absolute URL when it points at an allowed Stripe origin,
 * otherwise null (relative paths, other hosts, non-https schemes, embedded credentials).
 */
export function resolveStripeRedirectUrl(candidate: unknown): string | null {
  if (typeof candidate !== "string" || candidate.trim() === "") return null;
  let url: URL;
  try {
    url = new URL(candidate.trim());
  } catch {
    return null;
  }
  if (url.username || url.password) return null;
  return ALLOWED_STRIPE_REDIRECT_ORIGINS.includes(url.origin) ? url.href : null;
}
