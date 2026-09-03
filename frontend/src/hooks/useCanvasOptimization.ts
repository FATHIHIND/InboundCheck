import { useEffect, useRef, useState } from "react";

export interface CanvasOptimizationOptions {
  onVisibilityChange?: (isVisible: boolean) => void;
  renderStaticFrame?: () => void;
}

/**
 * Custom hook for high-performance canvas rendering.
 * Provides:
 * 1. Viewport IntersectionObserver to pause rendering when canvas is scrolled off-screen.
 * 2. Page Visibility API to pause rendering when the browser tab is inactive.
 * 3. prefers-reduced-motion media query to render a single static frame for users with vestibular sensitivities.
 */
export function useCanvasOptimization(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  options?: CanvasOptimizationOptions
) {
  const isVisibleRef = useRef<boolean>(true);
  const prefersReducedMotionRef = useRef<boolean>(false);
  const [shouldAnimate, setShouldAnimate] = useState<boolean>(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // 1. Reduced Motion Preference
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    prefersReducedMotionRef.current = motionQuery.matches;

    const handleMotionChange = (e: MediaQueryListEvent) => {
      prefersReducedMotionRef.current = e.matches;
      updateState();
    };

    if (motionQuery.addEventListener) {
      motionQuery.addEventListener("change", handleMotionChange);
    } else {
      motionQuery.addListener(handleMotionChange);
    }

    // 2. Tab Visibility (Page Visibility API)
    let isTabVisible = !document.hidden;
    const handleVisibilityChange = () => {
      isTabVisible = !document.hidden;
      updateState();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    // 3. Viewport Intersection Observer
    let isIntersecting = true;
    const observer = new IntersectionObserver(
      ([entry]) => {
        isIntersecting = entry.isIntersecting;
        updateState();
      },
      { threshold: 0.05 }
    );
    observer.observe(canvas);

    const updateState = () => {
      const active = isTabVisible && isIntersecting && !prefersReducedMotionRef.current;
      isVisibleRef.current = active;
      setShouldAnimate(active);

      if (options?.onVisibilityChange) {
        options.onVisibilityChange(active);
      }
      if (prefersReducedMotionRef.current && options?.renderStaticFrame) {
        options.renderStaticFrame();
      }
    };

    updateState();

    return () => {
      if (motionQuery.removeEventListener) {
        motionQuery.removeEventListener("change", handleMotionChange);
      } else {
        motionQuery.removeListener(handleMotionChange);
      }
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      observer.disconnect();
    };
  }, [canvasRef, options]);

  return { isVisibleRef, prefersReducedMotionRef, shouldAnimate };
}
