import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        border: {
          DEFAULT: "hsl(var(--border))",
          subtle: "var(--sys-border-subtle)",
          default: "var(--sys-border-default)",
          highlight: "var(--sys-border-highlight)",
        },
        obsidian: {
          canvas: "hsl(var(--obsidian-black))",
          950: "hsl(var(--obsidian-950))",
          900: "hsl(var(--obsidian-900))",
          850: "hsl(var(--obsidian-850))",
          800: "hsl(var(--obsidian-800))",
        },
        shopify: {
          DEFAULT: "#008060",
          green: "hsl(var(--shopify-green))",
          dark: "hsl(var(--shopify-dark))",
        },
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        "card-foreground": "hsl(var(--card-foreground))",
        primary: {
          DEFAULT: "#10b981", // Emerald Neon
          foreground: "#000000",
        },
        accent: {
          DEFAULT: "#06b6d4", // Electric Cyan
          foreground: "#ffffff",
        },
        destructive: {
          DEFAULT: "#ef4444",
          foreground: "#ffffff",
        },
        warning: {
          DEFAULT: "#f59e0b",
          foreground: "#000000",
        }
      },
      boxShadow: {
        "stripe-hairline": "var(--sys-hairline-specular)",
        "fluent-elevation": "var(--sys-hairline-specular), var(--sys-shadow-ambient)",
        "emerald-radar": "0 0 25px -4px rgba(16, 185, 129, 0.25)",
      },
      transitionTimingFunction: {
        "apple-spring": "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      keyframes: {
        marquee: {
          "0%": { transform: "translateX(0%)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
      animation: {
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        marquee: "marquee 30s linear infinite",
      }
    },
  },
  plugins: [],
};
export default config;
