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
          DEFAULT: "#059669", // Emerald 600 (Stripe/Shopify Classic)
          foreground: "#ffffff",
        },
        accent: {
          DEFAULT: "#0284c7", // Electric Sky
          foreground: "#ffffff",
        },
        destructive: {
          DEFAULT: "#dc2626", // Red 600
          foreground: "#ffffff",
        },
        warning: {
          DEFAULT: "#d97706", // Amber 600
          foreground: "#ffffff",
        }
      },
      boxShadow: {
        "stripe-hairline": "var(--sys-hairline-specular)",
        "fluent-elevation": "var(--sys-shadow-ambient)",
        "emerald-radar": "0 0 20px -2px rgba(5, 150, 105, 0.2)",
        "xs": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        "2xs": "0 1px 1px 0 rgba(0, 0, 0, 0.03)",
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
