"use client";

import { useEffect, useRef } from "react";

interface AccessibleDialogProps {
  isOpen: boolean;
  onClose?: () => void;
  labelledBy: string;
  children: React.ReactNode;
  className?: string;
  panelClassName?: string;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/**
 * Shared modal/drawer shell with focus containment, Escape dismissal, focus
 * restoration, and document scroll locking. It deliberately owns no product
 * behavior so existing flows can adopt it without changing their contracts.
 */
export function AccessibleDialog({
  isOpen,
  onClose,
  labelledBy,
  children,
  className = "",
  panelClassName = "",
  closeOnBackdrop = true,
  closeOnEscape = true,
}: AccessibleDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusFirstElement = () => {
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      (focusable?.[0] || dialogRef.current)?.focus();
    };
    const focusTimer = window.setTimeout(focusFirstElement, 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && closeOnEscape && onClose) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? []
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = originalOverflow;
      previousFocusRef.current?.focus();
    };
  }, [isOpen, onClose, closeOnEscape]);

  if (!isOpen) return null;

  return (
    <div
      className={`fixed inset-0 z-50 flex bg-slate-900/60 backdrop-blur-sm ${className}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && closeOnBackdrop && onClose) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={panelClassName}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

export default AccessibleDialog;
