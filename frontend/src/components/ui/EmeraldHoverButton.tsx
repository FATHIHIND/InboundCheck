"use client";

import React, { forwardRef } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

export type EmeraldButtonVariant =
  | "primary"
  | "solid"
  | "secondary"
  | "outline"
  | "ghost"
  | "destructive";

export type EmeraldButtonSize = "xs" | "sm" | "md" | "lg" | "xl";

export interface EmeraldHoverButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual variant styling */
  variant?: EmeraldButtonVariant;
  /** Size dimension scaling */
  size?: EmeraldButtonSize;
  /** Displays spinning loading indicator and prevents interaction */
  isLoading?: boolean;
  /** Loading text replacement */
  loadingText?: string;
  /** Optional icon rendered next to text */
  icon?: React.ReactNode;
  /** Icon placement relative to children */
  iconPosition?: "left" | "right";
  /** Optional Next.js link href — renders as a Link when provided */
  href?: string;
  /** Children elements */
  children?: React.ReactNode;
  /** Additional CSS classes */
  className?: string;
}

const SIZE_STYLES: Record<EmeraldButtonSize, string> = {
  xs: "h-7 px-2.5 text-[11px] rounded-md gap-1",
  sm: "h-8 px-3 text-xs rounded-md gap-1.5",
  md: "h-9 px-4 text-xs sm:text-sm rounded-md gap-2",
  lg: "h-10 px-5 text-sm rounded-md gap-2.5",
  xl: "h-11 px-6 text-base rounded-lg gap-3 font-semibold",
};

/**
 * Enterprise B2B SaaS Standard Button (Style Option A: Stripe / Shopify Admin Classic).
 * Primary: Solid Shopify Emerald (bg-emerald-600 hover:bg-emerald-700 text-white)
 * Secondary / Outline: High-contrast white border-slate-300 text-slate-700
 */
export const EmeraldHoverButton = forwardRef<
  HTMLButtonElement,
  EmeraldHoverButtonProps
>(
  (
    {
      variant = "primary",
      size = "md",
      isLoading = false,
      loadingText,
      icon,
      iconPosition = "left",
      href,
      children,
      className = "",
      disabled,
      type = "button",
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || isLoading;

    // Base button structure
    const baseClasses =
      "inline-flex items-center justify-center font-semibold select-none transition-colors duration-150 cursor-pointer active:scale-[0.99] disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed shadow-xs";

    // Variant configurations
    let variantClasses = "";

    if (variant === "primary" || variant === "solid") {
      variantClasses =
        "bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 text-white border border-transparent";
    } else if (variant === "secondary" || variant === "outline") {
      variantClasses =
        "bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-700 border border-slate-300 shadow-2xs font-medium";
    } else if (variant === "ghost") {
      variantClasses =
        "bg-transparent hover:bg-slate-100 active:bg-slate-200 text-slate-600 hover:text-slate-900 border border-transparent shadow-none font-medium";
    } else if (variant === "destructive") {
      variantClasses =
        "bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white border border-transparent";
    }

    const content = (
      <>
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin shrink-0" />
        ) : icon && iconPosition === "left" ? (
          <span className="shrink-0 flex items-center justify-center">
            {icon}
          </span>
        ) : null}

        {isLoading && loadingText ? (
          <span>{loadingText}</span>
        ) : (
          <span>{children}</span>
        )}

        {!isLoading && icon && iconPosition === "right" && (
          <span className="shrink-0 flex items-center justify-center">
            {icon}
          </span>
        )}
      </>
    );

    const combinedClassName = `${baseClasses} ${SIZE_STYLES[size]} ${variantClasses} ${className}`;

    if (href && !isDisabled) {
      return (
        <Link href={href} className={combinedClassName}>
          {content}
        </Link>
      );
    }

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        className={combinedClassName}
        {...props}
      >
        {content}
      </button>
    );
  }
);

EmeraldHoverButton.displayName = "EmeraldHoverButton";

export default EmeraldHoverButton;
