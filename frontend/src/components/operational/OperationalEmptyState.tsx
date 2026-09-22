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
      className={`relative overflow-hidden rounded-lg bg-white border border-slate-200 p-8 md:p-12 text-center shadow-xs flex flex-col items-center justify-center ${className}`}
    >
      <div className="p-3.5 rounded-lg bg-slate-50 border border-slate-200 text-slate-400 mb-3.5">
        {icon || <FolderX className="w-7 h-7 text-slate-400" />}
      </div>

      <span className="px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200 text-[10px] font-mono font-medium tracking-wider uppercase mb-2.5">
        {badge}
      </span>

      <h3 className="text-base font-semibold text-slate-900 tracking-tight mb-1.5 max-w-md">
        {title}
      </h3>

      <p className="text-xs text-slate-500 leading-relaxed max-w-lg mb-5">
        {description}
      </p>

      {action && (
        action.href ? (
          <a
            href={action.href}
            className="inline-flex items-center justify-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold h-9 px-4 rounded-md shadow-xs transition-colors text-xs cursor-pointer"
          >
            <PlusCircle className="w-4 h-4" />
            <span>{action.label}</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </a>
        ) : (
          <button
            type="button"
            onClick={action.onClick}
            className="inline-flex items-center justify-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold h-9 px-4 rounded-md shadow-xs transition-colors text-xs cursor-pointer"
          >
            <PlusCircle className="w-4 h-4" />
            <span>{action.label}</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        )
      )}
    </div>
  );
}

export default OperationalEmptyState;
