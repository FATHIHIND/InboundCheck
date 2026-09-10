"use client";

import React, { ReactNode } from "react";
import { FolderX, ArrowRight, PlusCircle } from "lucide-react";

interface OperationalEmptyStateProps {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
  className?: string;
  badge?: string;
}

export function OperationalEmptyState({
  icon,
  title,
  description,
  action,
  className = "",
  badge = "Awaiting Onboarding",
}: OperationalEmptyStateProps) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl bg-[#0E0E12]/80 border border-white/10 p-8 md:p-12 text-center backdrop-blur-xl shadow-xl flex flex-col items-center justify-center ${className}`}
    >
      <div className="p-4 rounded-2xl bg-white/[0.03] border border-white/10 text-zinc-400 mb-4 shadow-inner">
        {icon || <FolderX className="w-8 h-8 text-zinc-500" />}
      </div>

      <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[11px] font-medium tracking-wide uppercase font-mono mb-3">
        {badge}
      </span>

      <h3 className="text-lg font-semibold text-white tracking-tight mb-2 max-w-md">
        {title}
      </h3>

      <p className="text-sm text-zinc-400 leading-relaxed max-w-lg mb-6">
        {description}
      </p>

      {action && (
        action.href ? (
          <a
            href={action.href}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-black font-semibold text-xs transition-all shadow-lg shadow-emerald-500/20 active:scale-95"
          >
            <PlusCircle className="w-4 h-4" />
            {action.label}
            <ArrowRight className="w-3.5 h-3.5 ml-0.5" />
          </a>
        ) : (
          <button
            type="button"
            onClick={action.onClick}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-black font-semibold text-xs transition-all shadow-lg shadow-emerald-500/20 active:scale-95"
          >
            <PlusCircle className="w-4 h-4" />
            {action.label}
            <ArrowRight className="w-3.5 h-3.5 ml-0.5" />
          </button>
        )
      )}
    </div>
  );
}
