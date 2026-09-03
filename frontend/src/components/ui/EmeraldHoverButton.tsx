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
  xs: "px-2.5 py-1 text-[11px] rounded-lg gap-1.5",
  sm: "px-3.5 py-1.5 text-xs rounded-lg gap-1.5",
  md: "px-4 py-2 text-xs sm:text-sm rounded-xl gap-2",
  lg: "px-5 py-2.5 text-sm sm:text-base rounded-xl gap-2.5",
  xl: "px-7 py-3.5 text-base sm:text-lg rounded-2xl gap-3 font-bold",
};

/**
 * Uiverse-adapted Emerald Hover Fill Button.
 * Base: Midnight Obsidian (#08080A) & Shopify Emerald (#10B981).
 * Transition: Expands smooth emerald fill from corner to cover button on hover,
 * seamlessly shifting text to deep Midnight Obsidian (#08080A) for state-of-the-art contrast.
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
      "group relative inline-flex items-center justify-center font-semibold select-none overflow-hidden transition-all duration-300 cursor-pointer active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed";

    // Variant configurations
    let variantClasses = "";
    let fillElement: React.ReactNode = null;

    if (variant === "primary") {
      variantClasses =
        "border border-emerald-500/60 bg-transparent text-emerald-400 hover:border-emerald-400 hover:shadow-[0_0_25px_rgba(16,185,129,0.35)] active:border-emerald-600";
      fillElement = (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-[20px] -right-[20px] h-0 w-0 rounded-full bg-emerald-500 transition-all duration-700 ease-out group-hover:-top-[30px] group-hover:-left-[30px] group-hover:h-[calc(100%+60px)] group-hover:w-[calc(100%+60px)] group-hover:rounded-none group-active:bg-emerald-600 -z-10"
        />
      );
    } else if (variant === "solid") {
      variantClasses =
        "border border-emerald-500 bg-emerald-500 text-[#08080A] shadow-[0_0_20px_rgba(16,185,129,0.3)] hover:bg-emerald-400 hover:border-emerald-400 hover:shadow-[0_0_30px_rgba(16,185,129,0.5)] active:bg-emerald-600";
      fillElement = (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-white/20 opacity-0 transition-opacity duration-300 group-hover:opacity-100 -z-10"
        />
      );
    } else if (variant === "ghost") {
      variantClasses =
        "border border-zinc-700/60 bg-zinc-900/60 text-zinc-300 hover:border-emerald-500/50 hover:text-white hover:shadow-[0_0_20px_rgba(16,185,129,0.15)]";
      fillElement = (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-[20px] -right-[20px] h-0 w-0 rounded-full bg-emerald-500/20 transition-all duration-700 ease-out group-hover:-top-[30px] group-hover:-left-[30px] group-hover:h-[calc(100%+60px)] group-hover:w-[calc(100%+60px)] group-hover:rounded-none group-active:bg-emerald-500/30 -z-10"
        />
      );
    } else if (variant === "outline" || variant === "secondary") {
      variantClasses =
        "border border-white/[0.12] bg-[#0E0E12]/80 backdrop-blur-md text-zinc-200 hover:border-emerald-500/50 hover:shadow-[0_0_20px_rgba(16,185,129,0.2)]";
      fillElement = (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-[20px] -right-[20px] h-0 w-0 rounded-full bg-emerald-500 transition-all duration-700 ease-out group-hover:-top-[30px] group-hover:-left-[30px] group-hover:h-[calc(100%+60px)] group-hover:w-[calc(100%+60px)] group-hover:rounded-none group-active:bg-emerald-600 -z-10"
        />
      );
    } else if (variant === "destructive") {
      variantClasses =
        "border border-rose-500/50 bg-rose-500/10 text-rose-400 hover:border-rose-400 hover:shadow-[0_0_20px_rgba(244,63,94,0.3)]";
      fillElement = (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-[20px] -right-[20px] h-0 w-0 rounded-full bg-rose-500 transition-all duration-700 ease-out group-hover:-top-[30px] group-hover:-left-[30px] group-hover:h-[calc(100%+60px)] group-hover:w-[calc(100%+60px)] group-hover:rounded-none group-active:bg-rose-600 -z-10"
        />
      );
    }

    // Text color transition for primary/outline variants where text flips to obsidian
    const textClasses =
      variant === "primary" || variant === "outline" || variant === "secondary"
        ? "relative z-10 flex items-center justify-center gap-2 transition-colors duration-300 group-hover:text-[#08080A]"
        : variant === "destructive"
        ? "relative z-10 flex items-center justify-center gap-2 transition-colors duration-300 group-hover:text-white"
        : "relative z-10 flex items-center justify-center gap-2 transition-colors duration-300";

    const content = (
      <>
        {fillElement}
        <span className={textClasses}>
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          ) : icon && iconPosition === "left" ? (
            <span className="shrink-0 transition-transform duration-200 group-hover:scale-110">
              {icon}
            </span>
          ) : null}

          {isLoading && loadingText ? (
            <span>{loadingText}</span>
          ) : (
            <span>{children}</span>
          )}

          {!isLoading && icon && iconPosition === "right" && (
            <span className="shrink-0 transition-transform duration-200 group-hover:translate-x-0.5">
              {icon}
            </span>
          )}
        </span>
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
