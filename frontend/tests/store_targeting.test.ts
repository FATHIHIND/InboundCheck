import { describe, it } from "node:test";
import assert from "node:assert/strict";

describe("PHASE 18A.2D — Store Disconnect Targeting & Agency Multi-Store Selection", () => {
  // Helper modeling StoreSettingsDrawer targeting logic
  function resolveDisconnectTarget(props: {
    storeId?: string;
    initialShopDomain?: string;
    initialStoreName?: string;
    editedShopDomainInput?: string;
  }) {
    const targetSelector = props.storeId || props.initialShopDomain;
    const targetDisplayName = props.initialShopDomain || props.initialStoreName || "Shopify Store";
    const canDisconnect = Boolean(targetSelector);

    return {
      targetSelector,
      targetDisplayName,
      canDisconnect,
    };
  }

  // Helper modeling page.tsx multi-store selection state machine
  function resolveActiveStore(
    stores: Array<{ id: string; shop_domain: string; metadata?: { name?: string } }>,
    currentSelectedId: string | null
  ) {
    if (!stores || stores.length === 0) {
      return {
        selectedStore: null,
        nextSelectedId: null,
      };
    }

    const matched = stores.find((s) => s.id === currentSelectedId);
    if (matched) {
      return {
        selectedStore: matched,
        nextSelectedId: matched.id,
      };
    }

    // Default to first available store if currentSelectedId is null or stale
    return {
      selectedStore: stores[0],
      nextSelectedId: stores[0].id,
    };
  }

  it("1. Edited domain input does not change the disconnect target", () => {
    const resolution = resolveDisconnectTarget({
      storeId: "store-uuid-001",
      initialShopDomain: "merchant-original.myshopify.com",
      initialStoreName: "Original Brand",
      editedShopDomainInput: "malicious-takeover.myshopify.com", // user edited form input
    });

    assert.strictEqual(resolution.canDisconnect, true);
    assert.strictEqual(
      resolution.targetSelector,
      "store-uuid-001",
      "Must target immutable storeId regardless of user input"
    );
  });

  it("2. Confirmation dialog shows the selected immutable store display name", () => {
    const resolution = resolveDisconnectTarget({
      storeId: "store-uuid-002",
      initialShopDomain: "authentic-store.myshopify.com",
      initialStoreName: "Authentic Store",
      editedShopDomainInput: "different-name.myshopify.com",
    });

    assert.strictEqual(
      resolution.targetDisplayName,
      "authentic-store.myshopify.com",
      "Confirmation dialog must display the immutable initial domain"
    );
    assert.strictEqual(resolution.canDisconnect, true);

    // Case where no valid store identifier is bound
    const unboundResolution = resolveDisconnectTarget({
      storeId: undefined,
      initialShopDomain: undefined,
      editedShopDomainInput: "attempted-domain.myshopify.com",
    });
    assert.strictEqual(unboundResolution.canDisconnect, false);
    assert.strictEqual(unboundResolution.targetSelector, undefined);
  });

  it("3. Agency users can select a non-first store", () => {
    const agencyStores = [
      { id: "store-alpha", shop_domain: "alpha.myshopify.com", metadata: { name: "Store Alpha" } },
      { id: "store-beta", shop_domain: "beta.myshopify.com", metadata: { name: "Store Beta" } },
      { id: "store-gamma", shop_domain: "gamma.myshopify.com", metadata: { name: "Store Gamma" } },
    ];

    // Selecting non-first store (Beta)
    const result = resolveActiveStore(agencyStores, "store-beta");
    assert.ok(result.selectedStore);
    assert.strictEqual(result.selectedStore.id, "store-beta");
    assert.strictEqual(result.selectedStore.shop_domain, "beta.myshopify.com");
    assert.strictEqual(result.nextSelectedId, "store-beta");
  });

  it("4. Disconnect targets the selected store ID in multi-store fleet", () => {
    const agencyStores = [
      { id: "store-alpha", shop_domain: "alpha.myshopify.com", metadata: { name: "Store Alpha" } },
      { id: "store-beta", shop_domain: "beta.myshopify.com", metadata: { name: "Store Beta" } },
    ];

    // User selected Store Beta
    const active = resolveActiveStore(agencyStores, "store-beta");
    assert.ok(active.selectedStore);

    const targetProps = {
      storeId: active.selectedStore.id,
      initialShopDomain: active.selectedStore.shop_domain,
      initialStoreName: active.selectedStore.metadata?.name,
      editedShopDomainInput: "tampered.myshopify.com",
    };

    const resolution = resolveDisconnectTarget(targetProps);
    assert.strictEqual(resolution.targetSelector, "store-beta");
    assert.strictEqual(resolution.targetDisplayName, "beta.myshopify.com");
    assert.strictEqual(resolution.canDisconnect, true);
  });

  it("5. After disconnect, selection updates safely without stale IDs", () => {
    // Initial fleet has Alpha and Beta
    const fleetBefore = [
      { id: "store-alpha", shop_domain: "alpha.myshopify.com" },
      { id: "store-beta", shop_domain: "beta.myshopify.com" },
    ];

    // User had Beta selected
    const initial = resolveActiveStore(fleetBefore, "store-beta");
    assert.strictEqual(initial.selectedStore?.id, "store-beta");

    // Beta was disconnected, fleet reloaded with only Alpha
    const fleetAfter = [
      { id: "store-alpha", shop_domain: "alpha.myshopify.com" },
    ];

    // Passing stale "store-beta" ID safely resolves to remaining store "store-alpha"
    const afterDisconnect = resolveActiveStore(fleetAfter, "store-beta");
    assert.strictEqual(
      afterDisconnect.selectedStore?.id,
      "store-alpha",
      "Stale disconnected ID must fall back to next remaining active store"
    );
    assert.strictEqual(afterDisconnect.nextSelectedId, "store-alpha");

    // When all stores disconnected (empty fleet)
    const emptyFleet: Array<{ id: string; shop_domain: string }> = [];
    const emptyResult = resolveActiveStore(emptyFleet, "store-alpha");
    assert.strictEqual(emptyResult.selectedStore, null);
    assert.strictEqual(emptyResult.nextSelectedId, null);
  });
});
