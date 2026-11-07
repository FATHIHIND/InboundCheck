import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { resolveStripeRedirectUrl } from "../src/lib/stripe-redirect";

describe("FE-8 Stripe redirect allow-list", () => {
  it("accepts Stripe hosted Checkout and Billing Portal URLs", () => {
    assert.equal(
      resolveStripeRedirectUrl("https://checkout.stripe.com/c/pay/cs_test_123#fid"),
      "https://checkout.stripe.com/c/pay/cs_test_123#fid"
    );
    assert.equal(
      resolveStripeRedirectUrl("https://billing.stripe.com/p/session/test_abc"),
      "https://billing.stripe.com/p/session/test_abc"
    );
  });

  it("rejects every other destination", () => {
    for (const value of [
      undefined,
      null,
      42,
      "",
      "/dashboard/billing",
      "//checkout.stripe.com/c/pay/x",
      "http://checkout.stripe.com/c/pay/x",
      "https://checkout.stripe.com.evil.test/c/pay/x",
      "https://evil.test/?u=https://checkout.stripe.com",
      "https://user:pass@checkout.stripe.com/c/pay/x",
      "https://checkout.stripe.com:8443/c/pay/x",
      "https://dashboard.stripe.com/login",
      "javascript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
    ]) {
      assert.equal(resolveStripeRedirectUrl(value), null, String(value));
    }
  });
});
